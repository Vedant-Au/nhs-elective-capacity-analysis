"""
Monte Carlo weight-sensitivity test for the elective pressure index.

Directly closes the caveat flagged when the index was first built
(docs/STATUS.md, 2026-08-08 continuation entry): PC1 explains only ~32% of
variance across the six signals, and dm01_breach loaded negative against the
other five. This script asks "how much does that matter" rather than leaving
it as an unresolved caveat — per Vedant's instruction to apply Monte Carlo
"wherever viable" across the analytics layer, not just as a one-off separate
phase.

Method: bootstrap resample the complete-case rows (same N, with replacement)
B times, refit StandardScaler + PCA(1) on each resample, and for every
resample:
  1. record the resulting PC1 loadings (sign-oriented the same way as the
     original build, via correlation with rtt_over18_share) — this gives a
     distribution per feature, not just the single point estimate the first
     build reported.
  2. apply those loadings to the FULL (non-resampled) standardized panel to
     get a bootstrap pressure_index_raw for every row, aggregate to a mean
     score per provider, rank providers, and Spearman-correlate that ranking
     against the baseline (original-weights) provider ranking. A high, tight
     distribution of rank correlations means the index's *ranking* is robust
     even if the exact loadings wobble; a low or wide one means it isn't.

Outputs two reference tables: ref_pressure_index_weight_sensitivity (per-
feature loading distribution + how often each feature's sign flips) and
ref_pressure_index_rank_stability (the distribution of provider-ranking
Spearman correlations across bootstrap iterations).
"""
import os
import shutil

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PROJECT_ROOT, "nhs_warehouse.db")
BUILD_DB = f"/tmp/nhs_wh_sensitivity_build_{os.getpid()}.db"

FEATURE_COLS = ["rtt_growth", "rtt_over18_share", "rtt_over52_share",
                 "dm01_breach", "ae_pressure", "kh03_occupancy"]
N_BOOTSTRAP = 2000
RNG_SEED = 42


def fit_pca(z: np.ndarray, sign_anchor: np.ndarray) -> np.ndarray:
    """Fit PCA(1) on standardized matrix z, orient sign via corr with sign_anchor."""
    pca = PCA(n_components=1)
    scores = pca.fit_transform(z)[:, 0]
    loadings = pca.components_[0]
    corr = np.corrcoef(scores, sign_anchor)[0, 1]
    sign = 1.0 if corr >= 0 else -1.0
    return loadings * sign


