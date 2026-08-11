"""
Step 2: turn /tmp/solver_model_inputs.json into a fully-specified LP (lever
caps, costs, equity constraint), solve it with scipy.optimize.linprog as an
independent reference answer, and save everything needed to build the Excel
workbook (which will reproduce this same LP for Vedant to solve interactively
via Excel's own Solver add-in).

Cost assumptions — UPDATED 2026-08-08 with real NHS England National Cost
Collection (NCC) 2024/25 figures, supplied by Vedant via screenshots of the
National Schedule of NHS costs Power BI dashboard (this sandbox still has
no outbound internet path that can pull the dashboard itself — confirmed
again this session, web_fetch returns the underlying .zip as unusable
opaque binary). Replaces the flat £1,500/£400 planning-assumption pass
from the prior version of this script with a properly weighted figure:

  - SOURCED (NCC 2024/25, National Schedule of NHS costs, Summary: HRG
    tab, Total row, England-wide, 206 providers): Elective Inpatient
    £6,624/completion (1,255,967 activities); Daycase £1,078/completion
    (7,680,341 activities); Outpatient Procedures £233/completion
    (19,224,707 activities); Diagnostic Imaging £140/test (8,573,583
    tests). These are real reported average unit costs, not estimates.
  - SOURCED (this warehouse): the 12 core C&M trusts' own trailing
    6-month (Oct-2025 to Mar-2026) RTT completion mix — 14.7% admitted,
    85.3% non-admitted (from fact_rtt_provider_specialty_month's own
    completed_admitted / completed_nonadmitted columns, not assumed).
  - BLENDED (real inputs, one flagged bridging assumption): RTT's own
    Part_1A/1B split doesn't distinguish daycase from inpatient within
    "admitted" pathways — NHS doesn't publish that split by RTT clock
    type. Bridged using the NCC's own NATIONAL Elective Inpatient/Daycase
    ACTIVITY mix (day case dominates ~86% of admitted NCC activity
    nationally) to blend the two into one admitted-completion unit cost,
    then combined with the ICB's own real admitted/non-admitted split and
    the (also real) Outpatient Procedures cost as the non-admitted proxy.
    This is the one place a national ratio stands in for something this
    ICB's own data can't provide — flagged here and in the workbook.
  - CORRECTED 2026-08-08 (was wrong, now fixed): the 75%/100% marginal-
    rate split was sourced from a 2022 HFMA article describing the
    2022/23 scheme and flagged as unverified against the current scheme
    ever since. Verified now against the actual 2025/26 NHS Payment
    Scheme (NHS England, "NHS provider payment mechanisms" and the
    2025/26 NHSPS main page, corroborated by HFMA) — that marginal-rate
    mechanism was REMOVED for 2025/26. Both NHS and independent-sector
    providers are now paid 100% of the NHSPS unit price for elective
    activity, with no floors, ceilings, or marginal rates. c1 and c2 are
    therefore equal under current policy, not 75%/100% as the earlier
    version of this model assumed — a real, substantive correction, not
    a rounding tweak, and it removes the in-house-cheaper-than-outsourcing
    cost preference that was baked into every result up to this point.
  - ESTIMATED (weakest-sourced figure remaining): diagnostic-unlocked
    pathway cost = 1.75 x the real £140 Diagnostic Imaging unit cost =
    £245. The £140 base is now real; the "1.75 diagnostic tests per RTT
    pathway unlocked" multiplier is still an analyst assumption (a
    plausible clinical estimate — most pathways need at least one imaging
    and often one pathology-type test to reach a treatment decision — but
    not itself a published NHS ratio).
"""
import json
import pandas as pd
import numpy as np
from scipy.optimize import linprog

with open('/tmp/solver_model_inputs.json') as f:
    data = json.load(f)

df = pd.DataFrame(data['providers'])
n_months = data['n_months']
providers = df['provider_org_code'].tolist()
P = len(providers)

