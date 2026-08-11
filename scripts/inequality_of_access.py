"""
Inequality-of-access analysis: does elective pressure track this ICB's
already-established deprivation gradient?

Joins the pressure index (mean per core provider, across all months) and
workforce staffing intensity (contextual overlay, per the charter's
confirmed design: workforce/IMD are cross-referenced against the index as
findings, not blended into its formula) through dim_provider_local_authority
to dim_imd2019_local_authority.

HONEST SCOPE CAVEAT, stated up front rather than discovered at the end: this
is n=12 providers (the pressure index's core set) mapped to a handful of
distinct local authorities — a correlation over 12 points is suggestive, not
a powered statistical test. Reported with a bootstrap confidence interval
(Monte Carlo, per the "wherever viable" steer) specifically so the
uncertainty is visible rather than a single misleadingly precise coefficient
being the headline.

Catchment caveat handling: 5 of the 12 core providers are regional
specialist centres (RBQ, RBS, REN, REP, RET — Heart & Chest, Alder Hey,
Clatterbridge Cancer, Women's, Walton) whose single-LA assignment in
dim_provider_local_authority understates their real catchment (documented
there, not new information). Every correlation below is computed twice:
across all 12 providers, and across the 7 providers WITHOUT that caveat
(RBL, RBN, RBT, REM, RJN, RJR, RWW) whose assigned LA is a much more
reasonable proxy for where their patients actually come from.

IMD direction note, called out because it trips people up (already flagged
once in sql/schema/14_dim_imd2019_local_authority.sql): imd_avg_rank uses
rank 1 = MOST deprived. A negative correlation between imd_avg_rank and
pressure means more-deprived areas have HIGHER pressure.
"""
import os
import shutil

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PROJECT_ROOT, "nhs_warehouse.db")
BUILD_DB = f"/tmp/nhs_wh_inequality_build_{os.getpid()}.db"

SPECIALIST_CENTRES = {"RBQ", "RBS", "REN", "REP", "RET"}
N_BOOTSTRAP = 5000
RNG_SEED = 42


def bootstrap_spearman(x: np.ndarray, y: np.ndarray, rng) -> dict:
    n = len(x)
    rho0, p0 = spearmanr(x, y)
    boot_rhos = np.empty(N_BOOTSTRAP)
    for b in range(N_BOOTSTRAP):
        idx = rng.integers(0, n, size=n)
        if len(set(idx)) < 3:  # degenerate resample, skip
            boot_rhos[b] = np.nan
            continue
        r, _ = spearmanr(x[idx], y[idx])
        boot_rhos[b] = r
    boot_rhos = boot_rhos[~np.isnan(boot_rhos)]
    return {
        "n": n, "rho": rho0, "p_value": p0,
        "boot_ci_low_p5": np.percentile(boot_rhos, 5),
        "boot_ci_high_p95": np.percentile(boot_rhos, 95),
        "boot_mean": boot_rhos.mean(),
    }