def main():
    print("== Copying current warehouse into /tmp ==", flush=True)
    if os.path.exists(BUILD_DB):
        os.remove(BUILD_DB)
    shutil.copy(PROJECT_DB, BUILD_DB)
    con = duckdb.connect(BUILD_DB)

    panel = con.execute(f"""
        select provider_org_code, treatment_function_code, period,
               {', '.join(FEATURE_COLS)}
        from fact_elective_pressure_index_provider_specialty_month
    """).fetchdf()

    complete = panel.dropna(subset=FEATURE_COLS).reset_index(drop=True)
    print(f"Complete-case rows: {len(complete)} / {len(panel)}")

    scaler = StandardScaler()
    z_full = scaler.fit_transform(complete[FEATURE_COLS])

    # Baseline (point-estimate) loadings and provider ranking, same as the
    # original build — recomputed here so this script is self-contained and
    # reproducible independent of the earlier run.
    baseline_loadings = fit_pca(z_full, complete["rtt_over18_share"].values)
    baseline_index = z_full @ baseline_loadings
    complete["_baseline_index"] = baseline_index
    baseline_provider_rank = (
        complete.groupby("provider_org_code")["_baseline_index"].mean().rank()
    )

    print("\nBaseline loadings (point estimate, matches build_pressure_index.py):")
    for f, w in zip(FEATURE_COLS, baseline_loadings):
        print(f"  {f}: {w:.4f}")

    # ---- Monte Carlo bootstrap ----
    rng = np.random.default_rng(RNG_SEED)
    n = len(complete)
    boot_loadings = np.zeros((N_BOOTSTRAP, len(FEATURE_COLS)))
    rank_corrs = np.zeros(N_BOOTSTRAP)

    for b in range(N_BOOTSTRAP):
        idx = rng.integers(0, n, size=n)
        z_boot = z_full[idx]
        anchor_boot = complete["rtt_over18_share"].values[idx]
        loadings_b = fit_pca(z_boot, anchor_boot)
        boot_loadings[b] = loadings_b

        # Apply this iteration's loadings to the FULL panel (not the resample)
        # to see how much the resulting provider ranking would move.
        index_b = z_full @ loadings_b
        provider_rank_b = (
            pd.Series(index_b, index=complete.index)
            .groupby(complete["provider_org_code"]).mean().rank()
        )
        rho, _ = spearmanr(baseline_provider_rank.sort_index(), provider_rank_b.sort_index())
        rank_corrs[b] = rho

        if (b + 1) % 500 == 0:
            print(f"  bootstrap {b + 1}/{N_BOOTSTRAP}")

    boot_df = pd.DataFrame(boot_loadings, columns=FEATURE_COLS)

    print("\n== Per-feature loading distribution across %d bootstrap resamples ==" % N_BOOTSTRAP)
    summary_rows = []
    for f in FEATURE_COLS:
        vals = boot_df[f]
        pct_negative = (vals < 0).mean()
        pct_positive = (vals > 0).mean()
        row = {
            "feature": f,
            "point_estimate": dict(zip(FEATURE_COLS, baseline_loadings))[f],
            "boot_mean": vals.mean(),
            "boot_std": vals.std(),
            "ci_low_p5": vals.quantile(0.05),
            "ci_high_p95": vals.quantile(0.95),
            "pct_bootstrap_negative": pct_negative,
            "pct_bootstrap_positive": pct_positive,
            "sign_stable": (pct_negative >= 0.95) or (pct_positive >= 0.95),
        }
        summary_rows.append(row)
        print(f"  {f}: point={row['point_estimate']:.3f}  boot_mean={row['boot_mean']:.3f} "
              f"+/- {row['boot_std']:.3f}  90%CI=[{row['ci_low_p5']:.3f}, {row['ci_high_p95']:.3f}]  "
              f"sign_stable={row['sign_stable']}  (neg in {pct_negative:.1%} of resamples)")
    weight_sensitivity = pd.DataFrame(summary_rows)

    print(f"\n== Provider-ranking stability across {N_BOOTSTRAP} resamples ==")
    print(f"Spearman rank correlation (bootstrap ranking vs. baseline ranking): "
          f"mean={rank_corrs.mean():.4f}, std={rank_corrs.std():.4f}, "
          f"p5={np.percentile(rank_corrs, 5):.4f}, p95={np.percentile(rank_corrs, 95):.4f}")
    print("Interpretation: values near 1.0 mean the provider-level pressure RANKING is "
          "stable even though the exact PCA loadings wobble across resamples; values "
          "further from 1.0 mean ranking conclusions should be treated cautiously.")

    rank_stability = pd.DataFrame({
        "n_bootstrap": [N_BOOTSTRAP],
        "mean_rank_correlation": [rank_corrs.mean()],
        "std_rank_correlation": [rank_corrs.std()],
        "p5_rank_correlation": [np.percentile(rank_corrs, 5)],
        "p95_rank_correlation": [np.percentile(rank_corrs, 95)],
        "min_rank_correlation": [rank_corrs.min()],
    })

    # ---- Write tables ----
    con.execute("DROP TABLE IF EXISTS ref_pressure_index_weight_sensitivity")
    con.register("ws_df", weight_sensitivity)
    con.execute("CREATE TABLE ref_pressure_index_weight_sensitivity AS SELECT * FROM ws_df")

    con.execute("DROP TABLE IF EXISTS ref_pressure_index_rank_stability")
    con.register("rs_df", rank_stability)
    con.execute("CREATE TABLE ref_pressure_index_rank_stability AS SELECT * FROM rs_df")

    con.close()

    print("\n== Copying build DB back to project mount ==")
    tmp_final = f"/tmp/nhs_wh_sensitivity_final_{os.getpid()}.db"
    shutil.copy(BUILD_DB, tmp_final)
    shutil.copy(tmp_final, PROJECT_DB)
    verify = duckdb.connect(PROJECT_DB, read_only=True)
    print(verify.execute("select * from ref_pressure_index_rank_stability").fetchdf().to_string())
    verify.close()
    print("Done.")


if __name__ == "__main__":
    main()
