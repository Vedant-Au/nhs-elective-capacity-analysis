"""
NHS Cheshire and Merseyside ICB — Elective Capacity Scenario and Strategy Model
Phase 5: scenario wayfinding engine.

PURPOSE
-------
Phase 3 produced a single optimal allocation of a fixed budget across three
capacity levers. That answer is only as good as the seven parameters feeding
it, four of which are analyst estimates rather than sourced figures. This
script asks the question the optimiser cannot: given that those parameters
are uncertain, which COMMITMENT should the ICB actually make, and what would
have to be observed for that commitment to be wrong?

METHOD AND PROVENANCE
---------------------
The structure follows Cairns, G. and Wright, G. (2018), Scenario Thinking:
Preparing Your Organization for the Future in an Unpredictable World, 2nd ed.,
Palgrave Macmillan:

  Ch. 2  the intuitive-logics "basic method", stages 1-8 (focal issue,
         driving forces, clustering, cluster outcomes, impact/uncertainty
         matrix, framing, scoping, developing)
  Ch. 5  Goodwin and Wright's sum-of-ranks decision analysis for evaluating
         strategies against scenarios on multiple objectives, plus the
         objective-weighting sensitivity test
  Ch. 8  robust strategy construction; Wright and Goodwin's (2009)
         flexible / diversified / insurable screen; early-warning flags

Two deliberate departures from the book, both because this project has
quantitative material the book's workshop setting does not:

  (a) Stage 5's impact/uncertainty matrix is normally populated by
      participants placing sticky notes by judgement. Here the IMPACT axis
      is computed — it is the swing in the LP objective when each driving
      force is moved across its plausible range with all others held at
      base (a one-at-a-time tornado). The UNCERTAINTY axis is graded against
      a published rubric tied to this project's own source-provenance record
      (see EVIDENCE_GRADES below), not by show of hands.

  (b) Stage 4's "two extreme yet plausible outcomes" per cluster are, where
      the data allows, taken from measured distributions rather than
      asserted — the demand range is the Phase 2 Monte Carlo forecast's own
      p5 and p95 at horizon end, not a round number chosen for symmetry.

Framing of the whole exercise follows Sminia, H. (2026), "From Scenario
Thinking to Scenario Doing: Strategic Management as Wayfinding", Futures &
Foresight Science 8:e70038 — the do-nothing case is treated as the baseline
"practical coping" trajectory, the scenario set as "conscious reflecting"
against a breakdown IN that trajectory, and the section of the output
covering conditions the model cannot resolve as a breakdown OF it, requiring
"practical solutioning" rather than a better optimum.

The institutional feasibility screen draws on Sminia, H. (2022), The
Strategic Manager, 3rd ed., Ch. 7 (institutional theory): a technically
optimal allocation that violates the legitimacy expectations of the field
will not in practice be enacted, so it is screened separately rather than
scored away inside the same weighted total.

WHAT IS COMPUTED VERSUS WHAT IS JUDGED
--------------------------------------
Every figure in the results grid is computed by the same validated LP used
in Phase 3. Three inputs are analyst judgements and are labelled as such in
the output rather than dressed up as calculations: the flexibility and
insurability scores, the institutional feasibility rating, and the plausible
ranges for driving forces where no measured distribution exists.

Reads   /tmp/solver_model_inputs.json  (produced by build_solver_inputs.py)
Writes  /tmp/scenario_wayfinding.json  and CSV extracts to OUT_DIR
"""
import json
import itertools
import numpy as np
import pandas as pd
from scipy.optimize import linprog

INPUTS = '/tmp/solver_model_inputs.json'
OUT_JSON = '/tmp/scenario_wayfinding.json'
OUT_DIR = '/tmp/scenario_out'

# ---------------------------------------------------------------------------
# Base parameters — identical to solve_capacity_optimizer.py (Phase 3).
# Any change here breaks comparability with the delivered Solver workbook,
# so these are copied verbatim rather than re-derived.
# ---------------------------------------------------------------------------
BASE = dict(
    budget=15_000_000.0,
    demand_mult=1.00,          # multiplier on the baseline over-52wk backlog
    inhouse_growth=0.15,
    diag_growth=0.10,
    is_growth=0.50,
    diag_tests_per_pathway=1.75,
    tariff_mult=1.00,          # multiplier on the NCC-derived unit tariff
    equity_tolerance_pp=0.15,
    bed_headroom_floor=0.10,
)

# NCC 2024/25 National Schedule of NHS costs — see solve_capacity_optimizer.py
NCC_ELECTIVE_INPATIENT_COST = 6624.0
NCC_ELECTIVE_INPATIENT_ACTIVITY = 1_255_967
NCC_DAYCASE_COST = 1078.0
NCC_DAYCASE_ACTIVITY = 7_680_341
NCC_OUTPATIENT_PROCEDURE_COST = 233.0
NCC_DIAGNOSTIC_IMAGING_COST = 140.0
NCC_AUDIOLOGY_COST = 107.0
NCC_DIAGNOSTIC_SERVICES_COST = 90.0

# ---------------------------------------------------------------------------
# Evidence grading rubric. Applied to each driving force to place it on the
# uncertainty axis of the Stage 5 matrix. Grades are assigned from this
# project's own documented provenance (docs/STATUS.md), not re-judged here.
# ---------------------------------------------------------------------------
EVIDENCE_GRADES = {
    1: "Sourced — published national dataset covering the current period "
       "(NCC 2024/25; NHS Payment Scheme 2025/26).",
    2: "Measured — derived from this warehouse's own observed data with a "
       "quantified interval attached (Phase 2 Monte Carlo forecast).",
    3: "Anchored estimate — extrapolated from warehouse data or from a "
       "stated national policy target, but not itself a published figure.",
    4: "Unsourced estimate — analyst judgement with no published source, or "
       "a quantity for which no public figure exists at any level.",
}


