"""
Healthcare Capacity Optimisation Toolkit — optimisation and scenario engine.

Generalised from the Cheshire and Merseyside Phase 5 engine. The method is
unchanged; what changed is that levers, costs, driving forces, strategies and
objectives are now read from the engagement config rather than declared here.

Method basis: Cairns and Wright (2018) Scenario Thinking, 2nd ed. — Ch.2 basic
method, Ch.5 sum-of-ranks decision analysis, Ch.8 robust strategy and flags.

Three design decisions carried forward from the original build because each was
made in response to a defect found in validation, and each would silently
reintroduce that defect if dropped:

  1. Lexicographic solve. The LP has multiple equally optimal solutions
     whenever two levers are priced identically, so any metric read off the
     allocation — equity above all — is otherwise an artefact of which optimal
     vertex the solver happened to reach.
  2. One canonical rounding. Derived quantities are rebuilt from rounded
     inputs, so a workbook recomputing them in Excel cannot disagree with this
     engine about which strategies tie.
  3. Anchor-stability check on the tornado. A one-at-a-time sweep is valid only
     at the point it is evaluated, and a lever that is inert at the base case
     can be the only live lever past a tipping point.
"""
import itertools
import numpy as np
import pandas as pd
from scipy.optimize import linprog


# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------
def build_costs(cfg, data, tariff_mult, tests_per_pathway):
    """Blend the configured cost components into a price per cleared pathway
    for each lever type."""
    c = cfg['costs']
    comps = c['treatment_components']
    tot_act = sum(x['national_activity'] for x in comps)
    admitted_blend = sum(x['unit_cost'] * x['national_activity'] for x in comps) / tot_act
    s = data['admitted_share']
    unit = (s * admitted_blend + (1 - s) * c['non_admitted_unit_cost']['unit_cost'])
    unit *= tariff_mult

    diag_unit = sum(cfg['costs']['diagnostic_currencies'][k]['unit_cost'] * share
                    for k, share in data['diagnostic_mix'].items()) * tariff_mult

    return {
        'treatment': unit,
        'treatment_outsourced': unit * c['outsourcing_price_multiplier'],
        'diagnostic': tests_per_pathway * diag_unit,
    }


def base_params(cfg):
    p = {
        'budget': float(cfg['budget']['default']),
        'demand_mult': 1.0,
        'tariff_mult': 1.0,
        'diag_tests_per_pathway': float(cfg['diagnostic_conversion']['tests_per_pathway']),
        'equity_tolerance_pp': float(cfg['equity']['tolerance_pp']),
        'bed_headroom_floor': float(cfg.get('bed_headroom_floor', 0.10)),
    }
    for key, lv in cfg['levers'].items():
        p[f'{key}_growth'] = float(lv['growth_rate'])
    # Aliases so driving forces can be named in domain terms.
    p['inhouse_growth'] = p.get('x1_growth', 0.0)
    p['is_growth'] = p.get('x2_growth', 0.0)
    return p


def _sync_aliases(p):
    p = dict(p)
    if 'inhouse_growth' in p:
        p['x1_growth'] = p['inhouse_growth']
    if 'is_growth' in p:
        p['x2_growth'] = p['is_growth']
    return p


