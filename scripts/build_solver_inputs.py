"""
NHS_Project — Phase 3 Excel Solver capacity-optimizer.
Step 1: extract and derive all model inputs from nhs_warehouse.db, solve a
reference LP in Python (scipy.optimize.linprog) to validate against, then
hand off to a second script that builds the actual Excel workbook.

Design locked in with Vedant, 2026-08-07 continuation session (see
docs/STATUS.md):
  - Objective: minimize total forecasted RTT over-52-week breaches across
    12 core trusts over the 18-month forecast horizon (2026-04..2027-09).
  - Levers: (1) extra in-house elective capacity, (2) independent-sector
    outsourcing, (3) diagnostic capacity investment — all three expressed
    in a common unit (extra RTT-equivalent completed pathways/month) so
    they're directly comparable and summable in the LP.
  - Constraints: budget envelope, workforce/bed capacity ceilings,
    per-provider outsourcing cap, bounded equity tolerance.

Grain decision (new, made this session, documented rather than silently
assumed): decision variables are at PROVIDER level, not provider-specialty.
Two of the three constraint-defining data sources (Workforce, KH03 beds)
only exist at provider grain in this warehouse — there is no specialty-
level FTE or bed data to constrain against — so a genuinely
specialty-disaggregated model isn't supportable by the data actually
warehoused, independent of Excel Solver's own ~200-variable practical
limit on the free Solver engine (which a 12 x ~20-specialty x 3-lever
model would blow through anyway, ~700+ variables). 12 providers x 3
levers = 36 decision variables, comfortably within Excel's native Solver.
"""
import duckdb
import pandas as pd
import numpy as np
import re
import json

DB = "/sessions/peaceful-nice-bohr/mnt/NHS_Project/nhs_warehouse.db"
MONTHS = {
    'JANUARY': 1, 'FEBRUARY': 2, 'MARCH': 3, 'APRIL': 4, 'MAY': 5, 'JUNE': 6,
    'JULY': 7, 'AUGUST': 8, 'SEPTEMBER': 9, 'OCTOBER': 10, 'NOVEMBER': 11, 'DECEMBER': 12
}

def parse_period(p):
    m = re.match(r'RTT-(\w+)-(\d{4})', p, re.IGNORECASE)
    return pd.Timestamp(year=int(m.group(2)), month=MONTHS[m.group(1).upper()], day=1)

con = duckdb.connect(DB, read_only=True)

# ---------------------------------------------------------------------------
# 1. Core provider list + deprivation grouping
# ---------------------------------------------------------------------------
providers = con.execute("""
    SELECT p.provider_org_code, p.provider_org_name, p.provider_type
    FROM dim_provider p
    WHERE p.in_core_analysis = true
    ORDER BY p.provider_org_code
""").fetchdf()

depriv = con.execute("""
    SELECT pl.provider_org_code, pl.la_code, pl.la_name, pl.catchment_caveat,
           imd.imd_rank_of_avg_rank AS la_imd_rank
    FROM dim_provider_local_authority pl
    JOIN dim_imd2019_local_authority imd USING (la_code)
""").fetchdf()

providers = providers.merge(depriv, on='provider_org_code', how='left')
median_rank = providers['la_imd_rank'].median()
providers['higher_deprivation'] = providers['la_imd_rank'] <= median_rank
print("Providers:", len(providers), "| median LA IMD rank:", median_rank)
print(providers[['provider_org_code', 'la_name', 'la_imd_rank', 'higher_deprivation']].to_string())

# ---------------------------------------------------------------------------
# 2. Baseline (do-nothing) over-52-week breach forecast, provider x month
#    Method: forecasted total waiting list (provider-month, already built)
#    x trailing 6-month actual over-52 share (provider-level, summed across
#    specialties). This is a proxy, not a direct forecast of breach counts
#    (the forecast table was scoped to waiting_list_size only, per the
#    2026-08-08 forecasting session) — flagged explicitly, not silent.
# ---------------------------------------------------------------------------
rtt_actual = con.execute("""
    SELECT provider_org_code, period, waiting_list_size, waiting_list_over_52wk,
           completed_pathways_total
    FROM fact_rtt_provider_specialty_month
    WHERE provider_org_code IN (SELECT provider_org_code FROM dim_provider WHERE in_core_analysis = true)
""").fetchdf()
rtt_actual['period_month'] = rtt_actual['period'].apply(parse_period)

# provider-month totals (sum across specialties)
prov_month = rtt_actual.groupby(['provider_org_code', 'period_month']).agg(
    waiting_list_size=('waiting_list_size', 'sum'),
    over_52wk=('waiting_list_over_52wk', 'sum'),
    completed_pathways=('completed_pathways_total', 'sum'),
).reset_index()