def build_cost_structure(data, tariff_mult, diag_tests_per_pathway):
    """Reproduce the Phase 3 cost model, with two scenario multipliers applied."""
    admitted_blended = (
        NCC_ELECTIVE_INPATIENT_COST * NCC_ELECTIVE_INPATIENT_ACTIVITY
        + NCC_DAYCASE_COST * NCC_DAYCASE_ACTIVITY
    ) / (NCC_ELECTIVE_INPATIENT_ACTIVITY + NCC_DAYCASE_ACTIVITY)
    s = data['icb_admitted_share']
    unit_tariff = (s * admitted_blended + (1 - s) * NCC_OUTPATIENT_PROCEDURE_COST) * tariff_mult
    diag_weighted = (
        data['dm01_imaging_share'] * NCC_DIAGNOSTIC_IMAGING_COST
        + data['dm01_audiology_share'] * NCC_AUDIOLOGY_COST
        + data['dm01_other_physio_share'] * NCC_DIAGNOSTIC_SERVICES_COST
        + data['dm01_endoscopy_share'] * NCC_OUTPATIENT_PROCEDURE_COST
    ) * tariff_mult
    # 2025/26 NHSPS pays NHS and independent-sector providers the same unit
    # price for elective activity — no marginal rate. c1 == c2 by policy.
    return unit_tariff, unit_tariff, diag_tests_per_pathway * diag_weighted


