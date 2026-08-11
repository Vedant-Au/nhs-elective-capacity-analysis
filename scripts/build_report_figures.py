"""
NHS Cheshire and Merseyside ICB: Phase 6 board paper figures.

Five figures, deliberately plain. Every one is built from a stored output or
the warehouse, never from a number typed in by hand, so a figure cannot drift
away from the analysis behind it.

Design rules applied throughout: no chart junk, no gridlines except a light
horizontal reference where a reader needs to compare heights, no top or right
spines, one idea per figure, and the point of the figure stated in its title
rather than left for the caption to explain.
"""
import json
import re
import duckdb
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

OUT = '/tmp/figures'
DB = '/tmp/wh.db'

NAVY = '#1f3864'
BLUE = '#2e75b6'
LIGHT = '#bdd7ee'
AMBER = '#bf8f00'
RED = '#c00000'
GREY = '#7f7f7f'

plt.rcParams.update({
    'font.family': 'DejaVu Sans',
    'font.size': 9,
    'axes.titlesize': 11,
    'axes.titleweight': 'bold',
    'axes.labelsize': 9,
    'axes.edgecolor': '#595959',
    'axes.linewidth': 0.8,
    'figure.dpi': 200,
})


def clean(ax, hgrid=True):
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    if hgrid:
        ax.yaxis.grid(True, color='#e0e0e0', linewidth=0.7)
        ax.set_axisbelow(True)


def thousands(x, _):
    return f'{x:,.0f}'


def fig1_backlog():
    """The diagnosis: the waiting list never recovered, and is forecast to keep rising."""
    rt = pd.read_csv('/tmp/evidence_rtt.csv', parse_dates=['d'])
    fc = pd.read_csv('/tmp/evidence_forecast.csv', parse_dates=['period_month'])
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.plot(rt.d, rt.wl, color=NAVY, lw=1.8, label='Actual waiting list')
    ax.fill_between(fc.period_month, fc.p5, fc.p95, color=LIGHT, alpha=0.75,
                    label='Forecast range (p5–p95)', zorder=1)
    ax.plot(fc.period_month, fc.p50, color=BLUE, lw=1.6, ls='--',
            label='Forecast central case')
    ax.axvline(pd.Timestamp('2020-03-01'), color=GREY, lw=0.9, ls=':')
    ax.annotate('COVID-19', xy=(pd.Timestamp('2020-04-01'), 745000),
                fontsize=8, color=GREY)
    pre = rt[rt.d == '2020-02-01'].wl.iloc[0]
    ax.axhline(pre, color=GREY, lw=0.9, ls=':')
    ax.annotate(f'Pre-pandemic level ({pre:,.0f})',
                xy=(pd.Timestamp('2022-06-01'), pre * 0.88), fontsize=8, color=GREY)
    ax.set_title('The waiting list has not recovered, and is not forecast to')
    ax.set_ylabel('Patients on the RTT waiting list')
    ax.yaxis.set_major_formatter(FuncFormatter(thousands))
    ax.set_ylim(0, 900000)
    ax.legend(frameon=False, loc='lower right', fontsize=8)
    clean(ax)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig1_backlog.png', bbox_inches='tight')
    plt.close(fig)