latest_actual_month = prov_month['period_month'].max()
print("\nLatest actual RTT month:", latest_actual_month.date())
trailing_start = latest_actual_month - pd.DateOffset(months=5)  # last 6 months inclusive
trailing = prov_month[prov_month['period_month'] >= trailing_start]

trailing_agg = trailing.groupby('provider_org_code').agg(
    trailing_wl=('waiting_list_size', 'mean'),
    trailing_over52=('over_52wk', 'mean'),
    trailing_completions=('completed_pathways', 'mean'),
).reset_index()
trailing_agg['over52_share'] = trailing_agg['trailing_over52'] / trailing_agg['trailing_wl']
print("\nTrailing 6-month (", trailing_start.date(), "to", latest_actual_month.date(), ") provider stats:")
print(trailing_agg.to_string())

# ---------------------------------------------------------------------------
# 3. Forecast horizon: 18 months, 2026-04 through 2027-09
# ---------------------------------------------------------------------------
fc = con.execute("""
    SELECT provider_org_code, period_month, waiting_list_size AS wl_forecast, mc_p50
    FROM fact_rtt_waitinglist_forecast_provider_month
    WHERE provider_org_code IN (SELECT provider_org_code FROM dim_provider WHERE in_core_analysis = true)
      AND is_forecast = true
""").fetchdf()
fc['period_month'] = pd.to_datetime(fc['period_month'])
horizon_start, horizon_end = fc['period_month'].min(), fc['period_month'].max()
n_months = fc['period_month'].nunique()
print(f"\nForecast horizon: {horizon_start.date()} to {horizon_end.date()} ({n_months} months)")

fc = fc.merge(trailing_agg[['provider_org_code', 'over52_share']], on='provider_org_code', how='left')
fc['baseline_over52_forecast'] = fc['wl_forecast'] * fc['over52_share']

baseline_by_provider = fc.groupby('provider_org_code').agg(
    baseline_over52_total=('baseline_over52_forecast', 'sum'),
    avg_monthly_wl_forecast=('wl_forecast', 'mean'),
).reset_index()
print("\nBaseline (do-nothing) 18-month cumulative over-52wk breach forecast, by provider:")
print(baseline_by_provider.to_string())

# ---------------------------------------------------------------------------
# 4. Capacity ceilings: workforce (consultant FTE) + KH03 (G&A bed headroom)
# ---------------------------------------------------------------------------
workforce = con.execute("""
    SELECT provider_org_code, fiscal_year, consultant_fte
    FROM fact_workforce_provider_year
    WHERE provider_org_code IN (SELECT provider_org_code FROM dim_provider WHERE in_core_analysis = true)
""").fetchdf()
latest_fy = sorted(workforce['fiscal_year'].unique())[-1]
workforce_latest = workforce[workforce['fiscal_year'] == latest_fy][['provider_org_code', 'consultant_fte']]
print(f"\nLatest workforce fiscal year: {latest_fy}")

kh03 = con.execute("""
    SELECT provider_org_code, quarter_end_date, available_ga, occupied_ga
    FROM fact_kh03_provider_quarter
    WHERE provider_org_code IN (SELECT provider_org_code FROM dim_provider WHERE in_core_analysis = true)
""").fetchdf()
kh03['quarter_end_date'] = pd.to_datetime(kh03['quarter_end_date'])
latest_q = kh03['quarter_end_date'].max()
kh03_latest = kh03[kh03['quarter_end_date'] == latest_q].copy()
kh03_latest['bed_headroom_pct'] = 1 - (kh03_latest['occupied_ga'] / kh03_latest['available_ga'])
print(f"Latest KH03 quarter: {latest_q.date()}")
print(kh03_latest[['provider_org_code', 'available_ga', 'occupied_ga', 'bed_headroom_pct']].to_string())

# ---------------------------------------------------------------------------
# 5. Independent-sector outsourcing pool (real current ICB-wide IS activity)
# ---------------------------------------------------------------------------
is_activity = con.execute("""
    SELECT period, sum(completed_pathways_total) AS is_completions
    FROM fact_rtt_provider_specialty_month
    WHERE provider_org_code IN (SELECT provider_org_code FROM dim_provider WHERE provider_type = 'independent_sector')
    GROUP BY period
""").fetchdf()
is_activity['period_month'] = is_activity['period'].apply(parse_period)
is_trailing = is_activity[is_activity['period_month'] >= trailing_start]['is_completions'].mean()
print(f"\nCurrent ICB-wide independent-sector monthly completions (trailing 6mo avg): {is_trailing:.0f}")

