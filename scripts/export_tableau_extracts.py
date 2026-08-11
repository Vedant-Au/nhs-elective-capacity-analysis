"""
Tableau story phase — data extraction. Claude can't author real .twb/.twbx
files (no Tableau Hyper API available in this sandbox, no network path to
install it, and no way to validate hand-written Tableau XML against real
Tableau) so the division of labor here mirrors the Excel Solver phase:
Claude prepares clean, denormalized, Tableau-ready CSV extracts + a design
spec; Vedant builds the actual workbook in Tableau Desktop.

Five-story-point narrative, matching this project's own analytical arc:
  1. The Backlog — RTT waiting list trend, pre/post-COVID
  2. Where's the pressure worst? — pressure index by provider
  3. What's driving it? — six signals, deprivation cross-cut, clusters
  4. Where's this heading? — 18-month forecast with MC bands
  5. What can be done? — capacity-optimizer (Excel Solver) results

Extracts written to tableau/ (already an empty placeholder in this repo,
per the original charter's folder scaffold).
"""
import duckdb
import pandas as pd
import json
import re

DB = "/sessions/peaceful-nice-bohr/mnt/NHS_Project/nhs_warehouse.db"
OUT = "/sessions/peaceful-nice-bohr/mnt/NHS_Project/tableau"
con = duckdb.connect(DB, read_only=True)

MONTHS = {
    'JANUARY': 1, 'FEBRUARY': 2, 'MARCH': 3, 'APRIL': 4, 'MAY': 5, 'JUNE': 6,
    'JULY': 7, 'AUGUST': 8, 'SEPTEMBER': 9, 'OCTOBER': 10, 'NOVEMBER': 11, 'DECEMBER': 12
}
def parse_period(p):
    m = re.match(r'RTT-(\w+)-(\d{4})', p, re.IGNORECASE)
    return pd.Timestamp(year=int(m.group(2)), month=MONTHS[m.group(1).upper()], day=1)

# ---------------------------------------------------------------------------
# 0. Master provider dimension (name, type, deprivation) — the lookup table
#    every other extract joins back to in Tableau via relationships.
# ---------------------------------------------------------------------------
dim = con.execute("""
    SELECT p.provider_org_code, p.provider_org_name, p.provider_type, p.in_core_analysis,
           pl.la_name, pl.catchment_caveat, imd.imd_rank_of_avg_rank AS la_imd_rank,
           imd.health_rank_of_avg_rank AS la_health_imd_rank
    FROM dim_provider p
    LEFT JOIN dim_provider_local_authority pl USING (provider_org_code)
    LEFT JOIN dim_imd2019_local_authority imd ON pl.la_code = imd.la_code
    WHERE p.in_core_analysis = true
""").fetchdf()
median_rank = dim['la_imd_rank'].median()
dim['higher_deprivation'] = dim['la_imd_rank'] <= median_rank
dim.to_csv(f"{OUT}/dim_provider.csv", index=False)
print("dim_provider.csv:", len(dim), "rows")

# ---------------------------------------------------------------------------
# 1. Story point 1 — RTT waiting list trend, provider-month (all 84 months)
# ---------------------------------------------------------------------------
rtt = con.execute("""
    SELECT provider_org_code, period,
           sum(waiting_list_size) AS waiting_list_size,
           sum(waiting_list_over_18wk) AS over_18wk,
           sum(waiting_list_over_52wk) AS over_52wk,
           sum(completed_pathways_total) AS completed_pathways
    FROM fact_rtt_provider_specialty_month
    WHERE provider_org_code IN (SELECT provider_org_code FROM dim_provider WHERE in_core_analysis = true)
    GROUP BY 1, 2
""").fetchdf()
rtt['period_month'] = rtt['period'].apply(parse_period)
rtt['over18_share'] = rtt['over_18wk'] / rtt['waiting_list_size']
rtt['over52_share'] = rtt['over_52wk'] / rtt['waiting_list_size']
rtt = rtt.drop(columns=['period']).sort_values(['provider_org_code', 'period_month'])
rtt.to_csv(f"{OUT}/rtt_trend_provider_month.csv", index=False)
print("rtt_trend_provider_month.csv:", len(rtt), "rows")