def solve(data, params, strategy=None):
    """Solve the Phase 3 LP under a given parameter set and strategy constraint set.

    strategy keys (all optional):
      lock       list of levers forced to zero, e.g. ['x2']
      min_share  {'x3': 0.50}  lever must take at least this share of spend
      max_share  {'x1': 0.50}  lever may take at most this share of spend
      equity_tolerance_pp  overrides the parameter value (equity stringency is
                           a policy choice made by the ICB, not an environmental
                           uncertainty, so it belongs to the strategy)
      spend_cap  fraction of the available budget the strategy commits
    """
    strategy = strategy or {}
    df = pd.DataFrame(data['providers']).copy()
    n_months = data['n_months']
    providers = df['provider_org_code'].tolist()
    P = len(providers)

    df['baseline_over52_total'] = df['baseline_over52_total'] * params['demand_mult']

    df['bed_scale'] = (df['bed_headroom_pct'] / params['bed_headroom_floor']).clip(upper=1.0)
    df['x1_cap'] = df['trailing_completions'] * params['inhouse_growth'] * df['bed_scale']
    df['x3_cap'] = df['trailing_completions'] * params['diag_growth']
    is_pool_monthly = data['is_ceiling_trailing_monthly'] * params['is_growth']
    backlog_share = df['baseline_over52_total'] / df['baseline_over52_total'].sum()
    df['x2_cap'] = backlog_share * is_pool_monthly

    C1, C2, C3 = build_cost_structure(data, params['tariff_mult'],
                                      params['diag_tests_per_pathway'])
    costs = {'x1': C1, 'x2': C2, 'x3': C3}

    budget = params['budget'] * strategy.get('spend_cap', 1.0)
    eq_tol = strategy.get('equity_tolerance_pp', params['equity_tolerance_pp'])

    higher_mask = df['higher_deprivation'].values.astype(bool)
    baseline = df['baseline_over52_total'].values
    higher_baseline_share = baseline[higher_mask].sum() / baseline.sum()
    target_share = higher_baseline_share - eq_tol

    var_names = ([f"x1_{p}" for p in providers] + [f"x2_{p}" for p in providers]
                 + [f"x3_{p}" for p in providers] + [f"red_{p}" for p in providers])
    n_vars = 4 * P
    idx = {n: i for i, n in enumerate(var_names)}

    c = np.zeros(n_vars)
    for p in providers:
        c[idx[f"red_{p}"]] = -1.0

    A_ub, b_ub = [], []

    # reduction_p <= n_months * (x1_p + x2_p + x3_p)
    for p in providers:
        row = np.zeros(n_vars)
        row[idx[f"red_{p}"]] = 1.0
        for lv in ('x1', 'x2', 'x3'):
            row[idx[f"{lv}_{p}"]] = -n_months
        A_ub.append(row); b_ub.append(0.0)

    # total spend <= budget
    row = np.zeros(n_vars)
    for p in providers:
        for lv in ('x1', 'x2', 'x3'):
            row[idx[f"{lv}_{p}"]] = n_months * costs[lv]
    A_ub.append(row); b_ub.append(budget)

    # equity floor on the higher-deprivation share of the reduction achieved
    row = np.zeros(n_vars)
    for p in providers:
        is_higher = bool(df.loc[df.provider_org_code == p, 'higher_deprivation'].values[0])
        row[idx[f"red_{p}"]] = target_share - (1.0 if is_higher else 0.0)
    A_ub.append(row); b_ub.append(0.0)

    # strategy: minimum share of total spend on a lever
    #   spend_lv >= share * total_spend  ->  share*total - spend_lv <= 0
    for lv, share in strategy.get('min_share', {}).items():
        row = np.zeros(n_vars)
        for p in providers:
            for k in ('x1', 'x2', 'x3'):
                row[idx[f"{k}_{p}"]] += share * n_months * costs[k]
            row[idx[f"{lv}_{p}"]] -= n_months * costs[lv]
        A_ub.append(row); b_ub.append(0.0)

    # strategy: maximum share of total spend on a lever
    for lv, share in strategy.get('max_share', {}).items():
        row = np.zeros(n_vars)
        for p in providers:
            row[idx[f"{lv}_{p}"]] += n_months * costs[lv]
            for k in ('x1', 'x2', 'x3'):
                row[idx[f"{k}_{p}"]] -= share * n_months * costs[k]
        A_ub.append(row); b_ub.append(0.0)

    locked = set(strategy.get('lock', []))
    bounds = []
    for name in var_names:
        lv, p = name.split('_', 1)
        if lv in ('x1', 'x2', 'x3'):
            cap = 0.0 if lv in locked else float(df.loc[df.provider_org_code == p, f'{lv}_cap'].values[0])
            bounds.append((0.0, cap))
        else:
            bounds.append((0.0, float(df.loc[df.provider_org_code == p, 'baseline_over52_total'].values[0])))

    A_ub_arr, b_ub_arr = np.array(A_ub), np.array(b_ub)
    res = linprog(c, A_ub=A_ub_arr, b_ub=b_ub_arr, bounds=bounds, method='highs')
    if not res.success:
        return {'feasible': False, 'message': res.message}

    # ---------------------------------------------------------------------
    # Degeneracy resolution (lexicographic second stage).
    #
    # This LP has multiple equally-optimal solutions whenever two levers are
    # priced identically — established in the Phase 3 build log, and confirmed
    # again here: the first pass returned the same 15,873 breaches cleared
    # with the higher-deprivation share landing anywhere between 30% and 100%
    # depending only on which optimal vertex the solver happened to reach.
    #
    # Any equity figure read off the first pass is therefore an artefact of
    # solver internals, not a property of the strategy, and must not be
    # ranked. The fix is to optimise hierarchically: hold total breaches
    # cleared at its optimum, then among all allocations that achieve it,
    # take the one that does most for higher-deprivation providers. That
    # yields a unique, reproducible figure with a clear meaning — the best
    # equity outcome obtainable at no cost to the primary objective.
    # ---------------------------------------------------------------------
    opt_reduction = -res.fun
    tol = max(1e-6 * abs(opt_reduction), 1e-6)
    row = np.zeros(n_vars)
    for p in providers:
        row[idx[f"red_{p}"]] = -1.0
    A2 = np.vstack([A_ub_arr, row])
    b2 = np.append(b_ub_arr, -(opt_reduction - tol))

    c2 = np.zeros(n_vars)
    for p in providers:
        if bool(df.loc[df.provider_org_code == p, 'higher_deprivation'].values[0]):
            c2[idx[f"red_{p}"]] = -1.0
    res2 = linprog(c2, A_ub=A2, b_ub=b2, bounds=bounds, method='highs')
    sol = res2.x if res2.success else res.x
    equity_resolved = bool(res2.success)

    # ---------------------------------------------------------------------
    # Third lexicographic stage: among all allocations that achieve both the
    # optimal reduction and the optimal equity outcome, take the one that
    # relies least on the evidence-weak levers.
    #
    # Added after the Phase 7 reproduction check found one cell in forty
    # returning identical volume and identical equity but a different lever
    # mix, and so a different delivery-risk figure — 0.855 against 0.823.
    # Delivery risk is a ranked objective, so leaving it unpinned meant
    # ranking solver internals rather than a property of the strategy. Costs
    # nothing in either prior objective by construction.
    # ---------------------------------------------------------------------
    risk_resolved = False
    if res2.success:
        opt_eq = -res2.fun
        tol_eq = max(1e-6 * abs(opt_eq), 1e-6)
        row_eq = np.zeros(n_vars)
        for p in providers:
            if bool(df.loc[df.provider_org_code == p, 'higher_deprivation'].values[0]):
                row_eq[idx[f"red_{p}"]] = -1.0
        c3 = np.zeros(n_vars)
        for lv in ('x2', 'x3'):          # the evidence-weak levers
            for p in providers:
                c3[idx[f"{lv}_{p}"]] = 1.0
        res3 = linprog(c3, A_ub=np.vstack([A2, row_eq]),
                       b_ub=np.append(b2, -(opt_eq - tol_eq)),
                       bounds=bounds, method='highs')
        if res3.success:
            sol = res3.x
            risk_resolved = True
    rows = []
    for p in providers:
        x1, x2, x3 = (sol[idx[f"x1_{p}"]], sol[idx[f"x2_{p}"]], sol[idx[f"x3_{p}"]])
        red = sol[idx[f"red_{p}"]]
        rows.append({
            'provider_org_code': p,
            'x1_inhouse_monthly': x1, 'x2_outsource_monthly': x2, 'x3_diagnostic_monthly': x3,
            'baseline_over52_18mo': float(df.loc[df.provider_org_code == p, 'baseline_over52_total'].values[0]),
            'reduction_18mo': red,
            'cost_18mo': n_months * (C1 * x1 + C2 * x2 + C3 * x3),
            'higher_deprivation': bool(df.loc[df.provider_org_code == p, 'higher_deprivation'].values[0]),
        })
    r = pd.DataFrame(rows)

    total_red = r['reduction_18mo'].sum()
    total_cost = r['cost_18mo'].sum()
    total_baseline = r['baseline_over52_18mo'].sum()
    higher_red = r.loc[r.higher_deprivation, 'reduction_18mo'].sum()

    spend = {lv: n_months * costs[lv] * r[f"{lv}_{s}"].sum()
             for lv, s in (('x1', 'inhouse_monthly'), ('x2', 'outsource_monthly'),
                           ('x3', 'diagnostic_monthly'))}
    total_spend = sum(spend.values())
    spend_share = {lv: (v / total_spend if total_spend > 0 else 0.0) for lv, v in spend.items()}

    # Capacity delivered by each lever, in pathways over the horizon. Used to
    # attribute the reduction to levers pro-rata, since reduction_p is a
    # min() of baseline and delivered capacity and cannot be split directly.
    cap_delivered = {lv: n_months * r[f"{lv}_{s}"].sum()
                     for lv, s in (('x1', 'inhouse_monthly'), ('x2', 'outsource_monthly'),
                                   ('x3', 'diagnostic_monthly'))}
    total_cap = sum(cap_delivered.values())
    # Delivery-risk exposure: the share of the reduction resting on the two
    # levers whose capacity assumptions are grade-4 analyst estimates (the
    # 50% independent-sector scaling headroom, and the 1.75 diagnostic
    # tests-per-pathway conversion). Lower is safer.
    weak_share = ((cap_delivered['x2'] + cap_delivered['x3']) / total_cap) if total_cap > 0 else 0.0

    hhi = sum(s ** 2 for s in spend_share.values()) if total_spend > 0 else 1.0

    return {
        'feasible': True,
        'equity_resolved_lexicographically': equity_resolved,
        'delivery_risk_resolved_lexicographically': risk_resolved,
        'total_baseline': float(total_baseline),
        'total_reduction': float(total_red),
        'pct_reduction': float(total_red / total_baseline) if total_baseline else 0.0,
        'total_cost': float(total_cost),
        'higher_reduction': float(higher_red),
        'higher_reduction_share': float(higher_red / total_red) if total_red > 0 else 0.0,
        'higher_baseline_share': float(higher_baseline_share),
        'breaches_per_million': float(total_red / (total_cost / 1e6)) if total_cost > 0 else 0.0,
        'delivery_risk_exposure': float(weak_share),
        'lever_diversification': float(1.0 - hhi),
        'spend_share_x1': spend_share['x1'],
        'spend_share_x2': spend_share['x2'],
        'spend_share_x3': spend_share['x3'],
        'unit_costs': {'c1': C1, 'c2': C2, 'c3': C3},
        'allocation': r.to_dict(orient='records'),
    }