# ---------------------------------------------------------------------------
# The optimisation
# ---------------------------------------------------------------------------
def solve(cfg, data, params, strategy=None):
    params = _sync_aliases(params)
    strategy = strategy or {}
    levers = cfg['levers']
    lever_keys = list(levers.keys())

    df = pd.DataFrame(data['providers']).copy()
    n = data['n_months']
    providers = df['provider_org_code'].tolist()
    P = len(providers)

    df['baseline_over52_total'] = df['baseline_over52_total'] * params['demand_mult']
    floor = params['bed_headroom_floor']
    df['bed_scale'] = (df['bed_headroom_pct'] / floor).clip(upper=1.0)

    backlog_share = (df['baseline_over52_total'] / df['baseline_over52_total'].sum()
                     if df['baseline_over52_total'].sum() > 0
                     else pd.Series(1.0 / P, index=df.index))

    for k, lv in levers.items():
        g = params[f'{k}_growth']
        if lv['cap_basis'] == 'trailing_activity':
            cap = df['trailing_completions'] * g
            if lv.get('scale_by_bed_headroom'):
                cap = cap * df['bed_scale']
        elif lv['cap_basis'] == 'outsourcing_pool':
            cap = backlog_share * data['is_ceiling_trailing_monthly'] * g
        else:
            raise ValueError(f'Unknown cap_basis {lv["cap_basis"]!r} for lever {k}')
        df[f'{k}_cap'] = cap

    costs_by_type = build_costs(cfg, data, params['tariff_mult'],
                                params['diag_tests_per_pathway'])
    cost = {k: costs_by_type[levers[k]['price']] for k in lever_keys}

    budget = params['budget'] * strategy.get('spend_cap', 1.0)
    eq_tol = strategy.get('equity_tolerance_pp', params['equity_tolerance_pp'])

    higher = df['higher_deprivation'].values.astype(bool)
    baseline = df['baseline_over52_total'].values
    higher_baseline_share = (baseline[higher].sum() / baseline.sum()
                             if baseline.sum() > 0 else 0.0)
    target_share = higher_baseline_share - eq_tol

    names = [f'{k}_{p}' for k in lever_keys for p in providers] + \
            [f'red_{p}' for p in providers]
    nv = len(names)
    idx = {nm: i for i, nm in enumerate(names)}

    c = np.zeros(nv)
    for p in providers:
        c[idx[f'red_{p}']] = -1.0

    A, b = [], []
    for p in providers:
        row = np.zeros(nv)
        row[idx[f'red_{p}']] = 1.0
        for k in lever_keys:
            row[idx[f'{k}_{p}']] = -n
        A.append(row); b.append(0.0)

    row = np.zeros(nv)
    for p in providers:
        for k in lever_keys:
            row[idx[f'{k}_{p}']] = n * cost[k]
    A.append(row); b.append(budget)

    row = np.zeros(nv)
    for i, p in enumerate(providers):
        row[idx[f'red_{p}']] = target_share - (1.0 if higher[i] else 0.0)
    A.append(row); b.append(0.0)

    for k, share in strategy.get('min_share', {}).items():
        row = np.zeros(nv)
        for p in providers:
            for j in lever_keys:
                row[idx[f'{j}_{p}']] += share * n * cost[j]
            row[idx[f'{k}_{p}']] -= n * cost[k]
        A.append(row); b.append(0.0)

    for k, share in strategy.get('max_share', {}).items():
        row = np.zeros(nv)
        for p in providers:
            row[idx[f'{k}_{p}']] += n * cost[k]
            for j in lever_keys:
                row[idx[f'{j}_{p}']] -= share * n * cost[j]
        A.append(row); b.append(0.0)

    locked = set(strategy.get('lock', []))
    bounds = []
    for nm in names:
        pre, p = nm.split('_', 1)
        if pre == 'red':
            bounds.append((0.0, float(df.loc[df.provider_org_code == p,
                                             'baseline_over52_total'].values[0])))
        else:
            cap = 0.0 if pre in locked else float(
                df.loc[df.provider_org_code == p, f'{pre}_cap'].values[0])
            bounds.append((0.0, max(cap, 0.0)))

    A, b = np.array(A), np.array(b)
    res = linprog(c, A_ub=A, b_ub=b, bounds=bounds, method='highs')
    if not res.success:
        return {'feasible': False, 'message': res.message}

    # -----------------------------------------------------------------
    # Lexicographic refinement — see module docstring, decision 1.
    #
    # Three stages, not two. Each stage pins one reported quantity that the
    # previous stage leaves free, because anything a solve does not pin is
    # decided by which optimal vertex the solver happens to reach and must
    # not then be ranked.
    #
    #   1. maximise breaches cleared
    #   2. among those, maximise the reduction reaching higher-need providers
    #   3. among those, minimise reliance on the evidence-weak levers
    #
    # Stage 3 was added after the Phase 7 reproduction check: one cell in
    # forty returned identical volume and identical equity but a different
    # lever mix, and therefore a different delivery-risk figure — 0.855
    # against 0.823 for the same allocation quality. Delivery risk is a
    # ranked objective, so leaving it unpinned meant ranking solver
    # internals. The stage costs nothing in either prior objective by
    # construction.
    # -----------------------------------------------------------------
    opt = -res.fun
    tol = max(1e-6 * abs(opt), 1e-6)
    row_vol = np.zeros(nv)
    for p in providers:
        row_vol[idx[f'red_{p}']] = -1.0

    c2 = np.zeros(nv)
    for i, p in enumerate(providers):
        if higher[i]:
            c2[idx[f'red_{p}']] = -1.0
    A2 = np.vstack([A, row_vol])
    b2 = np.append(b, -(opt - tol))
    res2 = linprog(c2, A_ub=A2, b_ub=b2, bounds=bounds, method='highs')
    sol = res2.x if res2.success else res.x

    if res2.success:
        opt_eq = -res2.fun
        tol_eq = max(1e-6 * abs(opt_eq), 1e-6)
        row_eq = np.zeros(nv)
        for i, p in enumerate(providers):
            if higher[i]:
                row_eq[idx[f'red_{p}']] = -1.0
        c3 = np.zeros(nv)
        for k in cfg.weak_levers:
            for p in providers:
                c3[idx[f'{k}_{p}']] = 1.0
        res3 = linprog(c3, A_ub=np.vstack([A2, row_eq]),
                       b_ub=np.append(b2, -(opt_eq - tol_eq)),
                       bounds=bounds, method='highs')
        if res3.success:
            sol = res3.x

    rows = []
    for i, p in enumerate(providers):
        rec = {'provider_org_code': p,
               'baseline_over52_18mo': float(baseline[i]),
               'reduction': float(sol[idx[f'red_{p}']]),
               'higher_deprivation': bool(higher[i])}
        spend = 0.0
        for k in lever_keys:
            v = float(sol[idx[f'{k}_{p}']])
            rec[k] = v
            spend += n * cost[k] * v
        rec['cost'] = spend
        rows.append(rec)
    r = pd.DataFrame(rows)

    total_red = r['reduction'].sum()
    total_cost = r['cost'].sum()
    higher_red = r.loc[r.higher_deprivation, 'reduction'].sum()
    cap_delivered = {k: n * r[k].sum() for k in lever_keys}
    total_cap = sum(cap_delivered.values())
    weak = cfg.weak_levers
    weak_share = (sum(cap_delivered[k] for k in weak) / total_cap) if total_cap > 0 else 0.0
    spend_by = {k: n * cost[k] * r[k].sum() for k in lever_keys}
    tot_spend = sum(spend_by.values())

    out = {
        'feasible': True,
        'total_baseline': float(baseline.sum()),
        'breaches_cleared': float(total_red),
        'breaches_cleared_higher_deprivation': float(higher_red),
        'total_cost': float(total_cost),
        'pct_of_baseline_cleared': float(total_red / baseline.sum()) if baseline.sum() else 0.0,
        'breaches_per_million': float(total_red / (total_cost / 1e6)) if total_cost > 0 else 0.0,
        'delivery_risk_exposure': float(weak_share),
        'unit_costs': {k: cost[k] for k in lever_keys},
        'allocation': r.to_dict(orient='records'),
    }
    for k in lever_keys:
        out[f'spend_share_{k}'] = (spend_by[k] / tot_spend) if tot_spend > 0 else 0.0
    return out