# ---------------------------------------------------------------------------
# 5b. Real admitted vs non-admitted completion mix for the 12 core trusts
#     (trailing 6mo) — needed to weight the National Cost Collection's
#     Elective Inpatient/Daycase/Outpatient Procedure unit costs into a
#     single blended tariff that reflects THIS ICB's actual completion mix,
#     not a national or arbitrary assumption. RTT's own Part_1A/1B split
#     doesn't distinguish daycase from inpatient within "admitted" — that
#     finer split is bridged using NCC's own national Elective
#     Inpatient/Daycase activity mix in solve_model.py, flagged there.
# ---------------------------------------------------------------------------
mix_df = con.execute("""
    SELECT provider_org_code, period, completed_admitted, completed_nonadmitted
    FROM fact_rtt_provider_specialty_month
    WHERE provider_org_code IN (SELECT provider_org_code FROM dim_provider WHERE in_core_analysis = true)
""").fetchdf()
mix_df['period_month'] = mix_df['period'].apply(parse_period)
mix_trailing = mix_df[mix_df['period_month'] >= trailing_start]
icb_admitted = float(mix_trailing['completed_admitted'].sum())
icb_nonadmitted = float(mix_trailing['completed_nonadmitted'].sum())
icb_admitted_share = icb_admitted / (icb_admitted + icb_nonadmitted)
print(f"\nC&M 12-trust trailing 6mo completion mix: admitted={icb_admitted:.0f} "
      f"({icb_admitted_share:.1%}), non-admitted={icb_nonadmitted:.0f} ({1-icb_admitted_share:.1%})")

# ---------------------------------------------------------------------------
# 5c. Real DM01 diagnostic test-mix (all 15 test types, whole warehouse
#     window — composition is a structural property of the service mix,
#     not something that needs a trailing-6mo window like activity volumes
#     do) for the 12 core trusts, split into the 4 categories NCC currencies
#     can actually be matched against: imaging, audiology (its own NCC
#     currency), other physiological measurement, and endoscopy. Needed to
#     weight the diagnostic-capacity lever's cost properly instead of
#     assuming imaging alone represents all of DM01.
# ---------------------------------------------------------------------------
dm01_mix = con.execute("""
    SELECT d.category, d.diagnostic_test_name, sum(f.total_activity) AS activity
    FROM fact_dm01_provider_test_month f
    JOIN dim_diagnostic_test d USING (diagnostic_test_code)
    WHERE f.provider_org_code IN (SELECT provider_org_code FROM dim_provider WHERE in_core_analysis = true)
    GROUP BY 1, 2
""").fetchdf()
imaging_activity = dm01_mix.loc[dm01_mix.category == 'imaging', 'activity'].sum()
audiology_activity = dm01_mix.loc[dm01_mix.diagnostic_test_name.str.contains('Audiology'), 'activity'].sum()
other_physio_activity = dm01_mix.loc[dm01_mix.category == 'physiological_measurement', 'activity'].sum() - audiology_activity
endoscopy_activity = dm01_mix.loc[dm01_mix.category == 'endoscopy', 'activity'].sum()
dm01_total = imaging_activity + audiology_activity + other_physio_activity + endoscopy_activity
print(f"\nDM01 test-mix (12 core trusts, full window): imaging {imaging_activity/dm01_total:.1%}, "
      f"audiology {audiology_activity/dm01_total:.1%}, other physiological measurement "
      f"{other_physio_activity/dm01_total:.1%}, endoscopy {endoscopy_activity/dm01_total:.1%}")

# ---------------------------------------------------------------------------
# Save everything to a JSON bundle for the workbook-building step
# ---------------------------------------------------------------------------
model_inputs = providers.merge(baseline_by_provider, on='provider_org_code') \
                         .merge(trailing_agg, on='provider_org_code') \
                         .merge(workforce_latest, on='provider_org_code', how='left') \
                         .merge(kh03_latest[['provider_org_code', 'available_ga', 'occupied_ga', 'bed_headroom_pct']],
                                on='provider_org_code', how='left')

out = {
    "horizon_start": str(horizon_start.date()),
    "horizon_end": str(horizon_end.date()),
    "n_months": int(n_months),
    "latest_actual_month": str(latest_actual_month.date()),
    "median_la_imd_rank": float(median_rank),
    "is_ceiling_trailing_monthly": float(is_trailing),
    "icb_admitted_share": float(icb_admitted_share),
    "dm01_imaging_share": float(imaging_activity / dm01_total),
    "dm01_audiology_share": float(audiology_activity / dm01_total),
    "dm01_other_physio_share": float(other_physio_activity / dm01_total),
    "dm01_endoscopy_share": float(endoscopy_activity / dm01_total),
    "providers": json.loads(model_inputs.to_json(orient='records')),
}
with open('/tmp/solver_model_inputs.json', 'w') as f:
    json.dump(out, f, indent=2, default=str)
model_inputs.to_csv('/tmp/solver_model_inputs.csv', index=False)
print("\nSaved /tmp/solver_model_inputs.json and .csv")
print("\nFull model_inputs table:")
print(model_inputs.to_string())