# ---------------------------------------------------------------------------
# Lever caps (monthly, applied uniformly across the 18-month horizon)
# ---------------------------------------------------------------------------
BED_HEADROOM_FLOOR = 0.10  # providers at/above this headroom face no extra scaling
df['bed_scale'] = (df['bed_headroom_pct'] / BED_HEADROOM_FLOOR).clip(upper=1.0)

INHOUSE_GROWTH_RATE = 0.15   # anchored on ERF's own national "10% activity increase" target, +buffer
DIAG_GROWTH_RATE = 0.10      # more conservative — indirect lever

df['x1_cap'] = df['trailing_completions'] * INHOUSE_GROWTH_RATE * df['bed_scale']
df['x3_cap'] = df['trailing_completions'] * DIAG_GROWTH_RATE

IS_GROWTH_RATE = 0.50  # independent sector assumed more scalable short-term than NHS in-house
is_pool_monthly = data['is_ceiling_trailing_monthly'] * IS_GROWTH_RATE
backlog_share = df['baseline_over52_total'] / df['baseline_over52_total'].sum()
df['x2_cap'] = backlog_share * is_pool_monthly

# ---------------------------------------------------------------------------
# Costs (£ per RTT-equivalent completed pathway per month)
# NCC 2024/25 National Schedule of NHS costs, Summary: HRG tab, Total row
# (screenshots supplied by Vedant, 2026-08-08) — see module docstring.
# ---------------------------------------------------------------------------
NCC_ELECTIVE_INPATIENT_COST = 6624.0
NCC_ELECTIVE_INPATIENT_ACTIVITY = 1_255_967
NCC_DAYCASE_COST = 1078.0
NCC_DAYCASE_ACTIVITY = 7_680_341
NCC_OUTPATIENT_PROCEDURE_COST = 233.0
NCC_DIAGNOSTIC_IMAGING_COST = 140.0
NCC_DIRECTLY_ACCESSED_AUDIOLOGY_COST = 107.0
NCC_DIRECTLY_ACCESSED_DIAGNOSTIC_SERVICES_COST = 90.0
# NCC also supplied "Directly Accessed Pathology Services" (£2.41/test blended,
# 493.6M tests) — real data, but DELIBERATELY NOT USED: DM01 (the diagnostic
# dataset this project tracks) has no pathology category at all — its 15 test
# types split into imaging, endoscopy, and physiological measurement only
# (dim_diagnostic_test.category). Blending in a currency DM01 doesn't cover
# would misrepresent what this lever actually funds, not improve it.

# Blend Elective Inpatient + Daycase into one "admitted" unit cost, weighted
# by NCC's own NATIONAL activity mix (RTT itself doesn't split admitted
# completions into daycase vs inpatient — flagged in the module docstring).
admitted_blended_cost = (
    NCC_ELECTIVE_INPATIENT_COST * NCC_ELECTIVE_INPATIENT_ACTIVITY
    + NCC_DAYCASE_COST * NCC_DAYCASE_ACTIVITY
) / (NCC_ELECTIVE_INPATIENT_ACTIVITY + NCC_DAYCASE_ACTIVITY)

icb_admitted_share = data['icb_admitted_share']
UNIT_TARIFF = icb_admitted_share * admitted_blended_cost + \
              (1 - icb_admitted_share) * NCC_OUTPATIENT_PROCEDURE_COST
print(f"\nAdmitted-completion blended cost (NCC national activity mix): £{admitted_blended_cost:,.2f}")
print(f"ICB admitted share (real, this warehouse): {icb_admitted_share:.1%}")
print(f"Blended unit_tariff (real inputs, one bridging assumption): £{UNIT_TARIFF:,.2f}")

C1 = 1.00 * UNIT_TARIFF   # in-house — 2025/26 NHSPS: 100% of tariff, no marginal rate (verified)
C2 = 1.00 * UNIT_TARIFF   # independent sector — same 100% rate, no policy differential from in-house