# ---------------------------------------------------------------------------
# 2/3. Story points 2 & 3 — pressure index (both grains) + clusters + inequality
# ---------------------------------------------------------------------------
pi_specialty = con.execute("""
    SELECT * FROM fact_elective_pressure_index_provider_specialty_month
    WHERE provider_org_code IN (SELECT provider_org_code FROM dim_provider WHERE in_core_analysis = true)
""").fetchdf()
pi_specialty.to_csv(f"{OUT}/pressure_index_provider_specialty_month.csv", index=False)
print("pressure_index_provider_specialty_month.csv:", len(pi_specialty), "rows")

pi_provider = pi_specialty.groupby(['provider_org_code', 'period_month']).agg(
    pressure_index_0_100=('pressure_index_0_100', 'mean'),
    rtt_growth=('rtt_growth', 'mean'), rtt_over18_share=('rtt_over18_share', 'mean'),
    rtt_over52_share=('rtt_over52_share', 'mean'), dm01_breach=('dm01_breach', 'mean'),
    ae_pressure=('ae_pressure', 'mean'), kh03_occupancy=('kh03_occupancy', 'mean'),
).reset_index()
pi_provider.to_csv(f"{OUT}/pressure_index_provider_month.csv", index=False)
print("pressure_index_provider_month.csv:", len(pi_provider), "rows")

clusters = con.execute("""
    SELECT c.*, ct.mean_pressure_index AS cluster_mean_pressure, ct.n_series AS cluster_size
    FROM ref_pressure_profile_clusters c
    LEFT JOIN ref_pressure_cluster_centroids ct USING (cluster)
    WHERE c.provider_org_code IN (SELECT provider_org_code FROM dim_provider WHERE in_core_analysis = true)
""").fetchdf()
clusters.to_csv(f"{OUT}/pressure_clusters.csv", index=False)
print("pressure_clusters.csv:", len(clusters), "rows")

inequality_dep = con.execute("SELECT * FROM ref_inequality_provider_deprivation").fetchdf()
inequality_dep.to_csv(f"{OUT}/inequality_deprivation.csv", index=False)
print("inequality_deprivation.csv:", len(inequality_dep), "rows")

inequality_corr = con.execute("SELECT * FROM ref_inequality_correlations").fetchdf()
inequality_corr.to_csv(f"{OUT}/inequality_correlations.csv", index=False)
print("inequality_correlations.csv:", len(inequality_corr), "rows")

# ---------------------------------------------------------------------------
# 4. Story point 4 — forecast with MC bands + model-selection audit trail
# ---------------------------------------------------------------------------
fc = con.execute("""
    SELECT * FROM fact_rtt_waitinglist_forecast_provider_month
    WHERE provider_org_code IN (SELECT provider_org_code FROM dim_provider WHERE in_core_analysis = true)
""").fetchdf()
fc.to_csv(f"{OUT}/forecast_provider_month.csv", index=False)
print("forecast_provider_month.csv:", len(fc), "rows")

model_sel = con.execute("SELECT * FROM ref_forecast_model_selection").fetchdf()
model_sel.to_csv(f"{OUT}/forecast_model_selection.csv", index=False)
print("forecast_model_selection.csv:", len(model_sel), "rows")

# ---------------------------------------------------------------------------
# 5. Story point 5 — capacity optimizer (Excel Solver) results
# ---------------------------------------------------------------------------
with open('/tmp/solver_model_solution.json') as f:
    solver = json.load(f)
solver_results = pd.DataFrame(solver['reference_solution'])
solver_results.to_csv(f"{OUT}/solver_results_provider.csv", index=False)
print("solver_results_provider.csv:", len(solver_results), "rows")

with open('/tmp/budget_sensitivity.json') as f:
    sens = json.load(f)
sens_df = pd.DataFrame(sens)
sens_df.to_csv(f"{OUT}/solver_budget_sensitivity.csv", index=False)
print("solver_budget_sensitivity.csv:", len(sens_df), "rows")

print("\nAll extracts written to", OUT)