# ---------------------------------------------------------------------------
# Stage 1-4: focal issue, driving forces, clusters, cluster outcomes.
#
# Focal issue of concern: how should NHS Cheshire and Merseyside ICB commit
# constrained elective-recovery capacity funding across the 18 months to
# September 2027, given that the backlog it is trying to clear, the price of
# clearing it, and the deliverable headroom in each lever are all uncertain?
#
# Driving forces are environmental uncertainties the ICB does not control.
# Equity stringency is deliberately NOT here: it is a policy choice the ICB
# does control, and so is modelled as a dimension of strategy instead.
# ---------------------------------------------------------------------------
DRIVING_FORCES = [
    dict(key='budget', cluster='Funding settlement', pestel='Political / Economic',
         label='Elective recovery funding envelope available to the ICB (18 months)',
         low=7_500_000.0, base=15_000_000.0, high=30_000_000.0,
         low_label='£7.5m — constrained settlement', high_label='£30m — expanded recovery funding',
         grade=4,
         basis='No ICB-level elective recovery budget is published at any level. '
               'The Phase 3 default of £15m was set as an illustrative, deliberately '
               'binding envelope, never as a sourced figure. Range spans half to '
               'double that anchor.'),
    dict(key='demand_mult', cluster='Backlog trajectory', pestel='Social / Economic',
         label='Over-52-week backlog to be cleared, relative to central forecast',
         low=0.9112, base=1.00, high=1.1466,
         low_label='p5 — backlog undershoots forecast', high_label='p95 — backlog overshoots forecast',
         grade=2,
         basis='Taken directly from the Phase 2 Monte Carlo waiting-list forecast: '
               'the ratio of the p5 and p95 ICB totals to the p50 total at horizon '
               'end (September 2027). Measured, not assumed.'),
    dict(key='is_growth', cluster='Independent-sector capacity', pestel='Economic / Political',
         label='Independent-sector headroom above current NHS-funded activity',
         low=0.20, base=0.50, high=0.80,
         low_label='+20% — sector at practical capacity', high_label='+80% — sector scales readily',
         grade=4,
         basis='Analyst assumption from Phase 3, chosen on the reasoning that the '
               'independent sector is more scalable short-term than NHS in-house '
               'capacity. No published measure of independent-sector spare elective '
               'capacity for this ICB exists.'),
    dict(key='inhouse_growth', cluster='NHS productivity', pestel='Technological / Social',
         label='Achievable uplift in NHS in-house elective completions',
         low=0.05, base=0.15, high=0.25,
         low_label='+5% — productivity stalls', high_label='+25% — sustained productivity gain',
         grade=3,
         basis="Anchored on the Elective Recovery Fund's own national 10% activity "
               'increase target plus a buffer. Policy-anchored, but the achievable '
               'rate for these specific trusts is not published.'),
    dict(key='diag_tests_per_pathway', cluster='Diagnostic conversion', pestel='Technological',
         label='Diagnostic tests required to unlock one completed RTT pathway',
         low=1.25, base=1.75, high=3.50,
         low_label='1.25 — efficient conversion', high_label='3.50 — test-heavy pathways',
         grade=4,
         basis='The single remaining unsourced figure in the Phase 3 cost model, '
               'flagged as such throughout. No NHS dataset publishes this ratio. '
               'It sets the unit cost of the diagnostic lever and therefore how '
               'much capacity a given budget buys through it. The upper bound is '
               'set at 3.50 deliberately: the diagnostic and treatment levers are '
               'indifferent at 3.34 tests per pathway (see tipping_points()), and a '
               'range that stopped short of that point would conceal the only '
               'decision in the model rather than test it. Three or more tests to '
               'reach a treatment decision is clinically ordinary on complex '
               'pathways, so the bound is plausible as well as convenient.'),
    dict(key='tariff_mult', cluster='Payment policy and cost base', pestel='Political / Legal',
         label='Unit cost of elective activity relative to NCC 2024/25 baseline',
         low=0.90, base=1.00, high=1.20,
         low_label='-10% — costs contained', high_label='+20% — cost or policy inflation',
         grade=1,
         basis='Unit costs are sourced from NCC 2024/25 and the 2025/26 NHS Payment '
               'Scheme. Graded low-uncertainty on provenance, but ranged anyway: the '
               'removal of the ERF marginal-rate mechanism for 2025/26 is direct '
               'evidence that payment policy does change materially between years.'),
]