# Weighted diagnostic unit cost — real DM01 test-mix shares (this warehouse,
# 12 core trusts, full window) applied to the matching NCC currency for each
# category. Replaces an imaging-only proxy with one that reflects what DM01
# actually measures (imaging dominates the mix at ~79%, so this moves the
# number only slightly vs. imaging alone — a genuine check, not wasted effort).
diag_weighted_cost = (
    data['dm01_imaging_share'] * NCC_DIAGNOSTIC_IMAGING_COST
    + data['dm01_audiology_share'] * NCC_DIRECTLY_ACCESSED_AUDIOLOGY_COST
    + data['dm01_other_physio_share'] * NCC_DIRECTLY_ACCESSED_DIAGNOSTIC_SERVICES_COST
    + data['dm01_endoscopy_share'] * NCC_OUTPATIENT_PROCEDURE_COST  # endoscopy has no
    # dedicated NCC "diagnostic test" currency of its own — most NHS endoscopies are
    # costed as day-case/outpatient procedures, so Outpatient Procedures is the closest
    # real match available rather than reusing Diagnostic Imaging for something it isn't.
)
print(f"\nDiagnostic weighted unit cost (real DM01 mix x matched NCC currencies): £{diag_weighted_cost:,.2f}"
      f" (vs. imaging-only £{NCC_DIAGNOSTIC_IMAGING_COST:,.2f})")

DIAG_TESTS_PER_PATHWAY = 1.75   # analyst estimate — the one unsourced multiplier left
C3 = DIAG_TESTS_PER_PATHWAY * diag_weighted_cost   # diagnostic-unlocked pathway
print(f"c1={C1:,.2f} | c2={C2:,.2f} | c3={C3:,.2f}")

# ---------------------------------------------------------------------------
# Budget envelope — NO public ICB-level elective recovery budget figure was
# available to source, so this is a SCENARIO INPUT the workbook exposes as
# an adjustable cell, not an asserted "real" number. Default set so the
# reference solve below is a genuinely constrained (non-trivial) scenario.
# ---------------------------------------------------------------------------
DEFAULT_BUDGET_TOTAL = 15_000_000.0  # over the full 18-month horizon, illustrative

# ---------------------------------------------------------------------------
# Equity constraint: bounded tolerance, not a hard floor (Vedant's steer).
# higher_deprivation providers' baseline share of total breaches...
# ---------------------------------------------------------------------------
higher_mask = df['higher_deprivation'].values
baseline = df['baseline_over52_total'].values
higher_baseline_share = baseline[higher_mask].sum() / baseline.sum()
EQUITY_TOLERANCE_PP = 0.15  # 15 percentage points
print(f"Higher-deprivation providers' baseline breach share: {higher_baseline_share:.1%}")
print(f"Equity floor on their share of total REDUCTION achieved: {higher_baseline_share - EQUITY_TOLERANCE_PP:.1%}")

# ---------------------------------------------------------------------------
# Build the LP.
# Variables: x1_p, x2_p, x3_p for p in providers (3P variables), plus
# auxiliary reduction_p variables (P more) to linearize the min().
# minimize: sum(baseline_p - reduction_p) == minimize: -sum(reduction_p)  [baseline is constant]
# s.t.
#   reduction_p <= baseline_p
#   reduction_p <= n_months * (x1_p + x2_p + x3_p)
#   0 <= x1_p <= x1_cap_p ; 0 <= x2_p <= x2_cap_p ; 0 <= x3_p <= x3_cap_p
#   sum_p n_months*(C1*x1_p + C2*x2_p + C3*x3_p) <= budget
#   sum_{p in higher}(reduction_p) >= (higher_baseline_share - tol) * sum_p(reduction_p)
#     -> rearranged to a linear constraint (see below)
# ---------------------------------------------------------------------------
var_names = [f"x1_{p}" for p in providers] + [f"x2_{p}" for p in providers] + \
            [f"x3_{p}" for p in providers] + [f"red_{p}" for p in providers]
