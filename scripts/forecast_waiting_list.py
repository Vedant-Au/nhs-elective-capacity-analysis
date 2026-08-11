"""
Forecast RTT waiting_list_size, provider-month grain, 12 core trusts.

Design (confirmed with Vedant, 2026-08 continuation session): try several
candidate methods and let a time-based backtest pick the best one per
series, rather than committing to one method up front. Prediction intervals
come from a Monte Carlo residual bootstrap rather than each model's own
closed-form CI formula, per the "apply MC wherever viable" steer.

Scope decision, stated plainly: forecasting runs at provider-month (sum of
waiting_list_size across all specialties for that trust), not provider-
specialty-month. 84 months is already a thin window for a 12-month seasonal
model; splitting further into ~25 specialties per provider would leave most
individual series too short and noisy to fit anything beyond a naive
baseline. Provider-month is also what the capacity-planning narrative
actually needs first. A specialty-level cut is a legitimate follow-on once
this is validated, not a corner quietly cut.

Candidate methods, backtested on the last 12 months held out from each
provider's 84-month series:
  1. seasonal_naive   y_t = y_{t-12} (same calendar month, prior year)
  2. linear_trend     OLS on time index, no seasonality
  3. holt_winters     statsmodels ExponentialSmoothing, additive trend + seasonal
  4. auto_arima       pmdarima auto_arima, seasonal (m=12), stepwise search

Whichever has the lowest backtest MAPE for a given provider is refit on the
FULL 84-month series and used for the real forward forecast. Every method's
backtest MAPE is stored, not just the winner's, so the choice is auditable.

Monte Carlo prediction intervals: bootstrap the winning model's in-sample
residuals (with replacement, 2,000 draws), add a resampled residual path to
the point forecast to build 2,000 simulated future trajectories, then take
the 5th/50th/95th percentiles at each forecast horizon month as the interval
— an empirical interval that doesn't assume Gaussian residuals, unlike the
models' own analytic CIs.
"""
import os
import shutil
import warnings

import duckdb
import numpy as np
import pandas as pd
import pmdarima as pm
from statsmodels.tsa.holtwinters import ExponentialSmoothing

warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PROJECT_ROOT, "nhs_warehouse.db")
BUILD_DB = f"/tmp/nhs_wh_forecast_build_{os.getpid()}.db"

HOLDOUT_MONTHS = 12
FORECAST_HORIZON = 18
N_MC = 2000
RNG_SEED = 42


def mape(actual, pred):
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    return float(np.mean(np.abs((actual - pred) / actual)) * 100)


def fit_seasonal_naive(train, horizon):
    last_year = train[-12:]
    reps = int(np.ceil(horizon / 12))
    fc = np.tile(last_year, reps)[:horizon]
    fitted = np.concatenate([np.full(12, np.nan), train[:-12]])  # y_{t-12} in-sample
    resid = train[12:] - fitted[12:]
    return fc, resid

def fit_linear_trend(train, horizon):
    t = np.arange(len(train))
    coef = np.polyfit(t, train, 1)
    fitted = np.polyval(coef, t)
    resid = train - fitted
    future_t = np.arange(len(train), len(train) + horizon)
    fc = np.polyval(coef, future_t)
    return fc, resid

def fit_holt_winters(train, horizon):
    model = ExponentialSmoothing(
        train, trend="add", seasonal="add", seasonal_periods=12, initialization_method="estimated"
    ).fit()
    fitted = model.fittedvalues
    resid = train - fitted
    fc = model.forecast(horizon)
    return np.asarray(fc), np.asarray(resid)

def fit_auto_arima(train, horizon):
    model = pm.auto_arima(
        train, seasonal=True, m=12, suppress_warnings=True, error_action="ignore", stepwise=True
    )
    resid = model.arima_res_.resid if hasattr(model, "arima_res_") else train - model.predict_in_sample()
    fc = model.predict(n_periods=horizon)
    return np.asarray(fc), np.asarray(resid)