def tipping_points(data):
    """Locate the parameter values at which the optimal lever mix changes shape.

    A sensitivity range tells you how much the answer moves. A tipping point
    tells you where the answer becomes a different answer, which is the more
    useful thing for a decision-maker to hold. Found by bisection on the
    spend mix rather than on the objective value, because the objective is
    continuous across the switch while the mix is not.
    """
    def mix_signature(p):
        r = solve(data, p)
        return tuple(round(r[f'spend_share_{lv}'], 3) > 0.01 for lv in ('x1', 'x2', 'x3'))

    results = []
    for f in DRIVING_FORCES:
        lo, hi = f['low'], f['high']
        if mix_signature({**BASE, f['key']: lo}) == mix_signature({**BASE, f['key']: hi}):
            results.append({'cluster': f['cluster'], 'key': f['key'],
                            'tipping_point': None,
                            'note': 'No change in the optimal lever mix anywhere in '
                                    'the plausible range.'})
            continue
        sig_lo = mix_signature({**BASE, f['key']: lo})
        a, b = lo, hi
        for _ in range(60):
            mid = (a + b) / 2.0
            if mix_signature({**BASE, f['key']: mid}) == sig_lo:
                a = mid
            else:
                b = mid
        results.append({'cluster': f['cluster'], 'key': f['key'],
                        'tipping_point': (a + b) / 2.0,
                        'base_value': f['base'],
                        'note': f"Optimal lever mix changes shape at "
                                f"{(a + b) / 2.0:.3f} (base assumption {f['base']})."})
    return pd.DataFrame(results)


def one_at_a_time_impact(data, at=None, label='base'):
    """Stage 5, impact axis: swing in breaches cleared when each driving force
    moves across its plausible range, all others held at base. This is a
    tornado analysis, and it is what places each cluster on the impact axis
    instead of a participant's judgement.

    A one-at-a-time tornado is only valid at the point it is evaluated. `at`
    allows the same sweep to be re-run from a different corner of the
    parameter space so that state-dependence can be detected rather than
    assumed away — see stability_check()."""
    anchor = {**BASE, **(at or {})}
    base_res = solve(data, anchor)
    out = []
    for f in DRIVING_FORCES:
        lo = solve(data, {**anchor, f['key']: f['low']})
        hi = solve(data, {**anchor, f['key']: f['high']})
        lo_v, hi_v = lo['total_reduction'], hi['total_reduction']
        out.append({
            'anchor': label,
            'cluster': f['cluster'], 'key': f['key'], 'pestel': f['pestel'],
            'label': f['label'],
            'low_value': f['low'], 'base_value': f['base'], 'high_value': f['high'],
            'low_label': f['low_label'], 'high_label': f['high_label'],
            'reduction_at_low': lo_v, 'reduction_at_base': base_res['total_reduction'],
            'reduction_at_high': hi_v,
            'swing_breaches': abs(hi_v - lo_v),
            'swing_pct_of_base': abs(hi_v - lo_v) / base_res['total_reduction'],
            'evidence_grade': f['grade'],
            'evidence_grade_meaning': EVIDENCE_GRADES[f['grade']],
            'evidence_basis': f['basis'],
        })
    d = pd.DataFrame(out).sort_values('swing_breaches', ascending=False)
    # criticality = normalised impact x normalised uncertainty; the two
    # highest-scoring clusters become scenario Factors A and B (Stage 5/6).
    d['impact_norm'] = d['swing_breaches'] / d['swing_breaches'].max()
    d['uncertainty_norm'] = (d['evidence_grade'] - 1) / 3.0
    d['criticality'] = d['impact_norm'] * d['uncertainty_norm']
    return d.sort_values('criticality', ascending=False).reset_index(drop=True)


def stability_check(data):
    """Re-run the tornado from the far corner of the most critical driver and
    report whether the ordering of driving forces is stable.

    This matters here specifically: at the base assumption the diagnostic
    lever dominates and the treatment levers are never used, so their
    capacity assumptions register zero impact. Past the diagnostic tipping
    point they are the only levers in play. A matrix built at one anchor and
    presented as the matrix would have understated them to zero."""
    base_m = one_at_a_time_impact(data, at=None, label='base')
    alt_at = {'diag_tests_per_pathway': 3.50}
    alt_m = one_at_a_time_impact(data, at=alt_at, label='diagnostic conversion high')
    merged = base_m[['cluster', 'swing_breaches', 'criticality']].merge(
        alt_m[['cluster', 'swing_breaches', 'criticality']],
        on='cluster', suffixes=('_base', '_alt'))
    merged['state_dependent'] = (
        ((merged.swing_breaches_base < 1.0) & (merged.swing_breaches_alt >= 1.0))
        | ((merged.swing_breaches_base >= 1.0) & (merged.swing_breaches_alt < 1.0))
    )
    return merged, alt_m