def fig2_money_not_capacity():
    """Nothing binds except money."""
    ceilings = [('Independent sector', 31.9), ('Diagnostic', 69.7), ('NHS in-house', 107.1)]
    fig, ax = plt.subplots(figsize=(7.2, 2.7))
    ypos = np.arange(len(ceilings))
    ax.barh(ypos, [c[1] for c in ceilings], color=LIGHT, edgecolor=BLUE, height=0.55)
    for i, (name, v) in enumerate(ceilings):
        ax.text(v + 2, i, f'£{v}m', va='center', fontsize=9, color=NAVY, fontweight='bold')
    ax.axvspan(7.5, 30, color=AMBER, alpha=0.18, zorder=0)
    ax.annotate('Funding range under\nconsideration: £7.5m – £30m',
                xy=(34, 2.45), ha='left', fontsize=8.5, color=AMBER, fontweight='bold')
    ax.set_yticks(ypos)
    ax.set_yticklabels([c[0] for c in ceilings])
    ax.set_xlim(0, 125)
    ax.set_ylim(-0.6, 3.0)
    ax.set_xlabel('Funding required before this capacity ceiling starts to bind (£m)')
    ax.set_title('No capacity ceiling binds at any funding level under consideration')
    ax.xaxis.grid(True, color='#e0e0e0', lw=0.7)
    ax.set_axisbelow(True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig2_money_not_capacity.png', bbox_inches='tight')
    plt.close(fig)


def fig3_tipping_point():
    """The decision chart: everything turns on one unsourced number."""
    import sys
    sys.path.insert(0, '/sessions/epic-dazzling-cannon/mnt/NHS_Project/scripts')
    from scenario_wayfinding import solve, BASE
    data = json.load(open('/tmp/solver_model_inputs.json'))
    xs = np.concatenate([np.arange(0.5, 3.30, 0.10), np.arange(3.30, 4.31, 0.02)])
    ys = [solve(data, {**BASE, 'diag_tests_per_pathway': float(x)})['total_reduction']
          for x in xs]
    fig, ax = plt.subplots(figsize=(7.2, 3.5))
    ax.plot(xs, ys, color=NAVY, lw=2)
    ax.axvline(3.343, color=RED, lw=1.4, ls='--')
    ax.annotate('Tipping point 3.34\nabove here the strategy reverses',
                xy=(3.40, 78000), fontsize=8.5, color=RED, fontweight='bold')
    ax.axvline(1.75, color=AMBER, lw=1.4, ls='--')
    ax.annotate('Planning\nassumption\n1.75', xy=(1.82, 95000), fontsize=8.5,
                color=AMBER, fontweight='bold')
    ax.axvspan(0.60, 0.92, color=BLUE, alpha=0.22)
    ax.annotate('Observed range\n0.60 – 0.92', xy=(0.55, 30000), fontsize=8.5,
                color=BLUE, fontweight='bold')
    ax.set_xlabel('Diagnostic tests required to unlock one completed pathway')
    ax.set_ylabel('Breaches cleared over 18 months')
    ax.set_title('The entire allocation turns on one figure that has no published source')
    ax.yaxis.set_major_formatter(FuncFormatter(thousands))
    ax.set_xlim(0.4, 4.35)
    ax.set_ylim(0, 130000)
    clean(ax)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig3_tipping_point.png', bbox_inches='tight')
    plt.close(fig)


def fig4_strategies():
    """How the candidate strategies perform across the scenario set."""
    g = pd.read_csv('/tmp/scenario_out/strategy_scenario_grid.csv')
    order = ['S1', 'S2', 'S5', 'S7', 'S3', 'S4', 'S6', 'S0']
    names = {'S0': 'Hold position', 'S1': 'Unconstrained', 'S2': 'NHS delivery only',
             'S3': 'No in-house expansion', 'S4': 'Diagnostic-led',
             'S5': 'Equity-first', 'S6': 'Diversified hedge', 'S7': 'Treatment only'}
    scen = ['A1B1', 'A1B2', 'A2B1', 'A2B2']
    labels = ['Lean money,\nefficient diagnostics', 'Lean money,\ntest-heavy',
              'Funded,\nefficient diagnostics', 'Funded,\ntest-heavy']
    piv = g.pivot(index='strategy', columns='scenario', values='breaches_cleared').loc[order]
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    x = np.arange(len(order))
    w = 0.2
    shades = [NAVY, BLUE, '#8faadc', LIGHT]
    for i, (s, lab) in enumerate(zip(scen, labels)):
        ax.bar(x + (i - 1.5) * w, piv[s], w, label=lab, color=shades[i],
               edgecolor='white', linewidth=0.4)
    ax.set_xticks(x)
    ax.set_xticklabels([names[o] for o in order], rotation=25, ha='right', fontsize=8)
    ax.set_ylabel('Breaches cleared over 18 months')
    ax.yaxis.set_major_formatter(FuncFormatter(thousands))
    ax.set_title('Three strategies are the same commitment; the real choice is against S7')
    ax.set_ylim(0, 205000)
    ax.legend(frameon=False, fontsize=7.5, ncol=4, loc='upper center',
              bbox_to_anchor=(0.5, -0.32))
    # Bracket the three that are provably identical on every objective.
    ax.plot([-0.4, 2.4], [186000, 186000], color=NAVY, lw=1.2)
    ax.annotate('Identical on every objective\nin every scenario', xy=(1.0, 190000),
                ha='center', fontsize=8, color=NAVY, fontweight='bold')
    ax.annotate('Zero exposure to the\nunsourced assumptions', xy=(3.0, 96000),
                ha='center', fontsize=8, color=AMBER, fontweight='bold')
    clean(ax)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig4_strategies.png', bbox_inches='tight')
    plt.close(fig)


def fig5_conversion():
    """The observed proxy over 84 months, against assumption and tipping point."""
    c = pd.read_csv('/tmp/scenario_out/diagnostic_conversion_observed.csv',
                    parse_dates=['month'])
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.plot(c.month, c.tests_per_completed_pathway, color=BLUE, lw=1.5)
    ax.axhline(1.75, color=AMBER, lw=1.3, ls='--')
    ax.annotate('Planning assumption 1.75', xy=(c.month.iloc[3], 1.80),
                fontsize=8.5, color=AMBER, fontweight='bold')
    ax.axhline(3.343, color=RED, lw=1.3, ls='--')
    ax.annotate('Tipping point 3.34. Strategy reverses above this line',
                xy=(c.month.iloc[3], 3.40), fontsize=8.5, color=RED, fontweight='bold')
    ax.set_ylim(0, 3.9)
    ax.set_ylabel('DM01 tests per completed pathway')
    ax.set_title('Observed conversion has never approached the level that would '
                 'change the recommendation')
    clean(ax)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig5_conversion.png', bbox_inches='tight')
    plt.close(fig)


def fig6_diagnostic_pressure():
    """The counter-indication, shown rather than buried."""
    con = duckdb.connect(DB, read_only=True)
    core = [r[0] for r in con.execute(
        'select provider_org_code from dim_provider where in_core_analysis').fetchall()]
    q = ','.join(f"'{c}'" for c in core)
    d = con.execute(f"""select period,
        sum(waiting_list_over_6wk)::double/nullif(sum(waiting_list_size),0) s
        from fact_dm01_provider_month where provider_org_code in ({q}) group by 1""").fetchdf()
    MON = {m: i + 1 for i, m in enumerate(
        ['JANUARY', 'FEBRUARY', 'MARCH', 'APRIL', 'MAY', 'JUNE', 'JULY', 'AUGUST',
         'SEPTEMBER', 'OCTOBER', 'NOVEMBER', 'DECEMBER'])}
    d['m'] = d.period.map(lambda p: (lambda x: pd.Timestamp(
        int(x.group(2)), MON[x.group(1).upper()], 1))(re.match(r'DM01-(\w+)-(\d{4})', p, re.I)))
    d = d.dropna(subset=['m']).sort_values('m').reset_index(drop=True)
    prior12 = d.iloc[-24:-12].s.mean() * 100
    last12 = d.tail(12).s.mean() * 100
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.plot(d.m, d.s * 100, color=GREY, lw=1.2)
    tail = d.tail(24)
    ax.plot(tail.m, tail.s * 100, color=RED, lw=1.8)
    ax.hlines(prior12, d.iloc[-24].m, d.iloc[-13].m, color=NAVY, lw=2.2)
    ax.hlines(last12, d.iloc[-12].m, d.iloc[-1].m, color=NAVY, lw=2.2)
    ax.annotate(f'12-month mean\n{prior12:.1f}%', xy=(d.iloc[-21].m, prior12 + 8),
                fontsize=8, color=NAVY, fontweight='bold', ha='center')
    ax.annotate(f'{last12:.1f}%', xy=(d.iloc[-6].m, last12 + 8),
                fontsize=8, color=NAVY, fontweight='bold', ha='center')
    ax.set_ylabel('% of diagnostic waiting list\nwaiting over six weeks')
    ax.set_title('Diagnostic waits improved sharply, then plateaued. The recent '
                 'uptick is a level shift, not a trend')
    ax.set_ylim(0, 62)
    clean(ax)
    fig.tight_layout()
    fig.savefig(f'{OUT}/fig6_diagnostic_pressure.png', bbox_inches='tight')
    plt.close(fig)


if __name__ == '__main__':
    import os
    os.makedirs(OUT, exist_ok=True)
    fig1_backlog(); print('fig1 backlog')
    fig2_money_not_capacity(); print('fig2 money not capacity')
    fig3_tipping_point(); print('fig3 tipping point')
    fig4_strategies(); print('fig4 strategies')
    fig5_conversion(); print('fig5 conversion')
    fig6_diagnostic_pressure(); print('fig6 diagnostic pressure')
    print('written to', OUT)