def main():
    print("== Copying current warehouse into /tmp ==", flush=True)
    if os.path.exists(BUILD_DB):
        os.remove(BUILD_DB)
    shutil.copy(PROJECT_DB, BUILD_DB)
    con = duckdb.connect(BUILD_DB)

    # Mean pressure-index outcomes per core provider
    pressure = con.execute("""
        select provider_org_code,
               avg(pressure_index_0_100) as mean_pressure_index,
               avg(rtt_over18_share) as mean_rtt_over18_share,
               avg(rtt_growth) as mean_rtt_growth
        from fact_elective_pressure_index_provider_specialty_month
        group by provider_org_code
    """).fetchdf()

    # Latest-year workforce staffing intensity (contextual overlay)
    workforce_latest = con.execute("""
        with ranked as (
            select *, row_number() over (partition by provider_org_code order by fiscal_year desc) as rn
            from fact_workforce_provider_year
        )
        select provider_org_code, fiscal_year, consultants_per_1000_fte, total_fte
        from ranked where rn = 1
    """).fetchdf()

    la_map = con.execute("""
        select provider_org_code, la_code, la_name, catchment_caveat
        from dim_provider_local_authority
    """).fetchdf()

    # NOTE: dim_imd2019_local_authority carries TWO rank columns per domain —
    # imd_avg_rank is the raw population-weighted average of LSOA-level
    # national ranks (out of 32,844 LSOAs, so values run into the tens of
    # thousands and are NOT directly interpretable as "this LA's rank").
    # imd_rank_of_avg_rank is the LA's own rank out of 151 upper-tier LAs
    # (1 = most deprived) — THAT is the comparable, interpretable figure and
    # the one used for every correlation below. Using the wrong column here
    # was the first version of this script's own bug, caught by cross-
    # checking against this log's already-established Knowsley=3/Liverpool=4
    # /Cheshire East=131 corroboration before trusting any new number.
    imd = con.execute("""
        select la_code,
               imd_rank_of_avg_rank as imd_avg_rank,
               imd_avg_score,
               health_rank_of_avg_rank as health_avg_rank,
               health_avg_score
        from dim_imd2019_local_authority
    """).fetchdf()

    merged = (
        pressure.merge(la_map, on="provider_org_code", how="left")
        .merge(imd, on="la_code", how="left")
        .merge(workforce_latest, on="provider_org_code", how="left")
    )
    merged["is_specialist_centre"] = merged["provider_org_code"].isin(SPECIALIST_CENTRES)
    merged = merged.sort_values("imd_avg_rank")

    print("== Full provider x deprivation table ==")
    print(merged[["provider_org_code", "la_name", "imd_avg_rank", "health_avg_rank",
                   "mean_pressure_index", "mean_rtt_over18_share",
                   "consultants_per_1000_fte", "is_specialist_centre"]].to_string(index=False))

    rng = np.random.default_rng(RNG_SEED)
    subsets = {
        "all_12_core_providers": merged,
        "excl_5_specialist_centres_n7": merged[~merged["is_specialist_centre"]],
    }
    print("\n== Correlations: deprivation rank vs. outcome (Spearman, MC bootstrap CI) ==")
    results = []
    for subset_name, df in subsets.items():
        df = df.dropna(subset=["imd_avg_rank"])
        print(f"\n--- {subset_name} (n={len(df)}) ---")
        for outcome, ivar in [("mean_pressure_index", "imd_avg_rank"),
                               ("mean_pressure_index", "health_avg_rank"),
                               ("mean_rtt_over18_share", "imd_avg_rank"),
                               ("consultants_per_1000_fte", "imd_avg_rank")]:
            sub = df.dropna(subset=[outcome, ivar])
            if len(sub) < 4:
                print(f"  {ivar} vs {outcome}: too few rows ({len(sub)}), skipped")
                continue
            r = bootstrap_spearman(sub[ivar].values, sub[outcome].values, rng)
            print(f"  {ivar} vs {outcome}: rho={r['rho']:+.3f} (p={r['p_value']:.3f}), "
                  f"90% bootstrap CI=[{r['boot_ci_low_p5']:+.3f}, {r['boot_ci_high_p95']:+.3f}]")
            results.append({"subset": subset_name, "independent_var": ivar, "outcome": outcome, **r})

    results_df = pd.DataFrame(results)

    print("\n== Interpretation ==")
    print("Remember: imd_avg_rank / health_avg_rank use rank 1 = MOST deprived. A NEGATIVE")
    print("rho for imd_avg_rank vs mean_pressure_index means more-deprived areas see MORE pressure.")
    key_row = results_df[(results_df.subset == "all_12_core_providers") &
                          (results_df.independent_var == "imd_avg_rank") &
                          (results_df.outcome == "mean_pressure_index")]
    if len(key_row):
        r = key_row.iloc[0]
        direction = "more-deprived areas see MORE pressure" if r.rho < 0 else "more-deprived areas see LESS pressure"
        print(f"Headline (all 12 providers): rho={r.rho:+.3f}, 90% CI=[{r.boot_ci_low_p5:+.3f}, "
              f"{r.boot_ci_high_p95:+.3f}] -> {direction}, but the CI is wide given n=12 — "
              f"read as suggestive, not conclusive.")

    # ---- Write tables ----
    con.execute("DROP TABLE IF EXISTS ref_inequality_provider_deprivation")
    con.register("merged_df", merged)
    con.execute("""
        CREATE TABLE ref_inequality_provider_deprivation AS
        SELECT provider_org_code, la_code, la_name, catchment_caveat, is_specialist_centre,
               imd_avg_rank, imd_avg_score, health_avg_rank, health_avg_score,
               mean_pressure_index, mean_rtt_over18_share, mean_rtt_growth,
               consultants_per_1000_fte, total_fte, fiscal_year
        FROM merged_df
    """)

    con.execute("DROP TABLE IF EXISTS ref_inequality_correlations")
    con.register("results_df", results_df)
    con.execute("CREATE TABLE ref_inequality_correlations AS SELECT * FROM results_df")

    con.close()

    print("\n== Copying build DB back to project mount ==")
    tmp_final = f"/tmp/nhs_wh_inequality_final_{os.getpid()}.db"
    shutil.copy(BUILD_DB, tmp_final)
    shutil.copy(tmp_final, PROJECT_DB)
    verify = duckdb.connect(PROJECT_DB, read_only=True)
    print(verify.execute("select count(*) from ref_inequality_provider_deprivation").fetchone())
    verify.close()
    print("Done.")


if __name__ == "__main__":
    main()