def detect_degeneracy(grid):
    """Flag strategy pairs that produce identical results everywhere.

    The Phase 3 build log already established that this LP is degenerate when
    two levers are priced identically. If two nominally different strategies
    are in fact the same commitment, that must be reported rather than left
    for a reader to assume the model discriminated between them."""
    metrics = ['breaches_cleared', 'breaches_cleared_higher_deprivation',
               'breaches_per_million', 'delivery_risk_exposure']
    piv = grid.pivot_table(index='strategy', columns='scenario', values=metrics)
    pairs = []
    codes = list(piv.index)
    for i in range(len(codes)):
        for j in range(i + 1, len(codes)):
            a, b = piv.loc[codes[i]].values, piv.loc[codes[j]].values
            if np.allclose(np.nan_to_num(a), np.nan_to_num(b), rtol=1e-6, atol=1e-4):
                pairs.append((codes[i], codes[j]))
    return pairs


# ---------------------------------------------------------------------------
# Stage 3: candidate strategies. Each is a genuine commitment expressed as a
# constraint set over the same LP, so all are evaluated on identical terms.
# ---------------------------------------------------------------------------
STRATEGIES = [
    dict(code='S0', name='Hold position',
         summary='Commit no additional recovery funding. The backlog follows its '
                 'business-as-usual trajectory.',
         spec=dict(spend_cap=0.0),
         rationale='Included because a do-nothing baseline is the only way to state '
                   'what the other strategies buy. In wayfinding terms this is the '
                   'practical-coping trajectory the ICB is already on.',
         flexible=5, insurable=5,
         flex_note='Fully reversible — no commitment is made.',
         insure_note='No downside to insure against beyond the backlog itself.',
         institutional='High legitimacy risk. Regulator and public expectation is '
                       'visible action on 52-week waits; inaction is not a defensible '
                       'position even where it is affordable.'),
    dict(code='S1', name='Unconstrained optimisation',
         summary='Allocate the full envelope wherever the model says it clears the '
                 'most breaches, with the standing 15pp equity tolerance.',
         spec=dict(),
         rationale='The Phase 3 answer, carried forward unchanged so that the value '
                   'of every added constraint can be read off against it.',
         flexible=3, insurable=2,
         flex_note='Mixed. Scalability depends on which levers the optimum happens '
                   'to select, which is not stable across scenarios.',
         insure_note='Hard to contract against, because the commitment is not '
                     'describable in advance of the solve.',
         institutional='Moderate risk. An allocation that changes shape whenever an '
                       'input is revised is difficult to defend to provider boards, '
                       'who experience it as arbitrary.'),
    dict(code='S2', name='NHS delivery only',
         summary='Deliver recovery entirely through NHS providers — in-house '
                 'treatment capacity or diagnostic capacity. No independent-sector '
                 'outsourcing.',
         spec=dict(lock=['x2']),
         rationale='Tests the position that recovery money should build durable NHS '
                   'capability rather than buy activity that leaves no residue.',
         flexible=2, insurable=2,
         flex_note='Low. Substantive capacity implies recruitment and estate '
                   'commitments that cannot be unwound within the horizon.',
         insure_note='Limited. Fixed costs persist if demand falls away.',
         institutional='High legitimacy within the provider field; aligns with '
                       'professional and staff-side expectations about where '
                       'recovery money should go.'),
    dict(code='S3', name='No in-house expansion',
         summary='Deliver recovery by buying independent-sector activity and by '
                 'unlocking diagnostics. No expansion of in-house treatment '
                 'capacity.',
         spec=dict(lock=['x1']),
         rationale='Tests the opposite position: fastest access to activity, no '
                   'long-term cost base.',
         flexible=5, insurable=4,
         flex_note='High. Contracted volumes can be scaled or stopped between '
                   'periods.',
         insure_note='Good. Volume risk sits with the provider under a per-case '
                     'contract.',
         institutional='Contested. Independent-sector reliance is politically '
                       'sensitive within the NHS field and attracts staff-side '
                       'objection even where it performs.'),
    dict(code='S4', name='Diagnostic-led recovery',
         summary='Direct at least half the envelope to diagnostic capacity, on the '
                 'basis that diagnostics gate the pathway.',
         spec=dict(min_share={'x3': 0.50}),
         rationale='Tests whether unlocking the diagnostic constraint clears more '
                   'pathways per pound than adding treatment capacity directly.',
         flexible=3, insurable=2,
         flex_note='Moderate. Equipment and workforce commitments are partly '
                   'reversible; capital elements are not.',
         insure_note='Weak. Benefit depends on the unsourced conversion ratio.',
         institutional='Strong legitimacy — matches the national diagnostic-capacity '
                       'policy direction and is readily explained to boards.'),
    dict(code='S5', name='Equity-first',
         summary='Require higher-deprivation providers to receive at least their '
                 'baseline share of the breaches cleared. No equity tolerance.',
         spec=dict(equity_tolerance_pp=0.0),
         rationale='Tests the cost of removing the 15pp tolerance and holding a hard '
                   'proportionality floor instead.',
         flexible=3, insurable=2,
         flex_note='Moderate — the constraint binds allocation, not contract form.',
         insure_note='Weak.',
         institutional='Strong legitimacy. Directly answers the statutory duty to '
                       'reduce inequalities in access and is straightforward to '
                       'evidence.'),
    dict(code='S7', name='Treatment capacity only',
         summary='Fund treatment capacity — in-house or independent sector — and '
                 'nothing through the diagnostic lever.',
         spec=dict(lock=['x3']),
         rationale='The counterpart to S4, and the strategy that prices the '
                   'diagnostic bet. Because the diagnostic lever rests entirely on '
                   'the one unsourced parameter in the model, this shows what the '
                   'programme delivers if that assumption is set aside altogether.',
         flexible=3, insurable=3,
         flex_note='Mixed — depends on the in-house / outsourced split, which is '
                   'left to the solve.',
         insure_note='Partial, through the outsourced component.',
         institutional='Low risk but low ambition. Treats the diagnostic constraint '
                       'as fixed, which sits awkwardly against national policy '
                       'emphasis on diagnostic capacity.'),
    dict(code='S6', name='Diversified hedge',
         summary='Cap any single lever at 50% of spend, so the programme is never '
                 'more than half exposed to one delivery assumption.',
         spec=dict(max_share={'x1': 0.50, 'x2': 0.50, 'x3': 0.50}),
         rationale='Constructed against the Ch.8 principle that keeping options open '
                   'beats optimising to a single expected case when the key inputs '
                   'are weakly evidenced.',
         flexible=4, insurable=3,
         flex_note='Good. Any one strand can be scaled back without collapsing the '
                   'programme.',
         insure_note='Moderate — the outsourced strand carries contractual '
                     'protection, the others less so.',
         institutional='Defensible. Spreads exposure across the competing positions '
                       'in the field rather than adjudicating between them.'),
]