n_vars = 4 * P
idx = {name: i for i, name in enumerate(var_names)}

c = np.zeros(n_vars)
for p in providers:
    c[idx[f"red_{p}"]] = -1.0  # maximize total reduction == minimize -reduction

A_ub, b_ub = [], []

# reduction_p <= n_months*(x1_p+x2_p+x3_p)  ->  red_p - n_months*x1_p - n_months*x2_p - n_months*x3_p <= 0
for p in providers:
    row = np.zeros(n_vars)
    row[idx[f"red_{p}"]] = 1.0
    row[idx[f"x1_{p}"]] = -n_months
    row[idx[f"x2_{p}"]] = -n_months
    row[idx[f"x3_{p}"]] = -n_months
    A_ub.append(row); b_ub.append(0.0)

# budget: sum n_months*(C1 x1 + C2 x2 + C3 x3) <= budget
row = np.zeros(n_vars)
for p in providers:
    row[idx[f"x1_{p}"]] = n_months * C1
    row[idx[f"x2_{p}"]] = n_months * C2
    row[idx[f"x3_{p}"]] = n_months * C3
A_ub.append(row); b_ub.append(DEFAULT_BUDGET_TOTAL)

# equity: sum_{higher} red_p >= (share - tol) * sum_{all} red_p
# -> (share-tol)*sum_all red_p - sum_higher red_p <= 0
target_share = higher_baseline_share - EQUITY_TOLERANCE_PP
row = np.zeros(n_vars)
for p in providers:
    coef = target_share - (1.0 if df.loc[df.provider_org_code == p, 'higher_deprivation'].values[0] else 0.0)
    row[idx[f"red_{p}"]] = coef
A_ub.append(row); b_ub.append(0.0)

bounds = []
for name in var_names:
    if name.startswith('x1_'):
        p = name[3:]; cap = df.loc[df.provider_org_code == p, 'x1_cap'].values[0]
        bounds.append((0, cap))
    elif name.startswith('x2_'):
        p = name[3:]; cap = df.loc[df.provider_org_code == p, 'x2_cap'].values[0]
        bounds.append((0, cap))
    elif name.startswith('x3_'):
        p = name[3:]; cap = df.loc[df.provider_org_code == p, 'x3_cap'].values[0]
        bounds.append((0, cap))
    else:
        p = name[4:]; baseline_p = df.loc[df.provider_org_code == p, 'baseline_over52_total'].values[0]
        bounds.append((0, baseline_p))

res = linprog(c, A_ub=np.array(A_ub), b_ub=np.array(b_ub), bounds=bounds, method='highs')
print("\nLP solve status:", res.message, "| success:", res.success)

sol = res.x
result_rows = []
for p in providers:
    x1, x2, x3, red = sol[idx[f"x1_{p}"]], sol[idx[f"x2_{p}"]], sol[idx[f"x3_{p}"]], sol[idx[f"red_{p}"]]
    baseline_p = df.loc[df.provider_org_code == p, 'baseline_over52_total'].values[0]
    result_rows.append({
        'provider_org_code': p,
        'x1_inhouse_monthly': x1, 'x2_outsource_monthly': x2, 'x3_diagnostic_monthly': x3,
        'baseline_over52_18mo': baseline_p, 'reduction_18mo': red,
        'residual_over52_18mo': baseline_p - red,
        'cost_18mo': n_months * (C1 * x1 + C2 * x2 + C3 * x3),
    })
result_df = pd.DataFrame(result_rows)
result_df = result_df.merge(df[['provider_org_code', 'provider_org_name', 'higher_deprivation']], on='provider_org_code')