# ---------------------------------------------------------------------------
# Scenario construction
# ---------------------------------------------------------------------------
def driver_range(cfg, data, d):
    if d['range_from'] == 'forecast_interval':
        return data['demand_low'], data['demand_high']
    return float(d['low']), float(d['high'])


def impact_matrix(cfg, data, anchor=None, label='base'):
    """Stage 5 impact axis, computed rather than judged."""
    base = {**base_params(cfg), **(anchor or {})}
    ref = solve(cfg, data, base)['breaches_cleared']
    rows = []
    for d in cfg['driving_forces']:
        lo_v, hi_v = driver_range(cfg, data, d)
        lo = solve(cfg, data, {**base, d['key']: lo_v})['breaches_cleared']
        hi = solve(cfg, data, {**base, d['key']: hi_v})['breaches_cleared']
        grade = cfg.grade_of(d['key'])
        rows.append({
            'anchor': label, 'cluster': d['cluster'], 'key': d['key'],
            'pestel': d.get('pestel', ''), 'label': d.get('label', ''),
            'low_value': lo_v, 'high_value': hi_v,
            'low_label': d.get('low_label', ''), 'high_label': d.get('high_label', ''),
            'reduction_at_low': lo, 'reduction_at_base': ref, 'reduction_at_high': hi,
            'swing_breaches': abs(hi - lo),
            'evidence_grade': grade,
            'evidence_basis': cfg.basis_of(d['key']),
        })
    m = pd.DataFrame(rows)
    mx = m['swing_breaches'].max()
    m['impact_norm'] = m['swing_breaches'] / mx if mx > 0 else 0.0
    m['uncertainty_norm'] = (m['evidence_grade'] - 1) / 3.0
    m['criticality'] = m['impact_norm'] * m['uncertainty_norm']
    return m.sort_values('criticality', ascending=False).reset_index(drop=True)


def tipping_points(cfg, data):
    """Where the optimal lever mix changes shape, by bisection on the mix."""
    base = base_params(cfg)
    keys = cfg.lever_keys

    def sig(p):
        r = solve(cfg, data, p)
        return tuple(round(r[f'spend_share_{k}'], 3) > 0.01 for k in keys)

    out = []
    for d in cfg['driving_forces']:
        lo, hi = driver_range(cfg, data, d)
        s_lo = sig({**base, d['key']: lo})
        if s_lo == sig({**base, d['key']: hi}):
            out.append({'cluster': d['cluster'], 'key': d['key'], 'tipping_point': None,
                        'base_value': base.get(d['key']),
                        'note': 'No change in the optimal lever mix anywhere in range.'})
            continue
        a, b = lo, hi
        for _ in range(60):
            mid = (a + b) / 2
            if sig({**base, d['key']: mid}) == s_lo:
                a = mid
            else:
                b = mid
        tp = (a + b) / 2
        out.append({'cluster': d['cluster'], 'key': d['key'], 'tipping_point': tp,
                    'base_value': base.get(d['key']),
                    'note': f'Optimal lever mix changes shape at {tp:.3f} '
                            f'(base assumption {base.get(d["key"])}).'})
    return pd.DataFrame(out)