def build_scenarios(matrix):
    """Stages 5-7: take the two most critical clusters as Factors A and B,
    frame their extremes, and scope the resulting 2x2 into four scenarios.
    A fifth case, the central forecast, is carried as the reference baseline."""
    fa, fb = matrix.iloc[0], matrix.iloc[1]
    fmap = {f['key']: f for f in DRIVING_FORCES}
    scenarios = []
    for (a_side, b_side) in itertools.product(['low', 'high'], repeat=2):
        params = dict(BASE)
        params[fa['key']] = fmap[fa['key']][a_side]
        params[fb['key']] = fmap[fb['key']][b_side]
        scenarios.append({
            'code': f"{'A1' if a_side == 'low' else 'A2'}{'B1' if b_side == 'low' else 'B2'}",
            'factor_a': fa['cluster'], 'factor_a_state': fmap[fa['key']][f'{a_side}_label'],
            'factor_b': fb['cluster'], 'factor_b_state': fmap[fb['key']][f'{b_side}_label'],
            'params': params,
        })
    scenarios.append({
        'code': 'BASE', 'factor_a': fa['cluster'], 'factor_a_state': 'central',
        'factor_b': fb['cluster'], 'factor_b_state': 'central', 'params': dict(BASE),
    })
    return scenarios, fa, fb


# Precision at which two results are treated as the same result before ranking.
#
# Necessary, not cosmetic. Several strategies reach an identical outcome by
# different routes, and the LP returns those outcomes to within solver
# tolerance rather than bit-identically — 63,493.495 against 63,493.432, a
# difference of 0.06 of a breach in 63,493. Ranked raw, those become distinct
# and the tie-break is decided by floating-point noise; the same workbook
# recomputing the same quantity in Excel then produces a different ordering.
# Rounding to a precision that is meaningful in the real world makes genuine
# ties resolve as ties in both engines.
RANK_PRECISION = {
    'breaches_cleared': 0,                       # whole breaches
    'breaches_cleared_higher_deprivation': 0,
    'breaches_per_million': 1,
    'delivery_risk_exposure': 4,
}


def canonicalise(grid):
    """Reduce the grid to ONE rounded basis, shared by this engine and the
    delivered workbook.

    Rounding in two places is worse than not rounding at all. An earlier
    version rounded the ranking basis here while the workbook recomputed
    value-for-money from the rounded breaches — so Excel divided 42,454 by
    the budget where Python divided 42,454.334, and the two disagreed on
    which strategies were tied. Derived quantities are therefore rebuilt
    from the rounded inputs, exactly as the workbook's own formulas do, and
    everything downstream reads from this one basis.
    """
    g = grid.copy()
    g['breaches_cleared'] = g['breaches_cleared'].round(
        RANK_PRECISION['breaches_cleared'])
    g['breaches_cleared_higher_deprivation'] = (
        g['breaches_cleared_higher_deprivation'].round(
            RANK_PRECISION['breaches_cleared_higher_deprivation']))
    g['delivery_risk_exposure'] = g['delivery_risk_exposure'].round(
        RANK_PRECISION['delivery_risk_exposure'])
    g['breaches_per_million'] = np.where(
        g['total_cost'] > 0,
        (g['breaches_cleared'] / (g['total_cost'] / 1e6)).round(
            RANK_PRECISION['breaches_per_million']),
        0.0)
    g['equity_share'] = np.where(
        g['breaches_cleared'] > 0,
        g['breaches_cleared_higher_deprivation'] / g['breaches_cleared'], 0.0)
    return g


def sum_of_ranks(grid, objectives, weights=None):
    """Cairns and Wright Ch.5, stages 4-6. Rank every strategy-scenario
    combination within each objective across the whole grid, then sum the
    ranks per strategy. Lower total is better."""
    weights = weights or {o: 1 for o in objectives}
    g = grid.copy()
    for obj, direction in objectives.items():
        asc = (direction == 'min')
        g[f'rank_{obj}'] = g[obj].rank(ascending=asc, method='min')
    g['sum_of_ranks'] = sum(g[f'rank_{o}'] * w for o, w in weights.items())
    return g


