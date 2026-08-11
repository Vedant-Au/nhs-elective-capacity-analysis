"""
Healthcare Capacity Optimisation Toolkit — warehouse extraction.

Generalised from the Cheshire and Merseyside Phase 3 extractor. Everything that
was a hardcoded provider list, date window, cost constant or growth rate is now
read from the engagement config.

The warehouse schema itself is still assumed: this expects fact tables for
activity, forecast, workforce, beds and diagnostics on the naming convention the
project's SQL layer establishes. That assumption is stated rather than hidden —
porting to a differently-shaped warehouse means editing the queries here, and
the toolkit does not pretend otherwise.
"""
import re
import duckdb
import numpy as np
import pandas as pd

MONTHS = {m: i + 1 for i, m in enumerate(
    ['JANUARY', 'FEBRUARY', 'MARCH', 'APRIL', 'MAY', 'JUNE', 'JULY', 'AUGUST',
     'SEPTEMBER', 'OCTOBER', 'NOVEMBER', 'DECEMBER'])}


def parse_period(p, prefix):
    m = re.match(prefix + r'-(\w+)-(\d{4})', str(p), re.IGNORECASE)
    if not m:
        return pd.NaT
    return pd.Timestamp(year=int(m.group(2)), month=MONTHS[m.group(1).upper()], day=1)