METHODS = {
    "seasonal_naive": fit_seasonal_naive,
    "linear_trend": fit_linear_trend,
    "holt_winters": fit_holt_winters,
    "auto_arima": fit_auto_arima,
}


def backtest_provider(y: np.ndarray) -> dict:
    """Return {method: backtest_mape} using the last HOLDOUT_MONTHS as test."""
    train, test = y[:-HOLDOUT_MONTHS], y[-HOLDOUT_MONTHS:]
    scores = {}
    for name, fn in METHODS.items():
        try:
            fc, _ = fn(train, HOLDOUT_MONTHS)
            scores[name] = mape(test, fc)
        except Exception as e:
            print(f"    {name} failed on backtest: {e}")
            scores[name] = np.inf
    return scores


def mc_prediction_interval(resid: np.ndarray, point_fc: np.ndarray, rng) -> tuple:
    """Bootstrap residuals to build empirical 5/50/95 percentile bands around point_fc."""
    resid = resid[~np.isnan(resid)]
    horizon = len(point_fc)
    sims = np.zeros((N_MC, horizon))
    for i in range(N_MC):
        draw = rng.choice(resid, size=horizon, replace=True)
        sims[i] = point_fc + draw  # additive noise per horizon step, drawn from in-sample residuals
    p5 = np.percentile(sims, 5, axis=0)
    p50 = np.percentile(sims, 50, axis=0)
    p95 = np.percentile(sims, 95, axis=0)
    return p5, p50, p95