def build_scenarios(cfg, data, matrix):
    fa, fb = matrix.iloc[0], matrix.iloc[1]
    dmap = {d['key']: d for d in cfg['driving_forces']}
    base = base_params(cfg)
    scen = []
    for a_side, b_side in itertools.product(['low', 'high'], repeat=2):
        p = dict(base)
        for f, side in ((fa, a_side), (fb, b_side)):
            lo, hi = driver_range(cfg, data, dmap[f['key']])
            p[f['key']] = lo if side == 'low' else hi
        scen.append({
            'code': f"{'A1' if a_side == 'low' else 'A2'}{'B1' if b_side == 'low' else 'B2'}",
            'factor_a': fa['cluster'],
            'factor_a_state': dmap[fa['key']].get(f'{a_side}_label', a_side),
            'factor_b': fb['cluster'],
            'factor_b_state': dmap[fb['key']].get(f'{b_side}_label', b_side),
            'params': p,
        })
    scen.append({'code': 'BASE', 'factor_a': fa['cluster'], 'factor_a_state': 'central',
                 'factor_b': fb['cluster'], 'factor_b_state': 'central',
                 'params': dict(base)})
    return scen, fa, fb


# ---------------------------------------------------------------------------
# Decision analysis
# ---------------------------------------------------------------------------
def canonicalise(cfg, grid):
    """One rounded basis, shared with any workbook built from this output."""
    g = grid.copy()
    prec = {o['key']: o['precision'] for o in cfg['objectives']}
    for key in ('breaches_cleared', 'breaches_cleared_higher_deprivation'):
        if key in g and key in prec:
            g[key] = g[key].round(prec[key])
    if 'delivery_risk_exposure' in prec:
        g['delivery_risk_exposure'] = g['delivery_risk_exposure'].round(
            prec['delivery_risk_exposure'])
    if 'breaches_per_million' in prec:
        g['breaches_per_million'] = np.where(
            g['total_cost'] > 0,
            (g['breaches_cleared'] / (g['total_cost'] / 1e6)).round(
                prec['breaches_per_million']), 0.0)
    g['equity_share'] = np.where(
        g['breaches_cleared'] > 0,
        g['breaches_cleared_higher_deprivation'] / g['breaches_cleared'], 0.0)
    return g


def sum_of_ranks(cfg, grid, weights=None):
    g = grid.copy()
    weights = weights or {o['key']: 1 for o in cfg['objectives']}
    for o in cfg['objectives']:
        g[f'rank_{o["key"]}'] = g[o['key']].rank(
            ascending=(o['direction'] == 'min'), method='min')
    g['sum_of_ranks'] = sum(g[f'rank_{o["key"]}'] * weights[o['key']]
                            for o in cfg['objectives'])
    return g


def detect_degeneracy(cfg, grid):
    keys = [o['key'] for o in cfg['objectives']]
    piv = grid.pivot_table(index='strategy', columns='scenario', values=keys)
    codes = list(piv.index)
    pairs = []
    for i in range(len(codes)):
        for j in range(i + 1, len(codes)):
            if np.allclose(np.nan_to_num(piv.loc[codes[i]].values),
                           np.nan_to_num(piv.loc[codes[j]].values),
                           rtol=1e-6, atol=1e-4):
                pairs.append((codes[i], codes[j]))
    return pairs


def run_grid(cfg, data, scenarios):
    rows, allocations = [], {}
    for sc in scenarios:
        for st in cfg['strategies']:
            r = solve(cfg, data, sc['params'], st.get('spec', {}))
            if not r['feasible']:
                rows.append({'scenario': sc['code'], 'strategy': st['code'],
                             'strategy_name': st['name'], 'feasible': False})
                continue
            row = {'scenario': sc['code'], 'strategy': st['code'],
                   'strategy_name': st['name'], 'feasible': True}
            for k in ('breaches_cleared', 'breaches_cleared_higher_deprivation',
                      'total_cost', 'breaches_per_million', 'delivery_risk_exposure',
                      'pct_of_baseline_cleared'):
                row[k] = r[k]
            for k in cfg.lever_keys:
                row[f'spend_share_{k}'] = r[f'spend_share_{k}']
            rows.append(row)
            allocations[f"{sc['code']}|{st['code']}"] = r['allocation']
    return canonicalise(cfg, pd.DataFrame(rows)), allocations
