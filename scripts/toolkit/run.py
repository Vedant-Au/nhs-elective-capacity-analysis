"""
Healthcare Capacity Optimisation Toolkit — command-line runner.

    python3 scripts/toolkit/run.py --config config/cheshire_merseyside.yaml

Runs the full sequence for one engagement: extract from the warehouse, build the
impact/uncertainty matrix, locate tipping points, frame scenarios, evaluate every
strategy against every scenario, rank, test the ranking against reweighting, and
write the outputs.
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from toolkit import config as cfgmod           # noqa: E402
from toolkit import extract as extractmod      # noqa: E402
from toolkit import engine                     # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', required=True)
    ap.add_argument('--out', default='/tmp/toolkit_out')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    v = not args.quiet

    cfg = cfgmod.load(args.config)
    eng = cfg['engagement']
    print(f"\n{'=' * 78}\n{eng['name']} — {eng['domain']}\n"
          f"{eng['horizon_months']}-month horizon\n{'=' * 78}")

    print('\n[1/6] Extracting from warehouse')
    data = extractmod.extract(cfg, verbose=v)

    print('\n[2/6] Impact / uncertainty matrix')
    matrix = engine.impact_matrix(cfg, data)
    if v:
        print(matrix[['cluster', 'swing_breaches', 'evidence_grade',
                      'criticality']].to_string(index=False))

    print('\n[3/6] Tipping points')
    tips = engine.tipping_points(cfg, data)
    live = tips[tips.tipping_point.notna()]
    if live.empty:
        print('  none inside any driving force\'s plausible range')
    else:
        for _, t in live.iterrows():
            print(f"  {t['cluster']}: {t['note']}")

    print('\n[4/6] Anchor-stability check')
    crit = matrix.iloc[0]
    alt_key = matrix.iloc[1]['key']
    lo, hi = engine.driver_range(
        cfg, data, next(d for d in cfg['driving_forces'] if d['key'] == alt_key))
    alt = engine.impact_matrix(cfg, data, anchor={alt_key: hi}, label='alt')
    stab = matrix[['cluster', 'swing_breaches']].merge(
        alt[['cluster', 'swing_breaches']], on='cluster', suffixes=('_base', '_alt'))
    stab['state_dependent'] = (
        ((stab.swing_breaches_base < 1) & (stab.swing_breaches_alt >= 1)) |
        ((stab.swing_breaches_base >= 1) & (stab.swing_breaches_alt < 1)))
    flipped = stab.loc[stab.state_dependent, 'cluster'].tolist()
    print('  state-dependent drivers: ' + (', '.join(flipped) if flipped else 'none'))

    print('\n[5/6] Strategy x scenario grid')
    scenarios, fa, fb = engine.build_scenarios(cfg, data, matrix)
    print(f"  Factor A: {fa['cluster']} (criticality {fa['criticality']:.3f})")
    print(f"  Factor B: {fb['cluster']} (criticality {fb['criticality']:.3f})")
    grid, allocations = engine.run_grid(cfg, data, scenarios)
    print(f"  {len(grid)} solves across {len(scenarios)} scenarios "
          f"x {len(cfg['strategies'])} strategies")

    print('\n[6/6] Decision analysis')
    ranked = engine.sum_of_ranks(cfg, grid)
    by_strategy = (ranked.groupby(['strategy', 'strategy_name'])['sum_of_ranks']
                   .sum().reset_index().sort_values('sum_of_ranks'))
    print(by_strategy.to_string(index=False))

    weight_tests = {}
    firsts = set()
    for o in cfg['objectives']:
        for mult in (2, 3):
            w = {x['key']: (mult if x['key'] == o['key'] else 1)
                 for x in cfg['objectives']}
            order = (engine.sum_of_ranks(cfg, grid, w)
                     .groupby('strategy')['sum_of_ranks'].sum()
                     .sort_values().index.tolist())
            weight_tests[f"{o['key']}_x{mult}"] = order
            firsts.add(order[0])

    reg = grid.pivot(index='strategy', columns='scenario', values='breaches_cleared')
    regret = reg.max(axis=0) - reg
    max_regret = regret.max(axis=1).sort_values()

    dups = engine.detect_degeneracy(cfg, grid)
    winner = by_strategy.iloc[0]
    stable = (len(firsts) == 1 and winner['strategy'] in firsts)

    print(f"\n  recommended: {winner['strategy']} — {winner['strategy_name']}")
    print(f"  weight-stable across all {len(weight_tests)} tests: "
          f"{'yes' if stable else 'NO — ' + ', '.join(sorted(firsts))}")
    print(f"  worst-case regret: {max_regret[winner['strategy']]:,.0f}")
    if dups:
        print('  degenerate strategy pairs: ' +
              ', '.join(f'{a}={b}' for a, b in dups))

    bundle = {
        'engagement': eng,
        'factor_a': fa['cluster'], 'factor_b': fb['cluster'],
        'matrix': matrix.to_dict(orient='records'),
        'tipping_points': tips.to_dict(orient='records'),
        'stability_check': stab.to_dict(orient='records'),
        'scenarios': scenarios,
        'grid': grid.to_dict(orient='records'),
        'ranked': ranked.to_dict(orient='records'),
        'by_strategy': by_strategy.to_dict(orient='records'),
        'weight_tests': weight_tests,
        'weight_stable': bool(stable),
        'regret': regret.to_dict(),
        'max_regret': max_regret.to_dict(),
        'degenerate_pairs': dups,
        'recommended': winner['strategy'],
        'allocations': allocations,
    }
    stem = Path(args.config).stem
    with open(out / f'{stem}_results.json', 'w') as f:
        json.dump(bundle, f, indent=2, default=str)
    matrix.to_csv(out / f'{stem}_driving_forces.csv', index=False)
    grid.to_csv(out / f'{stem}_grid.csv', index=False)
    ranked.to_csv(out / f'{stem}_ranks.csv', index=False)
    regret.to_csv(out / f'{stem}_regret.csv')
    print(f"\nWritten to {out}/{stem}_*\n")
    return bundle


if __name__ == '__main__':
    main()
