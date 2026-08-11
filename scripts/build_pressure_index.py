"""
Build the elective pressure index: fact_elective_pressure_index_provider_specialty_month.

Design (confirmed with Vedant, 2026-08 continuation session):
  - Grain: provider-specialty-month (native RTT/DM01 grain). DM01/A&E/KH03 modifiers
    are only available at provider-month, so they're broadcast uniformly across all
    specialties for a given provider-month (documented limitation, not hidden).
  - Weighting: statistically derived via PCA (PC1 loadings on the 6 standardized
    pressure signals), not fixed analyst weights. Robustness/sensitivity testing of
    these weights (perturbation, bootstrap, Monte Carlo) is explicitly deferred to
    the next phase (task: Python analytics layer / Monte Carlo simulation), per
    Vedant's instruction — this script derives the weights, it does not stress-test
    them.
  - Scope: the 12 core NHS trusts (dim_provider.in_core_analysis = true) — i.e. the
    trusts with real RTT elective activity. Independent-sector providers and RW4
    (Mersey Care, mental health, negligible RTT volume) are excluded, consistent
    with every prior scoping decision in this project.

Six input signals, all oriented so higher = more pressure:
  1. rtt_growth        RTT waiting list size vs. own provider-specialty Apr-Jun 2019
                        baseline (ratio - 1)
  2. rtt_over18_share   long_wait_share_18wk (given directly in fact_rtt table)
  3. rtt_over52_share   waiting_list_over_52wk / waiting_list_size
  4. dm01_breach        long_wait_share_6wk (provider-month, broadcast to specialties)
  5. ae_pressure        1 - pct_seen_within_4hr (provider-month, broadcast; REN has no
                         A&E department, so its value is imputed as the cohort's
                         core-provider mean for that month and flagged)
  6. kh03_occupancy     pct_occupied_ga (provider-quarter, mapped to every month in
                         that calendar quarter, broadcast to specialties)

Environment notes carried over from the rest of this project (see docs/STATUS.md):
  - Never write directly to nhs_warehouse.db on the synced project mount (WAL
    checkpoint fails with "Operation not permitted"). Build in /tmp, copy back.
  - If a stale .wal file blocks re-opening the copied .db, `mv` it out of the way;
    `rm` is blocked by the same mount restriction.
"""
import os
import re
import shutil
from datetime import date

import duckdb
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PROJECT_ROOT, "nhs_warehouse.db")
# Build in /tmp rather than directly on the synced project mount — same
# WAL-checkpoint permission quirk documented in build_warehouse.py and
# docs/STATUS.md. Copy the current warehouse in, add the new tables, copy
# the whole file back as the last step.
BUILD_DB = f"/tmp/nhs_wh_pressure_build_{os.getpid()}.db"

MONTH_RE = re.compile(r"^[A-Za-z0-9]+-([A-Za-z]+)-(\d{4})$")


def parse_period(period: str) -> date:
    """'RTT-APRIL-2019' / 'DM01-April-2019' / 'MSitAE-april-2019' -> date(2019,4,1)."""
    m = MONTH_RE.match(period)
    if not m:
        raise ValueError(f"Unrecognised period format: {period!r}")
    month_name, year = m.group(1), int(m.group(2))
    month_num = pd.to_datetime(f"{month_name} 1 2000", format="%B %d %Y").month
    return date(year, month_num, 1)


