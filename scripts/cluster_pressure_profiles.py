"""
Cluster provider-specialty series by their pressure profile.

Design (confirmed with Vedant, 2026-08 continuation session): cluster the
~300 provider-specialty combinations (12 core trusts x their treatment
functions), not individual provider-specialty-months — a time-collapsed
profile per series is what actually supports a peer-grouping narrative
("these specialties behave alike across trusts"), not a per-month cluster
that would mostly just track the calendar.

Features: the mean of the same six standardized pressure-index inputs
(rtt_growth, rtt_over18_share, rtt_over52_share, dm01_breach, ae_pressure,
kh03_occupancy) across all available months for that provider-specialty —
deliberately the SAME six signals the pressure index itself uses, so
clusters describe a genuine multi-dimensional profile shape (e.g. "high RTT
growth but average bed pressure" vs "average RTT but high A&E pressure"),
not just a re-sorting of the one-dimensional composite score. The composite
pressure_index_0_100 is carried through as a label for interpretation only,
never as a clustering input (that would be circular).

k selection: KMeans for k=2..8, silhouette score picks the winner —
statistically derived, consistent with how the pressure index's own
weights were chosen, rather than an arbitrary "3 tiers" assumption.

Monte Carlo (per Vedant's "wherever viable" steer): 1,000-iteration
bootstrap — resample the ~300 rows with replacement, fit KMeans on the
resample, predict labels for the ORIGINAL (non-resampled) rows using the
resample-fitted centroids, and compute the Adjusted Rand Index against the
baseline (full-data) clustering. ARI is permutation-invariant, so it
doesn't matter that cluster label numbers can flip between fits — it
measures whether the same items keep ending up grouped together.
"""
import os
import shutil

import duckdb
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PROJECT_ROOT, "nhs_warehouse.db")
BUILD_DB = f"/tmp/nhs_wh_cluster_build_{os.getpid()}.db"

FEATURE_COLS = ["rtt_growth", "rtt_over18_share", "rtt_over52_share",
                 "dm01_breach", "ae_pressure", "kh03_occupancy"]
K_RANGE = range(2, 9)
N_BOOTSTRAP = 1000
RNG_SEED = 42


