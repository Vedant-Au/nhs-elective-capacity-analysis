"""
Step 2b: budget sensitivity sweep. The base £15m solve showed every lever
being filled cheapest-first (diagnostics @ £400/unit) with x1/x2 never
activating — worth checking whether that's a real structural feature of
the model (three levers with identical per-unit effect, different price
always fills cheapest-to-most-expensive in order) or an artifact of one
budget choice. Sweeping budget makes this explicit and gives the workbook
a real "what would it take to actually need outsourcing" answer instead
of asserting one.
"""
import json
import numpy as np
import pandas as pd
from scipy.optimize import linprog

with open('/tmp/solver_model_solution.json') as f:
    bundle = json.load(f)

df = pd.DataFrame(bundle['providers'])
n_months = bundle['meta']['n_months']
providers = df['provider_org_code'].tolist()
P = len(providers)
a = bundle['assumptions']
C1, C2, C3 = a['c1_inhouse'], a['c2_outsource'], a['c3_diagnostic']
target_share = a['equity_floor_share']
higher_mask = df['higher_deprivation'].values

def solve_for_budget(budget):
    var_names = [f"x1_{p}" for p in providers] + [f"x2_{p}" for p in providers] + \
                [f"x3_{p}" for p in providers] + [f"red_{p}" for p in providers]
    idx = {name: i for i, name in enumerate(var_names)}
    n_vars = 4 * P
    c = np.zeros(n_vars)
    for p in providers:
        c[idx[f"red_{p}"]] = -1.0
    A_ub, b_ub = [], []
    for p in providers:
        row = np.zeros(n_vars)
        row[idx[f"red_{p}"]] = 1.0
        row[idx[f"x1_{p}"]] = -n_months; row[idx[f"x2_{p}"]] = -n_months; row[idx[f"x3_{p}"]] = -n_months
        A_ub.append(row); b_ub.append(0.0)
    row = np.zeros(n_vars)
    for p in providers:
        row[idx[f"x1_{p}"]] = n_months * C1; row[idx[f"x2_{p}"]] = n_months * C2; row[idx[f"x3_{p}"]] = n_months * C3
    A_ub.append(row); b_ub.append(budget)
    row = np.zeros(n_vars)
    for p in providers:
        coef = target_share - (1.0 if df.loc[df.provider_org_code == p, 'higher_deprivation'].values[0] else 0.0)
        row[idx[f"red_{p}"]] = coef
    A_ub.append(row); b_ub.append(0.0)
    bounds = []
    for name in var_names:
        if name.startswith('x1_'):
            p = name[3:]; bounds.append((0, df.loc[df.provider_org_code == p, 'x1_cap'].values[0]))
        elif name.startswith('x2_'):
            p = name[3:]; bounds.append((0, df.loc[df.provider_org_code == p, 'x2_cap'].values[0]))
        elif name.startswith('x3_'):
            p = name[3:]; bounds.append((0, df.loc[df.provider_org_code == p, 'x3_cap'].values[0]))
        else:
            p = name[4:]; bounds.append((0, df.loc[df.provider_org_code == p, 'baseline_over52_total'].values[0]))
    res = linprog(c, A_ub=np.array(A_ub), b_ub=np.array(b_ub), bounds=bounds, method='highs')
    if not res.success:
        return None
    sol = res.x
    tot_x1 = sum(sol[idx[f"x1_{p}"]] for p in providers) * n_months
    tot_x2 = sum(sol[idx[f"x2_{p}"]] for p in providers) * n_months
    tot_x3 = sum(sol[idx[f"x3_{p}"]] for p in providers) * n_months
    tot_red = sum(sol[idx[f"red_{p}"]] for p in providers)
    tot_cost = n_months * sum(C1*sol[idx[f"x1_{p}"]] + C2*sol[idx[f"x2_{p}"]] + C3*sol[idx[f"x3_{p}"]] for p in providers)
    return {'budget': budget, 'total_inhouse_units': tot_x1, 'total_outsource_units': tot_x2,
            'total_diagnostic_units': tot_x3, 'total_reduction': tot_red, 'total_cost': tot_cost,
            'pct_reduction': tot_red / df['baseline_over52_total'].sum()}

budgets = [2_000_000, 5_000_000, 10_000_000, 15_000_000, 25_000_000, 40_000_000, 60_000_000, 90_000_000, 130_000_000]
rows = [solve_for_budget(b) for b in budgets]
sens_df = pd.DataFrame([r for r in rows if r])
print(sens_df.to_string())

sens_df.to_json('/tmp/budget_sensitivity.json', orient='records', indent=2)
print("\nSaved /tmp/budget_sensitivity.json")

# Find the budget where x1/x2 first activate
first_x1 = sens_df[sens_df['total_inhouse_units'] > 1]['budget'].min()
first_x2 = sens_df[sens_df['total_outsource_units'] > 1]['budget'].min()
print(f"\nIn-house lever (x1) first activates around budget: {first_x1}")
print(f"Outsourcing lever (x2) first activates around budget: {first_x2}")