def quarter_end_for_month(d: date) -> date:
    """Calendar quarter-end date (Mar31/Jun30/Sep30/Dec31) that month d belongs to."""
    q_month = ((d.month - 1) // 3 + 1) * 3
    if q_month == 12:
        return date(d.year, 12, 31)
    # last day of q_month = first day of next month minus 1 day
    next_month_first = date(d.year, q_month + 1, 1)
    return next_month_first - pd.Timedelta(days=1)


def main():
    print("== Copying current warehouse into /tmp for a clean build ==", flush=True)
    if os.path.exists(BUILD_DB):
        os.remove(BUILD_DB)
    shutil.copy(PROJECT_DB, BUILD_DB)
    con = duckdb.connect(BUILD_DB)

    core_providers = con.execute(
        "select provider_org_code from dim_provider where in_core_analysis"
    ).fetchdf()["provider_org_code"].tolist()
    print(f"Core providers (n={len(core_providers)}): {core_providers}")

    placeholders = ",".join(f"'{c}'" for c in core_providers)

    # ---- RTT core (provider-specialty-month) ----
    # Excludes C_999: confirmed against stg_rtt_raw ('Total') and by direct
    # arithmetic check that C_999.waiting_list_size == sum of every other
    # treatment_function_code for the same provider-month (zero mismatches).
    # It's an NHS-published pseudo-row, not a real specialty -- including it
    # here was a real bug (fixed 2026-08, see docs/STATUS.md): it added a
    # fake 13th "specialty" per provider into the PCA fit and the 0-100
    # percentile rescaling, silently reusing the same pressure signals under
    # a code that's mechanically just an aggregate of the other 12-13 rows.
    rtt = con.execute(f"""
        select provider_org_code, treatment_function_code, period,
               waiting_list_size, waiting_list_over_18wk, waiting_list_over_52wk,
               long_wait_share_18wk
        from fact_rtt_provider_specialty_month
        where provider_org_code in ({placeholders})
          and treatment_function_code <> 'C_999'
    """).fetchdf()
    rtt["period_month"] = rtt["period"].apply(parse_period)
    rtt["rtt_over52_share"] = rtt["waiting_list_over_52wk"] / rtt["waiting_list_size"].replace(0, np.nan)

    # Baseline per (provider, specialty) = mean waiting_list_size over Apr-Jun 2019,
    # falling back to the earliest available month for any specialty missing that window
    # (RBS/RJR have 1-2 months of gaps elsewhere in the series per the coverage check,
    # but Apr-Jun 2019 coverage was confirmed present for all 12 core providers).
    baseline_window = rtt[rtt["period_month"] <= date(2019, 6, 1)]
    baseline = (
        baseline_window.groupby(["provider_org_code", "treatment_function_code"])["waiting_list_size"]
        .mean()
        .rename("baseline_wl")
    )
    earliest = (
        rtt.sort_values("period_month")
        .groupby(["provider_org_code", "treatment_function_code"])["waiting_list_size"]
        .first()
        .rename("earliest_wl")
    )
    rtt = rtt.merge(baseline, on=["provider_org_code", "treatment_function_code"], how="left")
    rtt = rtt.merge(earliest, on=["provider_org_code", "treatment_function_code"], how="left")
    rtt["baseline_wl"] = rtt["baseline_wl"].fillna(rtt["earliest_wl"])
    rtt["baseline_imputed"] = rtt["baseline_wl"].eq(rtt["earliest_wl"]) & baseline_window.empty
    rtt["rtt_growth"] = rtt["waiting_list_size"] / rtt["baseline_wl"].replace(0, np.nan) - 1

    n_specialty_rows = len(rtt)
    print(f"RTT core rows: {n_specialty_rows}")

    # ---- DM01 modifier (provider-month) ----
    dm01 = con.execute(f"""
        select provider_org_code, period, long_wait_share_6wk as dm01_breach
        from fact_dm01_provider_month
        where provider_org_code in ({placeholders})
    """).fetchdf()
    dm01["period_month"] = dm01["period"].apply(parse_period)
    dm01 = dm01[["provider_org_code", "period_month", "dm01_breach"]]

    # ---- A&E modifier (provider-month), impute REN as cohort mean, flagged ----
    ae = con.execute(f"""
        select provider_org_code, period, pct_seen_within_4hr
        from fact_ae_provider_month
        where provider_org_code in ({placeholders})
    """).fetchdf()
    ae["period_month"] = ae["period"].apply(parse_period)
    ae["ae_pressure"] = 1 - ae["pct_seen_within_4hr"]
    ae = ae[["provider_org_code", "period_month", "ae_pressure"]]

    all_months = sorted(rtt["period_month"].unique())
    cohort_mean_ae = ae.groupby("period_month")["ae_pressure"].mean().rename("cohort_ae_pressure")
    missing_ae_providers = set(core_providers) - set(ae["provider_org_code"].unique())
    print(f"Core providers with no A&E dept (imputed from cohort mean): {missing_ae_providers}")

    ae_full = pd.MultiIndex.from_product(
        [core_providers, all_months], names=["provider_org_code", "period_month"]
    ).to_frame(index=False)
    ae_full = ae_full.merge(ae, on=["provider_org_code", "period_month"], how="left")
    ae_full = ae_full.merge(cohort_mean_ae, on="period_month", how="left")
    ae_full["ae_pressure_imputed"] = ae_full["ae_pressure"].isna() & ae_full["cohort_ae_pressure"].notna()
    ae_full["ae_pressure"] = ae_full["ae_pressure"].fillna(ae_full["cohort_ae_pressure"])
    ae_full = ae_full[["provider_org_code", "period_month", "ae_pressure", "ae_pressure_imputed"]]

    # ---- KH03 modifier (provider-quarter -> every month in that calendar quarter) ----
    kh03 = con.execute(f"""
        select provider_org_code, quarter_end_date, pct_occupied_ga
        from fact_kh03_provider_quarter
        where provider_org_code in ({placeholders})
    """).fetchdf()
    kh03["quarter_end_date"] = pd.to_datetime(kh03["quarter_end_date"]).dt.date

    month_to_qend = pd.DataFrame({"period_month": all_months})
    month_to_qend["quarter_end_date"] = month_to_qend["period_month"].apply(quarter_end_for_month)
    kh03_monthly = month_to_qend.merge(kh03, on="quarter_end_date", how="left")
    # cross join with providers happened implicitly via kh03's own provider column;
    # check coverage
    missing_kh03 = kh03_monthly[kh03_monthly["pct_occupied_ga"].isna()]
    if len(missing_kh03):
        print(f"WARNING: {len(missing_kh03)} provider-months have no KH03 quarter match "
              f"(months: {sorted(missing_kh03['period_month'].unique())[:5]}...)")
    kh03_monthly = kh03_monthly[["provider_org_code", "period_month", "pct_occupied_ga"]].rename(
        columns={"pct_occupied_ga": "kh03_occupancy"}
    )

    # ---- Assemble panel ----
    panel = rtt.merge(dm01, on=["provider_org_code", "period_month"], how="left")
    panel = panel.merge(ae_full, on=["provider_org_code", "period_month"], how="left")
    panel = panel.merge(kh03_monthly, on=["provider_org_code", "period_month"], how="left")

    print(f"Panel assembled: {len(panel)} rows")
    print("Null counts per feature:")
    feature_cols = ["rtt_growth", "long_wait_share_18wk", "rtt_over52_share",
                     "dm01_breach", "ae_pressure", "kh03_occupancy"]
    print(panel[feature_cols].isna().sum())

    # ---- Standardize + PCA ----
    fit_rows = panel.dropna(subset=feature_cols)
    print(f"Rows usable for PCA fit (complete cases): {len(fit_rows)} / {len(panel)}")

    scaler = StandardScaler()
    z = scaler.fit_transform(fit_rows[feature_cols])
    pca = PCA(n_components=1)
    pca.fit(z)
    loadings = pca.components_[0]
    explained_var = pca.explained_variance_ratio_[0]

    # Orient sign so the index correlates positively with rtt_over18_share (the most
    # directly interpretable core RTT signal) rather than an arbitrary PCA sign.
    pc1_scores_fit = pca.transform(z)[:, 0]
    corr_check = np.corrcoef(pc1_scores_fit, fit_rows["long_wait_share_18wk"])[0, 1]
    sign = 1.0 if corr_check >= 0 else -1.0
    loadings = loadings * sign

    weights = pd.Series(loadings, index=feature_cols)
    print("\nPCA-derived loadings (sign-oriented, higher = more weight on pressure):")
    print(weights)
    print(f"Explained variance ratio (PC1): {explained_var:.4f}")
    for col in feature_cols:
        corr = np.corrcoef(fit_rows[col], pc1_scores_fit * sign)[0, 1]
        print(f"  corr(PC1, {col}) = {corr:.3f}")

    # Apply the fitted scaler+loadings to the FULL panel (rows with any missing
    # feature get a null index rather than a silently-imputed one — the imputation
    # already happened deliberately for ae_pressure only, and is flagged).
    all_z = pd.DataFrame(
        np.full((len(panel), len(feature_cols)), np.nan), columns=feature_cols, index=panel.index
    )
    complete_mask = panel[feature_cols].notna().all(axis=1)
    all_z.loc[complete_mask, feature_cols] = scaler.transform(panel.loc[complete_mask, feature_cols])
    panel["pressure_index_raw"] = (all_z[feature_cols] * weights).sum(axis=1, skipna=False)

    # Rescale to 0-100 via percentile rank across the full panel for readability.
    valid = panel["pressure_index_raw"].notna()
    panel.loc[valid, "pressure_index_0_100"] = (
        panel.loc[valid, "pressure_index_raw"].rank(pct=True) * 100
    )

    panel = panel.rename(columns={"long_wait_share_18wk": "rtt_over18_share"})
    out_cols = [
        "provider_org_code", "treatment_function_code", "period", "period_month",
        "waiting_list_size", "baseline_wl", "rtt_growth", "rtt_over18_share",
        "rtt_over52_share", "dm01_breach", "ae_pressure", "ae_pressure_imputed",
        "kh03_occupancy", "pressure_index_raw", "pressure_index_0_100",
    ]
    result = panel[out_cols].copy()

    # ---- Validation ----
    print("\n== Validation ==")
    assert result["rtt_over52_share"].dropna().between(0, 1.001).all(), "over52 share out of [0,1]"
    assert result["rtt_over18_share"].dropna().between(0, 1.001).all(), "over18 share out of [0,1]"
    over_check = (result["rtt_over52_share"] > result["rtt_over18_share"] + 0.02).sum()
    print(f"Rows where over52_share > over18_share + tolerance: {over_check} (should be ~0)")
    print(f"pressure_index_0_100 populated for {result['pressure_index_0_100'].notna().sum()} / {len(result)} rows")
    print(f"ae_pressure_imputed = True for {result['ae_pressure_imputed'].sum()} rows "
          f"(expect ~ 1 provider x 84 months x specialties present for REN)")

    # Spot check: REM should show the well-documented backlog trajectory in its
    # aggregate (sum across specialties) waiting list, corroborated earlier in
    # this project's warehouse validation.
    rem_by_month = (
        result[result["provider_org_code"] == "REM"]
        .groupby("period_month")["waiting_list_size"].sum().sort_index()
    )
    print("\nREM total RTT waiting list (spot check vs known trajectory):")
    for d in [date(2019, 4, 1), date(2020, 4, 1), date(2022, 9, 1), date(2025, 9, 1)]:
        if d in rem_by_month.index:
            print(f"  {d}: {rem_by_month[d]:,.0f}")

    rem_index_trend = (
        result[result["provider_org_code"] == "REM"]
        .groupby("period_month")["pressure_index_0_100"].mean().sort_index()
    )
    print("\nREM mean pressure_index_0_100 by year (spot check — should rise into 2022, ease after):")
    print(rem_index_trend.groupby(rem_index_trend.index.map(lambda d: d.year)).mean())

    # ---- Write output table + weights metadata table ----
    con.execute("DROP TABLE IF EXISTS fact_elective_pressure_index_provider_specialty_month")
    con.execute("""
        CREATE TABLE fact_elective_pressure_index_provider_specialty_month (
            provider_org_code VARCHAR NOT NULL,
            treatment_function_code VARCHAR NOT NULL,
            period VARCHAR NOT NULL,
            period_month DATE NOT NULL,
            waiting_list_size HUGEINT,
            baseline_wl DOUBLE,
            rtt_growth DOUBLE,
            rtt_over18_share DOUBLE,
            rtt_over52_share DOUBLE,
            dm01_breach DOUBLE,
            ae_pressure DOUBLE,
            ae_pressure_imputed BOOLEAN,
            kh03_occupancy DOUBLE,
            pressure_index_raw DOUBLE,
            pressure_index_0_100 DOUBLE,
            PRIMARY KEY (provider_org_code, treatment_function_code, period)
        )
    """)
    con.register("result_df", result)
    con.execute("INSERT INTO fact_elective_pressure_index_provider_specialty_month SELECT * FROM result_df")

    con.execute("DROP TABLE IF EXISTS ref_pressure_index_pca_weights")
    con.execute("""
        CREATE TABLE ref_pressure_index_pca_weights (
            feature VARCHAR PRIMARY KEY,
            pca_loading DOUBLE,
            explained_variance_ratio DOUBLE,
            n_fit_rows INTEGER,
            built_date DATE
        )
    """)
    weights_df = weights.reset_index()
    weights_df.columns = ["feature", "pca_loading"]
    weights_df["explained_variance_ratio"] = explained_var
    weights_df["n_fit_rows"] = len(fit_rows)
    weights_df["built_date"] = date.today()
    con.register("weights_df", weights_df)
    con.execute("INSERT INTO ref_pressure_index_pca_weights SELECT * FROM weights_df")

    con.close()

    print("\n== Copying build DB back to project mount ==")
    tmp_final = f"/tmp/nhs_wh_pressure_final_{os.getpid()}.db"
    shutil.copy(BUILD_DB, tmp_final)
    try:
        shutil.copy(tmp_final, PROJECT_DB)
    except PermissionError as e:
        print(f"Direct copy failed ({e}), this matches the known WAL-checkpoint mount quirk.")
        raise
    print("Done. Verifying the copied warehouse opens cleanly...")
    verify = duckdb.connect(PROJECT_DB, read_only=True)
    n = verify.execute("select count(*) from fact_elective_pressure_index_provider_specialty_month").fetchone()[0]
    print(f"fact_elective_pressure_index_provider_specialty_month row count in project DB: {n}")
    verify.close()


if __name__ == "__main__":
    main()