def main():
    print("== Copying current warehouse into /tmp ==", flush=True)
    if os.path.exists(BUILD_DB):
        os.remove(BUILD_DB)
    shutil.copy(PROJECT_DB, BUILD_DB)
    con = duckdb.connect(BUILD_DB)

    panel = con.execute(f"""
        select provider_org_code, treatment_function_code,
               {', '.join(FEATURE_COLS)}, pressure_index_0_100
        from fact_elective_pressure_index_provider_specialty_month
    """).fetchdf()

    # Time-collapse: mean per provider-specialty, skipping nulls per column
    # rather than dropping whole months (a series with 1-2 null months out
    # of 84 shouldn't lose its whole profile over that).
    profile = (
        panel.groupby(["provider_org_code", "treatment_function_code"])
        .agg({**{c: "mean" for c in FEATURE_COLS}, "pressure_index_0_100": "mean"})
        .reset_index()
    )
    n_months_seen = (
        panel.groupby(["provider_org_code", "treatment_function_code"]).size().rename("n_months")
    )
    profile = profile.merge(n_months_seen, on=["provider_org_code", "treatment_function_code"])
    print(f"Provider-specialty profiles: {len(profile)}")

    complete = profile.dropna(subset=FEATURE_COLS).reset_index(drop=True)
    print(f"Complete-case profiles usable for clustering: {len(complete)} / {len(profile)}")

    scaler = StandardScaler()
    X = scaler.fit_transform(complete[FEATURE_COLS])

    # ---- k selection via silhouette ----
    print("\n== k selection (silhouette score) ==")
    sil_scores = {}
    for k in K_RANGE:
        km = KMeans(n_clusters=k, n_init=20, random_state=RNG_SEED).fit(X)
        sil = silhouette_score(X, km.labels_)
        sil_scores[k] = sil
        print(f"  k={k}: silhouette={sil:.4f}")
    best_k = max(sil_scores, key=sil_scores.get)
    print(f"-> chosen k = {best_k}")

    baseline_km = KMeans(n_clusters=best_k, n_init=50, random_state=RNG_SEED).fit(X)
    complete["cluster"] = baseline_km.labels_

    # ---- Cluster interpretation: centroid z-scores relative to overall mean ----
    print(f"\n== Cluster centroids (k={best_k}), standardized units — |z| > 0.5 called out ==")
    centroid_rows = []
    for c in range(best_k):
        mask = complete["cluster"] == c
        n = mask.sum()
        centroid_z = X[mask].mean(axis=0)
        row = {"cluster": c, "n_series": int(n),
               "mean_pressure_index": complete.loc[mask, "pressure_index_0_100"].mean()}
        distinguishing = []
        for f, z in zip(FEATURE_COLS, centroid_z):
            row[f"{f}_z"] = z
            if abs(z) > 0.5:
                distinguishing.append(f"{f}={z:+.2f}")
        centroid_rows.append(row)
        print(f"  cluster {c}: n={n}, mean_pressure_index={row['mean_pressure_index']:.1f}, "
              f"distinguishing features: {', '.join(distinguishing) if distinguishing else '(none > 0.5 SD)'}")
    centroid_summary = pd.DataFrame(centroid_rows)

    # Spot check: where does REM's own specialties land?
    rem = complete[complete["provider_org_code"] == "REM"][
        ["treatment_function_code", "cluster", "pressure_index_0_100"]
    ].sort_values("cluster")
    print("\nREM specialties by cluster (spot check):")
    print(rem.to_string(index=False))

    # ---- Monte Carlo cluster stability ----
    print(f"\n== Monte Carlo cluster stability ({N_BOOTSTRAP} bootstrap resamples) ==")
    rng = np.random.default_rng(RNG_SEED)
    n = len(complete)
    aris = np.zeros(N_BOOTSTRAP)
    for b in range(N_BOOTSTRAP):
        idx = rng.integers(0, n, size=n)
        X_boot = X[idx]
        km_boot = KMeans(n_clusters=best_k, n_init=5, random_state=int(rng.integers(0, 1_000_000))).fit(X_boot)
        boot_labels_on_full = km_boot.predict(X)
        aris[b] = adjusted_rand_score(baseline_km.labels_, boot_labels_on_full)
        if (b + 1) % 250 == 0:
            print(f"  bootstrap {b + 1}/{N_BOOTSTRAP}")

    print(f"\nAdjusted Rand Index vs. baseline clustering: mean={aris.mean():.4f}, "
          f"std={aris.std():.4f}, p5={np.percentile(aris, 5):.4f}, p95={np.percentile(aris, 95):.4f}")
    print("Interpretation: ARI near 1.0 means the clustering is stable under resampling; "
          "ARI near 0 means it's close to random and shouldn't be over-narrated.")

    cluster_stability = pd.DataFrame({
        "k": [best_k], "n_bootstrap": [N_BOOTSTRAP],
        "mean_ari": [aris.mean()], "std_ari": [aris.std()],
        "p5_ari": [np.percentile(aris, 5)], "p95_ari": [np.percentile(aris, 95)],
    })

    # ---- Write tables ----
    out = complete[["provider_org_code", "treatment_function_code", "n_months", "cluster",
                     "pressure_index_0_100"] + FEATURE_COLS]
    con.execute("DROP TABLE IF EXISTS ref_pressure_profile_clusters")
    con.register("out_df", out)
    con.execute("CREATE TABLE ref_pressure_profile_clusters AS SELECT * FROM out_df")

    con.execute("DROP TABLE IF EXISTS ref_pressure_cluster_centroids")
    con.register("centroid_df", centroid_summary)
    con.execute("CREATE TABLE ref_pressure_cluster_centroids AS SELECT * FROM centroid_df")

    con.execute("DROP TABLE IF EXISTS ref_pressure_cluster_stability")
    con.register("stab_df", cluster_stability)
    con.execute("CREATE TABLE ref_pressure_cluster_stability AS SELECT * FROM stab_df")

    con.close()

    print("\n== Copying build DB back to project mount ==")
    tmp_final = f"/tmp/nhs_wh_cluster_final_{os.getpid()}.db"
    shutil.copy(BUILD_DB, tmp_final)
    shutil.copy(tmp_final, PROJECT_DB)
    verify = duckdb.connect(PROJECT_DB, read_only=True)
    print(verify.execute("select count(*) from ref_pressure_profile_clusters").fetchone())
    verify.close()
    print("Done.")


if __name__ == "__main__":
    main()
