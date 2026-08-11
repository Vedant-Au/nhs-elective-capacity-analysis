"""
NHS Cheshire and Merseyside ICB — Elective Capacity Scenario and Strategy Model
Phase 5, part 2: early-warning indicators.

PURPOSE
-------
A scenario set that is never revisited is a document, not a decision aid.
This script derives the observable indicators that would tell the ICB which
scenario it is actually moving into, restricted — deliberately — to
quantities the warehouse already holds and can refresh monthly. An indicator
nobody can measure is not an indicator.

Method follows Cairns and Wright (2018) Ch. 8, which takes the earliest-in-
time driving force in each causal chain and designates it a flag. Where no
warehouse quantity can serve as a flag, that is recorded as an explicit gap
rather than filled with a plausible-sounding proxy.

The framing is Sminia's (2026) distinction between scenario thinking and
scenario doing: the flags are what convert a set of pen-pictures into
something the organisation participates in month by month.

DIAGNOSTIC CONVERSION — TRIANGULATION OF THE MODEL'S LAST UNSOURCED FIGURE
--------------------------------------------------------------------------
The Phase 3 cost model rests on one figure with no published source: 1.75
diagnostic tests per unlocked RTT pathway. It sets the unit cost of the
diagnostic lever, and the scenario analysis shows the whole recommendation
turns on it.

This script computes an observable proxy from the warehouse: total DM01
diagnostic activity divided by total completed RTT pathways, across the 12
core trusts. The comparison is like-for-like in the sense that matters —
the diagnostic unit cost c3 is itself built from the DM01 test mix, so the
DM01 basket is exactly the basket the parameter is meant to price.

Two biases run in OPPOSITE directions and neither is quantified here:
  - DM01 covers 15 test types (imaging, endoscopy, physiological
    measurement) and no pathology at all, so it understates total
    diagnostic input per pathway.
  - Not every DM01 test sits on an RTT pathway — direct-access and
    GP-requested tests are included — so it overstates the tests
    attributable to RTT completions.
A third and more fundamental caveat: the model parameter is a MARGINAL
ratio (tests needed to unlock one ADDITIONAL pathway) while this proxy is
an AVERAGE across all activity. These are not the same quantity and the
proxy cannot settle the parameter.

What it can do is bound the argument, and that is how it is reported.
"""
import re
import json
import duckdb
import numpy as np
import pandas as pd
from scipy import stats

DB = '/tmp/wh.db'                       # see conventions: never open the synced copy directly
SCENARIO_JSON = '/tmp/scenario_wayfinding.json'
OUT_DIR = '/tmp/scenario_out'

MONTHS = {'JANUARY': 1, 'FEBRUARY': 2, 'MARCH': 3, 'APRIL': 4, 'MAY': 5, 'JUNE': 6,
          'JULY': 7, 'AUGUST': 8, 'SEPTEMBER': 9, 'OCTOBER': 10, 'NOVEMBER': 11,
          'DECEMBER': 12}

# Indifference point between the diagnostic and treatment levers, computed in
# scenario_wayfinding.tipping_points(). Above this the optimal strategy changes
# shape entirely, so it is the threshold the flag is set against.
DIAGNOSTIC_TIPPING_POINT = 3.343
DIAGNOSTIC_ASSUMPTION = 1.75


def parse_period(p, prefix):
    m = re.match(prefix + r'-(\w+)-(\d{4})', p, re.IGNORECASE)
    if not m:
        return pd.NaT
    return pd.Timestamp(year=int(m.group(2)), month=MONTHS[m.group(1).upper()], day=1)


