-- RTT waiting list forecast, grain (provider, month), 12 core trusts.
-- Built by scripts/forecast_waiting_list.py. Historical rows (is_forecast =
-- false) are the actual warehoused waiting_list_size, summed across
-- specialties; forecast rows (is_forecast = true) extend 18 months beyond
-- the last real month (through 2027-09 as of the 2026-08-08 build, since
-- the warehouse's real data runs through 2026-03).
--
-- METHOD SELECTION: four candidates (seasonal_naive, linear_trend,
-- holt_winters, auto_arima) were backtested per provider on a 12-month
-- holdout; whichever had the lowest backtest MAPE was refit on the full
-- 84-month series for the real forecast. See ref_forecast_model_selection
-- for every method's score, not just the winner's — this is intentionally
-- auditable rather than a black-box "trust the forecast" table.
--
-- HONEST CAVEAT: backtest MAPEs range widely (roughly 2% to 60% across
-- providers/methods) and several trusts have no method scoring below
-- ~10-17% even at their best (e.g. RBQ, RJN) — the 2020-2022 COVID
-- disruption sits inside the 84-month training window and genuinely
-- confuses trend/seasonality for some series. Forecasts for those trusts
-- should be read as directional, not precise. seasonal_naive (which simply
-- repeats the prior year's monthly pattern) won for several providers,
-- including REM — a real finding in itself: recent RTT trends have largely
-- plateaued rather than following a strong monotonic trend, which is why a
-- flat repeat-last-year forecast beat trend-fitting methods on the holdout.
--
-- PREDICTION INTERVALS: mc_p5/mc_p50/mc_p95 come from a 2,000-iteration
-- Monte Carlo bootstrap of the winning model's in-sample residuals (see
-- script header), not a closed-form Gaussian CI.

create table if not exists fact_rtt_waitinglist_forecast_provider_month (
    provider_org_code    text    not null,
    period_month          date    not null,
    waiting_list_size     double,            -- actual (historical rows) or point forecast (forecast rows)
    is_forecast            boolean not null,
    method                  text,             -- null for historical rows; winning method's name for forecast rows
    mc_p5                    double,           -- null for historical rows
    mc_p50                   double,
    mc_p95                   double,
    primary key (provider_org_code, period_month)
);

create table if not exists ref_forecast_model_selection (
    provider_org_code    text    not null,
    method                  text    not null,
    backtest_mape          double,
    is_winner               boolean not null,
    primary key (provider_org_code, method)
);