def main():
    print("== Copying current warehouse into /tmp ==", flush=True)
    if os.path.exists(BUILD_DB):
        os.remove(BUILD_DB)
    shutil.copy(PROJECT_DB, BUILD_DB)
    con = duckdb.connect(BUILD_DB)

    core_providers = con.execute(
        "select provider_org_code from dim_provider where in_core_analysis"
    ).fetchdf()["provider_org_code"].tolist()

    # Excludes C_999 ('Total' pseudo-row, NHS-published sum across every other
    # treatment_function_code for the same provider-month) -- without this
    # filter, summing waiting_list_size across treatment_function_code below
    # silently double-counts every provider-month (confirmed: REM Sep-2022
    # true total 87,044, contaminated sum 174,088). Real bug, fixed 2026-08,
    # see docs/STATUS.md.
    rtt = con.execute(f"""
        select provider_org_code, treatment_function_code, period, waiting_list_size
        from fact_rtt_provider_specialty_month
        where provider_org_code in ({','.join(f"'{c}'" for c in core_providers)})
          and treatment_function_code <> 'C_999'
    """).fetchdf()

    import re
    MONTH_RE = re.compile(r"^[A-Za-z0-9]+-([A-Za-z]+)-(\d{4})$")
    def parse_period(p):
        m = MONTH_RE.match(p)
        month_num = pd.to_datetime(f"{m.group(1)} 1 2000", format="%B %d %Y").month
        return pd.Timestamp(year=int(m.group(2)), month=month_num, day=1)
    rtt["period_month"] = rtt["period"].apply(parse_period)

    provider_month = (
        rtt.groupby(["provider_org_code", "period_month"])["waiting_list_size"]
        .sum().reset_index()
    )

    all_months = pd.date_range(provider_month["period_month"].min(),
                                provider_month["period_month"].max(), freq="MS")
    print(f"Full month range: {all_months[0].date()} to {all_months[-1].date()} ({len(all_months)} months)")

    model_selection_rows = []
    forecast_rows = []
    rng = np.random.default_rng(RNG_SEED)

    for provider in core_providers:
        sub = provider_month[provider_month["provider_org_code"] == provider].set_index("period_month")
        sub = sub.reindex(all_months)
        n_missing = sub["waiting_list_size"].isna().sum()
        if n_missing:
            sub["waiting_list_size"] = sub["waiting_list_size"].interpolate(limit_direction="both")
            print(f"{provider}: interpolated {n_missing} missing month(s)")
        y = sub["waiting_list_size"].values.astype(float)

        print(f"\n=== {provider} (n={len(y)}) ===")
        scores = backtest_provider(y)
        for m, s in scores.items():
            print(f"  backtest MAPE {m}: {s:.2f}%")
        best_method = min(scores, key=scores.get)
        print(f"  -> winner: {best_method}")

        # Refit winner on FULL series for the real forward forecast
        fc, resid = METHODS[best_method](y, FORECAST_HORIZON)
        p5, p50, p95 = mc_prediction_interval(resid, fc, rng)

        future_months = pd.date_range(all_months[-1] + pd.DateOffset(months=1),
                                       periods=FORECAST_HORIZON, freq="MS")

        for method, s in scores.items():
            model_selection_rows.append({
                "provider_org_code": provider, "method": method,
                "backtest_mape": s, "is_winner": method == best_method,
            })

        # Historical rows
        for dt, val in zip(all_months, y):
            forecast_rows.append({
                "provider_org_code": provider, "period_month": dt.date(),
                "waiting_list_size": val, "is_forecast": False,
                "method": None, "mc_p5": None, "mc_p50": None, "mc_p95": None,
            })
        # Forecast rows
        for dt, point, lo, mid, hi in zip(future_months, fc, p5, p50, p95):
            forecast_rows.append({
                "provider_org_code": provider, "period_month": dt.date(),
                "waiting_list_size": float(point), "is_forecast": True,
                "method": best_method, "mc_p5": float(lo), "mc_p50": float(mid), "mc_p95": float(hi),
            })

    model_selection = pd.DataFrame(model_selection_rows)
    forecast_df = pd.DataFrame(forecast_rows)

    print("\n== Model selection summary ==")
    print(model_selection.pivot(index="provider_org_code", columns="method", values="backtest_mape").round(2))
    print("\nWinners:")
    print(model_selection[model_selection["is_winner"]][["provider_org_code", "method", "backtest_mape"]]
          .to_string(index=False))

    # ---- Validation ----
    print("\n== Validation ==")
    assert (forecast_df["waiting_list_size"] >= 0).all(), "negative waiting list forecast"
    neg_p5 = (forecast_df.loc[forecast_df["is_forecast"], "mc_p5"] < 0).sum()
    print(f"Forecast rows with mc_p5 < 0 (possible for a bootstrap band, not necessarily wrong): {neg_p5}")

    rem_fc = forecast_df[(forecast_df["provider_org_code"] == "REM") & forecast_df["is_forecast"]]
    print("\nREM forward forecast (spot check):")
    print(rem_fc[["period_month", "waiting_list_size", "mc_p5", "mc_p95"]].to_string(index=False))

    # ---- Write tables ----
    con.execute("DROP TABLE IF EXISTS fact_rtt_waitinglist_forecast_provider_month")
    con.register("fc_df", forecast_df)
    con.execute("""
        CREATE TABLE fact_rtt_waitinglist_forecast_provider_month AS
        SELECT provider_org_code, period_month, waiting_list_size, is_forecast,
               method, mc_p5, mc_p50, mc_p95
        FROM fc_df
    """)

    con.execute("DROP TABLE IF EXISTS ref_forecast_model_selection")
    con.register("ms_df", model_selection)
    con.execute("CREATE TABLE ref_forecast_model_selection AS SELECT * FROM ms_df")

    con.close()

    print("\n== Copying build DB back to project mount ==")
    tmp_final = f"/tmp/nhs_wh_forecast_final_{os.getpid()}.db"
    shutil.copy(BUILD_DB, tmp_final)
    shutil.copy(tmp_final, PROJECT_DB)
    verify = duckdb.connect(PROJECT_DB, read_only=True)
    n1 = verify.execute("select count(*) from fact_rtt_waitinglist_forecast_provider_month").fetchone()[0]
    n2 = verify.execute("select count(*) from ref_forecast_model_selection").fetchone()[0]
    print(f"fact_rtt_waitinglist_forecast_provider_month: {n1} rows; ref_forecast_model_selection: {n2} rows")
    verify.close()
    print("Done.")


if __name__ == "__main__":
    main()