def main():
    import os
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(INPUTS) as f:
        data = json.load(f)

    print('=' * 78)
    print('STAGE 5 — IMPACT / UNCERTAINTY MATRIX')
    print('=' * 78)
    matrix = one_at_a_time_impact(data)
    print(matrix[['cluster', 'swing_breaches', 'swing_pct_of_base',
                  'evidence_grade', 'criticality']].to_string(index=False))

    print('\n--- tipping points (where the optimal lever mix changes shape) ---')
    tips = tipping_points(data)
    print(tips.to_string(index=False))

    print('\n--- anchor-stability check on the tornado ---')
    stab, alt_matrix = stability_check(data)
    print(stab.to_string(index=False))
    flipped = stab.loc[stab.state_dependent, 'cluster'].tolist()
    if flipped:
        print('STATE-DEPENDENT drivers (zero impact at one anchor, live at the '
              'other): ' + ', '.join(flipped))

    scenarios, fa, fb = build_scenarios(matrix)
    print(f"\nFactor A: {fa['cluster']}  (criticality {fa['criticality']:.3f})")
    print(f"Factor B: {fb['cluster']}  (criticality {fb['criticality']:.3f})")

    print('\n' + '=' * 78)
    print('STRATEGY x SCENARIO GRID')
    print('=' * 78)
    rows, allocations = [], {}
    for sc in scenarios:
        for st in STRATEGIES:
            r = solve(data, sc['params'], st['spec'])
            if not r['feasible']:
                rows.append({'scenario': sc['code'], 'strategy': st['code'],
                             'strategy_name': st['name'], 'feasible': False})
                continue
            rows.append({
                'scenario': sc['code'], 'strategy': st['code'], 'strategy_name': st['name'],
                'feasible': True,
                'breaches_cleared': r['total_reduction'],
                'breaches_cleared_higher_deprivation': r['higher_reduction'],
                'equity_share': r['higher_reduction_share'],
                'breaches_per_million': r['breaches_per_million'],
                'delivery_risk_exposure': r['delivery_risk_exposure'],
                'total_cost': r['total_cost'],
                'pct_of_baseline_cleared': r['pct_reduction'],
                'lever_diversification': r['lever_diversification'],
                'spend_share_x1': r['spend_share_x1'],
                'spend_share_x2': r['spend_share_x2'],
                'spend_share_x3': r['spend_share_x3'],
            })
            allocations[f"{sc['code']}|{st['code']}"] = r['allocation']
    grid = canonicalise(pd.DataFrame(rows))

    objectives = {
        'breaches_cleared': 'max',
        'breaches_cleared_higher_deprivation': 'max',
        'breaches_per_million': 'max',
        'delivery_risk_exposure': 'min',
    }
    ranked = sum_of_ranks(grid, objectives)
    by_strategy = (ranked.groupby(['strategy', 'strategy_name'])['sum_of_ranks']
                   .sum().reset_index().sort_values('sum_of_ranks'))
    print(by_strategy.to_string(index=False))

    # Weight sensitivity — Ch.5's test of whether the ordering survives a
    # decision-maker caring markedly more about one objective.
    weight_tests = {}
    for obj in objectives:
        for mult in (2, 3):
            w = {o: (mult if o == obj else 1) for o in objectives}
            rk = sum_of_ranks(grid, objectives, w)
            order = (rk.groupby('strategy')['sum_of_ranks'].sum()
                     .sort_values().index.tolist())
            weight_tests[f'{obj}_x{mult}'] = order

    # Minimax regret on the primary objective (Ch.8), on the same rounded
    # basis as the ranks so that the two analyses cannot disagree about
    # which strategies tie.
    reg = grid.pivot(index='strategy', columns='scenario', values='breaches_cleared')
    regret = reg.max(axis=0) - reg
    max_regret = regret.max(axis=1).sort_values()

    dups = detect_degeneracy(grid)
    if dups:
        print('\nDEGENERATE STRATEGY PAIRS (identical on every objective in every '
              'scenario): ' + ', '.join(f'{a}={b}' for a, b in dups))

    out = {
        'matrix': matrix.to_dict(orient='records'),
        'matrix_alt_anchor': alt_matrix.to_dict(orient='records'),
        'stability_check': stab.to_dict(orient='records'),
        'tipping_points': tips.to_dict(orient='records'),
        'degenerate_pairs': dups,
        'factor_a': fa['cluster'], 'factor_b': fb['cluster'],
        'scenarios': [{k: v for k, v in s.items()} for s in scenarios],
        'grid': grid.to_dict(orient='records'),
        'ranked': ranked.to_dict(orient='records'),
        'by_strategy': by_strategy.to_dict(orient='records'),
        'weight_tests': weight_tests,
        'regret': regret.to_dict(),
        'max_regret': max_regret.to_dict(),
        'strategies': [{k: v for k, v in s.items() if k != 'spec'} for s in STRATEGIES],
        'evidence_grades': EVIDENCE_GRADES,
        'base_params': BASE,
        'allocations': allocations,
    }
    with open(OUT_JSON, 'w') as f:
        json.dump(out, f, indent=2, default=str)

    matrix.to_csv(f'{OUT_DIR}/driving_forces_matrix.csv', index=False)
    grid.to_csv(f'{OUT_DIR}/strategy_scenario_grid.csv', index=False)
    ranked.to_csv(f'{OUT_DIR}/decision_analysis_ranks.csv', index=False)
    regret.to_csv(f'{OUT_DIR}/regret_matrix.csv')

    print('\nMinimax regret (breaches cleared, lower is better):')
    print(max_regret.to_string())
    print(f'\nWritten: {OUT_JSON} and CSVs to {OUT_DIR}')


if __name__ == '__main__':
    main()