def main():
    import os
    os.makedirs(OUT_DIR, exist_ok=True)
    con = duckdb.connect(DB, read_only=True)
    core = [r[0] for r in con.execute(
        'select provider_org_code from dim_provider where in_core_analysis').fetchall()]
    inlist = ','.join(f"'{c}'" for c in core)

    # ---- Indicator 1: diagnostic conversion proxy ------------------------
    dm = con.execute(f"""
        select period, sum(total_activity) as tests
        from fact_dm01_provider_month
        where provider_org_code in ({inlist}) group by 1""").fetchdf()
    rt = con.execute(f"""
        select period, sum(completed_pathways_total) as completions,
               sum(waiting_list_over_52wk) as over52, sum(waiting_list_size) as wl
        from fact_rtt_provider_specialty_month
        where provider_org_code in ({inlist}) group by 1""").fetchdf()
    dm['month'] = dm.period.map(lambda p: parse_period(p, 'DM01'))
    rt['month'] = rt.period.map(lambda p: parse_period(p, 'RTT'))
    conv = (dm.dropna(subset=['month']).merge(rt.dropna(subset=['month']), on='month')
            .sort_values('month'))
    conv['tests_per_completed_pathway'] = conv.tests / conv.completions
    t12 = conv.tail(12)
    conv_now = float(t12.tests.sum() / t12.completions.sum())
    conv_full = float(conv.tests.sum() / conv.completions.sum())

    # ---- Indicator 2: diagnostic waiting-list pressure -------------------
    dm6 = con.execute(f"""
        select period, sum(waiting_list_over_6wk)::double / nullif(sum(waiting_list_size),0)
               as over6_share
        from fact_dm01_provider_month
        where provider_org_code in ({inlist}) group by 1""").fetchdf()
    dm6['month'] = dm6.period.map(lambda p: parse_period(p, 'DM01'))
    dm6 = dm6.dropna(subset=['month']).sort_values('month').reset_index(drop=True)
    # Reported as 12-month means with a trend test, NOT as a point-to-point
    # comparison. An earlier draft quoted "6.2% rising to 9.9%" by picking the
    # value 12 months ago against the latest value. On a series with a standard
    # deviation of 2.0 points that is endpoint selection, not a finding: the
    # full window trends significantly DOWNWARD (-0.14 points per month,
    # p=0.009) and the last 24 months carry no significant trend at all
    # (p=0.21). What survives the test is a level shift between the two most
    # recent 12-month means, and that is what is quoted.
    dm6_last12 = float(dm6.over6_share.tail(12).mean())
    dm6_prior12 = float(dm6.over6_share.iloc[-24:-12].mean())
    _x = np.arange(len(dm6.tail(24)))
    _y = dm6.over6_share.tail(24).values
    _slope, _, _, _p24, _ = stats.linregress(_x, _y)
    _xf = np.arange(len(dm6))
    _slope_full, _, _, _pfull, _ = stats.linregress(_xf, dm6.over6_share.values)

    # ---- Indicator 3: backlog trajectory versus forecast band ------------
    fc = con.execute("""
        select period_month, sum(mc_p5) p5, sum(mc_p50) p50, sum(mc_p95) p95
        from fact_rtt_waitinglist_forecast_provider_month
        where is_forecast group by 1 order by 1 limit 1""").fetchdf()
    rt_sorted = rt.dropna(subset=['month']).sort_values('month')
    wl_now = float(rt_sorted.wl.iloc[-1])
    over52_now = float(rt_sorted.over52.iloc[-1])
    latest_month = rt_sorted.month.iloc[-1]

    # ---- Indicator 4: independent-sector activity ------------------------
    is_codes = [r[0] for r in con.execute("""
        select provider_org_code from dim_provider
        where coalesce(in_core_analysis,false)=false
          and provider_type ilike '%independent%'""").fetchall()]
    is_now = np.nan
    if is_codes:
        q = ','.join(f"'{c}'" for c in is_codes)
        isdf = con.execute(f"""
            select period, sum(completed_pathways_total) c
            from fact_rtt_provider_specialty_month
            where provider_org_code in ({q}) group by 1""").fetchdf()
        isdf['month'] = isdf.period.map(lambda p: parse_period(p, 'RTT'))
        isdf = isdf.dropna(subset=['month']).sort_values('month')
        if len(isdf) >= 6:
            is_now = float(isdf.c.tail(6).mean())

    flags = [
        dict(
            flag='F1', factor='Funding settlement (Factor A)',
            indicator='Confirmed elective recovery envelope for the ICB, 18 months to Sep-2027',
            source='NOT IN WAREHOUSE — NHS England allocation and planning guidance; ICB finance ledger',
            current_value='not observable from warehouse',
            trigger='Envelope confirmed below £10m, or above £25m',
            action='Re-run the grid at the confirmed envelope. This is the highest-impact '
                   'uncertainty in the model and the only one with no internal data source, '
                   'so it must be tracked through the finance route rather than the analytics one.',
            status='GAP — external monitoring required'),
        dict(
            flag='F2', factor='Diagnostic conversion (Factor B)',
            indicator='DM01 diagnostic tests per completed RTT pathway, 12 core trusts, monthly',
            source='fact_dm01_provider_month.total_activity / '
                   'fact_rtt_provider_specialty_month.completed_pathways_total',
            current_value=f'{conv_now:.2f} (trailing 12 months); {conv_full:.2f} across full window',
            trigger=f'Sustained rise above 2.00 for three consecutive months triggers review; '
                    f'{DIAGNOSTIC_TIPPING_POINT:.2f} is the point at which the optimal strategy '
                    f'changes shape entirely',
            action='Above the tipping point the diagnostic lever is no longer the cheapest route '
                   'to a cleared pathway and the programme should shift to treatment capacity. '
                   'The observed proxy currently sits well below both thresholds.',
            status='ACTIVE — measurable monthly'),
        dict(
            flag='F3', factor='Diagnostic capacity headroom',
            indicator='Share of the DM01 diagnostic waiting list waiting over six weeks',
            source='fact_dm01_provider_month.waiting_list_over_6wk / waiting_list_size',
            current_value=f'{dm6_last12:.1%} mean over the last 12 months, against '
                          f'{dm6_prior12:.1%} over the preceding 12',
            trigger='A statistically significant upward trend sustained over two quarters, '
                    'or the 12-month mean exceeding 15%',
            action='The model assumes 10% headroom for additional diagnostic activity, so a '
                   'deteriorating diagnostic waiting list would undercut the recommended '
                   'strategy at source. Read the level, not the last data point: over the full '
                   f'window the series trends significantly DOWNWARD ({_slope_full:+.3f} '
                   f'points per month, p={_pfull:.3f}), and over the last 24 months there is no '
                   f'significant trend either way (p={_p24:.2f}) on a series with a standard '
                   'deviation of about 2 points. The 12-month mean has stepped up by roughly 2 '
                   'points, which is worth watching but is not evidence of deterioration.',
            status='ACTIVE — measurable monthly; currently a level shift, not a trend'),
        dict(
            flag='F4', factor='Backlog trajectory',
            indicator='ICB total RTT waiting list against the Monte Carlo forecast band',
            source='fact_rtt_provider_specialty_month vs fact_rtt_waitinglist_forecast_provider_month',
            current_value=f'{wl_now:,.0f} at {latest_month:%b-%Y}; '
                          f'over-52-week waits {over52_now:,.0f}',
            trigger='Actual outside the p5–p95 band for two consecutive months',
            action='Recalibrate the forecast. Note that backlog size has no effect on the '
                   'optimal allocation at any funding level in scope — the budget clears far '
                   'less than the backlog either way — so this flag governs the credibility of '
                   'the stated ambition, not the choice of strategy.',
            status='ACTIVE — monitoring only, does not change the strategy'),
        dict(
            flag='F5', factor='Independent-sector capacity',
            indicator='Independent-sector NHS-funded completed pathways, trailing six-month mean',
            source='fact_rtt_provider_specialty_month, independent-sector providers',
            current_value=(f'{is_now:,.0f} per month' if not np.isnan(is_now)
                           else 'not separately identified in the warehouse'),
            trigger='Dormant below a £31.9m envelope',
            action='The independent-sector capacity ceiling does not bind until the envelope '
                   'exceeds £31.9m, above the top of the scenario range. Monitoring is not '
                   'warranted at current funding levels and is recorded here so that the '
                   'omission is deliberate rather than overlooked.',
            status='DORMANT — outside the range in which it can bind'),
        dict(
            flag='F6', factor='NHS in-house capacity',
            indicator='General and acute bed headroom (KH03) and consultant FTE',
            source='fact_kh03_provider_quarter, fact_workforce_provider_year',
            current_value='tracked in the Phase 3 model inputs',
            trigger='Dormant below a £107.1m envelope',
            action='As F5. The in-house capacity ceiling is an order of magnitude beyond any '
                   'funding level under consideration and cannot bind.',
            status='DORMANT — outside the range in which it can bind'),
    ]

    flags_df = pd.DataFrame(flags)
    flags_df.to_csv(f'{OUT_DIR}/early_warning_flags.csv', index=False)
    conv[['month', 'tests', 'completions', 'tests_per_completed_pathway']].to_csv(
        f'{OUT_DIR}/diagnostic_conversion_observed.csv', index=False)

    triangulation = {
        'model_assumption': DIAGNOSTIC_ASSUMPTION,
        'tipping_point': DIAGNOSTIC_TIPPING_POINT,
        'observed_trailing_12m': conv_now,
        'observed_full_window': conv_full,
        'observed_min': float(conv.tests_per_completed_pathway.min()),
        'observed_max': float(conv.tests_per_completed_pathway.max()),
        'n_months_observed': int(len(conv)),
        'caveats': [
            'DM01 covers 15 test types and no pathology, so it understates total '
            'diagnostic input per pathway.',
            'Not every DM01 test sits on an RTT pathway, so it overstates the tests '
            'attributable to RTT completions.',
            'The model parameter is marginal (tests to unlock one additional pathway); '
            'this proxy is an average across all activity. They are different quantities.',
            'The two measurement biases run in opposite directions and neither is '
            'quantified, so no net correction is applied or implied.',
        ],
        'conclusion':
            'The proxy does not settle the parameter and is not presented as doing so. '
            'It does establish that the observed DM01-to-completion ratio has never in '
            f'{len(conv)} months of data approached the {DIAGNOSTIC_TIPPING_POINT:.2f} '
            'level at which the recommended strategy would change. The direction of the '
            'recommendation is therefore better evidenced than the magnitude of the '
            'benefit it produces.',
    }
    with open(f'{OUT_DIR}/diagnostic_triangulation.json', 'w') as f:
        json.dump(triangulation, f, indent=2)

    print('EARLY WARNING FLAGS')
    print(flags_df[['flag', 'factor', 'current_value', 'status']].to_string(index=False))
    print('\nDIAGNOSTIC CONVERSION TRIANGULATION')
    for k, v in triangulation.items():
        if k not in ('caveats',):
            print(f'  {k}: {v}')
    print(f'\nWritten to {OUT_DIR}')


if __name__ == '__main__':
    main()