def extract(cfg, verbose=True):
    wh = cfg['warehouse']
    con = duckdb.connect(wh['path'], read_only=True)
    pred = wh['provider_predicate']
    scope = f'(SELECT provider_org_code FROM dim_provider WHERE {pred})'

    providers = con.execute(f"""
        SELECT provider_org_code, provider_org_name, provider_type
        FROM dim_provider WHERE {pred} ORDER BY provider_org_code""").fetchdf()
    if providers.empty:
        raise ValueError(
            f'provider_predicate "{pred}" selected no providers. The toolkit '
            'will not run on an empty scope.')

    # ---- equity grouping -------------------------------------------------
    eq = cfg['equity']
    depriv = con.execute(f"""
        SELECT pl.provider_org_code, pl.la_name,
               imd.{eq['rank_field']} AS need_rank
        FROM {eq['dimension_table']} pl
        JOIN {eq['lookup_table']} imd USING ({eq['dimension_join']})""").fetchdf()
    providers = providers.merge(depriv, on='provider_org_code', how='left')
    median_rank = providers['need_rank'].median()
    if eq['low_rank_means_higher_need']:
        providers['higher_deprivation'] = providers['need_rank'] <= median_rank
    else:
        providers['higher_deprivation'] = providers['need_rank'] >= median_rank

    # ---- activity and trailing window ------------------------------------
    rtt = con.execute(f"""
        SELECT provider_org_code, period, waiting_list_size, waiting_list_over_52wk,
               completed_pathways_total, completed_admitted, completed_nonadmitted
        FROM fact_rtt_provider_specialty_month
        WHERE provider_org_code IN {scope}""").fetchdf()
    rtt['period_month'] = rtt['period'].apply(lambda p: parse_period(p, 'RTT'))
    pm = rtt.groupby(['provider_org_code', 'period_month']).agg(
        waiting_list_size=('waiting_list_size', 'sum'),
        over_52wk=('waiting_list_over_52wk', 'sum'),
        completed_pathways=('completed_pathways_total', 'sum')).reset_index()

    latest = pm['period_month'].max()
    trailing_start = latest - pd.DateOffset(months=wh['trailing_months'] - 1)
    tr = pm[pm['period_month'] >= trailing_start].groupby('provider_org_code').agg(
        trailing_wl=('waiting_list_size', 'mean'),
        trailing_over52=('over_52wk', 'mean'),
        trailing_completions=('completed_pathways', 'mean')).reset_index()
    tr['over52_share'] = tr['trailing_over52'] / tr['trailing_wl']

    # ---- forecast horizon and baseline backlog ---------------------------
    fc = con.execute(f"""
        SELECT provider_org_code, period_month, waiting_list_size AS wl_forecast,
               mc_p5, mc_p50, mc_p95
        FROM fact_rtt_waitinglist_forecast_provider_month
        WHERE provider_org_code IN {scope} AND is_forecast = true""").fetchdf()
    fc['period_month'] = pd.to_datetime(fc['period_month'])
    n_months = int(fc['period_month'].nunique())
    if n_months != cfg['engagement']['horizon_months']:
        raise ValueError(
            f'Config declares a {cfg["engagement"]["horizon_months"]}-month horizon '
            f'but the forecast table supplies {n_months} months. Reconcile these '
            'rather than letting the model silently run over the wrong window.')

    fc = fc.merge(tr[['provider_org_code', 'over52_share']], on='provider_org_code',
                  how='left')
    fc['baseline'] = fc['wl_forecast'] * fc['over52_share']
    base = fc.groupby('provider_org_code').agg(
        baseline_over52_total=('baseline', 'sum'),
        avg_monthly_wl_forecast=('wl_forecast', 'mean')).reset_index()

    # Demand range straight from the forecast's own interval at horizon end.
    end = fc[fc.period_month == fc.period_month.max()]
    demand_low = float(end.mc_p5.sum() / end.mc_p50.sum())
    demand_high = float(end.mc_p95.sum() / end.mc_p50.sum())

    # ---- capacity ceilings ------------------------------------------------
    kh = con.execute(f"""
        SELECT provider_org_code, quarter_end_date, available_ga, occupied_ga
        FROM fact_kh03_provider_quarter WHERE provider_org_code IN {scope}""").fetchdf()
    kh['quarter_end_date'] = pd.to_datetime(kh['quarter_end_date'])
    kh = kh[kh.quarter_end_date == kh.quarter_end_date.max()].copy()
    kh['bed_headroom_pct'] = 1 - (kh['occupied_ga'] / kh['available_ga'])

    wf = con.execute(f"""
        SELECT provider_org_code, fiscal_year, consultant_fte
        FROM fact_workforce_provider_year WHERE provider_org_code IN {scope}""").fetchdf()
    wf = wf[wf.fiscal_year == sorted(wf.fiscal_year.unique())[-1]][
        ['provider_org_code', 'consultant_fte']]

    # ---- outsourcing pool -------------------------------------------------
    out_pred = wh['outsourcing_predicate']
    isa = con.execute(f"""
        SELECT period, sum(completed_pathways_total) AS c
        FROM fact_rtt_provider_specialty_month
        WHERE provider_org_code IN
              (SELECT provider_org_code FROM dim_provider WHERE {out_pred})
        GROUP BY period""").fetchdf()
    isa['period_month'] = isa['period'].apply(lambda p: parse_period(p, 'RTT'))
    is_pool = float(isa[isa.period_month >= trailing_start]['c'].mean())

    # ---- completion mix and diagnostic mix --------------------------------
    mix = rtt[rtt.period_month >= trailing_start]
    admitted = float(mix['completed_admitted'].sum())
    nonadmitted = float(mix['completed_nonadmitted'].sum())
    admitted_share = admitted / (admitted + nonadmitted)

    # Diagnostic mix is split to match the cost currencies available, not the
    # dataset's own categories. Audiology is carved out of physiological
    # measurement because it carries its own published unit cost; the remainder
    # is priced against the generic directly-accessed currency. The carve-out
    # is driven by the currency names in config, so an engagement with a
    # different cost schedule changes the config rather than this code.
    dm = con.execute(f"""
        SELECT d.category, d.diagnostic_test_name, sum(f.total_activity) AS activity
        FROM fact_dm01_provider_test_month f
        JOIN dim_diagnostic_test d USING (diagnostic_test_code)
        WHERE f.provider_org_code IN {scope}
        GROUP BY 1, 2""").fetchdf()
    currencies = cfg['costs']['diagnostic_currencies']
    act = {}
    if 'imaging' in currencies:
        act['imaging'] = float(dm.loc[dm.category == 'imaging', 'activity'].sum())
    if 'endoscopy' in currencies:
        act['endoscopy'] = float(dm.loc[dm.category == 'endoscopy', 'activity'].sum())
    physio = float(dm.loc[dm.category == 'physiological_measurement', 'activity'].sum())
    if 'audiology' in currencies:
        aud = float(dm.loc[dm.diagnostic_test_name.str.contains(
            'Audiology', case=False, na=False), 'activity'].sum())
        act['audiology'] = aud
        act['other_physiological'] = physio - aud
    else:
        act['other_physiological'] = physio
    total_tests = sum(act.values())
    if total_tests <= 0:
        raise ValueError('No diagnostic activity found for the providers in scope.')
    diag_mix = {k: v / total_tests for k, v in act.items()}

    df = (providers
          .merge(base, on='provider_org_code', how='left')
          .merge(tr, on='provider_org_code', how='left')
          .merge(wf, on='provider_org_code', how='left')
          .merge(kh[['provider_org_code', 'bed_headroom_pct']],
                 on='provider_org_code', how='left'))
    df = df.fillna({'bed_headroom_pct': 0.0, 'baseline_over52_total': 0.0,
                    'trailing_completions': 0.0})

    data = {
        'providers': df.to_dict(orient='records'),
        'n_months': n_months,
        'latest_actual_month': str(latest.date()),
        'is_ceiling_trailing_monthly': is_pool,
        'admitted_share': admitted_share,
        'diagnostic_mix': diag_mix,
        'demand_low': demand_low,
        'demand_high': demand_high,
    }
    if verbose:
        print(f"  providers in scope: {len(df)}")
        print(f"  horizon: {n_months} months to {fc.period_month.max().date()}")
        print(f"  baseline backlog: {df.baseline_over52_total.sum():,.0f}")
        print(f"  higher-need providers: {int(df.higher_deprivation.sum())} of {len(df)}")
        print(f"  demand interval from forecast: {demand_low:.4f} – {demand_high:.4f}")
        print(f"  outsourcing pool: {is_pool:,.0f}/month")
        print(f"  admitted share: {admitted_share:.1%}")
        print(f"  diagnostic mix: " +
              ', '.join(f'{k} {v:.1%}' for k, v in sorted(diag_mix.items())))
    return data