total_baseline = result_df['baseline_over52_18mo'].sum()
total_reduction = result_df['reduction_18mo'].sum()
total_cost = result_df['cost_18mo'].sum()
print(f"\nTotal baseline over-52wk breaches (18mo, do-nothing): {total_baseline:,.0f}")
print(f"Total reduction achieved: {total_reduction:,.0f} ({total_reduction/total_baseline:.1%})")
print(f"Total cost: £{total_cost:,.0f} (budget £{DEFAULT_BUDGET_TOTAL:,.0f})")
higher_reduction_share = result_df.loc[result_df.higher_deprivation, 'reduction_18mo'].sum() / total_reduction
print(f"Higher-deprivation providers' share of reduction: {higher_reduction_share:.1%} (floor was {target_share:.1%})")

print("\n", result_df.to_string())

# Sanity checks before trusting this
assert res.success, "LP did not solve successfully"
assert (result_df['x1_inhouse_monthly'] >= -1e-6).all()
assert (result_df['x2_outsource_monthly'] >= -1e-6).all()
assert (result_df['x3_diagnostic_monthly'] >= -1e-6).all()
assert (result_df['reduction_18mo'] <= result_df['baseline_over52_18mo'] + 1e-3).all(), "reduction exceeds baseline somewhere"
assert total_cost <= DEFAULT_BUDGET_TOTAL + 1.0, "budget constraint violated"
assert higher_reduction_share >= target_share - 1e-6, "equity constraint violated"
print("\nAll sanity checks passed.")

# Save everything the workbook builder needs
bundle = {
    "meta": {
        "horizon_start": data["horizon_start"], "horizon_end": data["horizon_end"],
        "n_months": n_months, "latest_actual_month": data["latest_actual_month"],
        "median_la_imd_rank": data["median_la_imd_rank"],
        "is_pool_monthly_total": data["is_ceiling_trailing_monthly"],
    },
    "assumptions": {
        "unit_tariff": UNIT_TARIFF, "c1_inhouse": C1, "c2_outsource": C2, "c3_diagnostic": C3,
        "inhouse_growth_rate": INHOUSE_GROWTH_RATE, "diag_growth_rate": DIAG_GROWTH_RATE,
        "is_growth_rate": IS_GROWTH_RATE, "bed_headroom_floor": BED_HEADROOM_FLOOR,
        "default_budget": DEFAULT_BUDGET_TOTAL, "equity_tolerance_pp": EQUITY_TOLERANCE_PP,
        "higher_baseline_share": higher_baseline_share, "equity_floor_share": target_share,
        "ncc_elective_inpatient_cost": NCC_ELECTIVE_INPATIENT_COST,
        "ncc_daycase_cost": NCC_DAYCASE_COST,
        "ncc_outpatient_procedure_cost": NCC_OUTPATIENT_PROCEDURE_COST,
        "ncc_diagnostic_imaging_cost": NCC_DIAGNOSTIC_IMAGING_COST,
        "ncc_audiology_cost": NCC_DIRECTLY_ACCESSED_AUDIOLOGY_COST,
        "ncc_diagnostic_services_cost": NCC_DIRECTLY_ACCESSED_DIAGNOSTIC_SERVICES_COST,
        "admitted_blended_cost": admitted_blended_cost,
        "icb_admitted_share": icb_admitted_share,
        "dm01_imaging_share": data['dm01_imaging_share'],
        "dm01_audiology_share": data['dm01_audiology_share'],
        "dm01_other_physio_share": data['dm01_other_physio_share'],
        "dm01_endoscopy_share": data['dm01_endoscopy_share'],
        "diag_weighted_cost": diag_weighted_cost,
        "diag_tests_per_pathway": DIAG_TESTS_PER_PATHWAY,
    },
    "providers": json.loads(df.to_json(orient='records')),
    "reference_solution": json.loads(result_df.to_json(orient='records')),
    "reference_totals": {
        "total_baseline": total_baseline, "total_reduction": total_reduction,
        "total_cost": total_cost, "pct_reduction": total_reduction / total_baseline,
        "higher_reduction_share": higher_reduction_share,
    },
}
with open('/tmp/solver_model_solution.json', 'w') as f:
    json.dump(bundle, f, indent=2, default=str)
print("\nSaved /tmp/solver_model_solution.json")
