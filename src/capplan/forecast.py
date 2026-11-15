"""Weekly volume forecasting per queue: SARIMAX with seasonal Fourier terms and event regressors,
backtested against a seasonal-naive baseline."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX

from . import params as P
from .generate import event_activity

FOURIER_K = 3
ORDER = (1, 1, 1)


def exog_for_weeks(weeks: pd.DatetimeIndex, queue: str) -> pd.DataFrame:
    """Fourier terms for annual seasonality + share of each week's days with an event active."""
    t = weeks.dayofyear.to_numpy() / 365.25
    X = {}
    for k in range(1, FOURIER_K + 1):
        X[f"sin{k}"] = np.sin(2 * np.pi * k * t)
        X[f"cos{k}"] = np.cos(2 * np.pi * k * t)
    days = pd.date_range(weeks.min(), weeks.max() + pd.Timedelta(days=6), freq="D")
    ev = event_activity(days, queue)
    ev["week"] = days - pd.to_timedelta(days.dayofweek, unit="D")
    ev_week = ev.groupby("week").mean().reindex(weeks).fillna(0.0)
    for name in P.EVENTS:
        if ev_week[name].abs().sum() > 0 or name in _events_for(queue):
            X[f"ev_{name}"] = ev_week[name].to_numpy()
    return pd.DataFrame(X, index=weeks)


def _events_for(queue: str) -> list[str]:
    return [ev for ev, by_q in P.EVENTS.items() if by_q.get(queue)]


def _design(weeks_train: pd.DatetimeIndex, weeks_future: pd.DatetimeIndex, queue: str):
    allw = weeks_train.append(weeks_future)
    X = exog_for_weeks(allw, queue)
    # keep only event columns that are active somewhere in the training window (identifiable)
    keep = [c for c in X.columns if not c.startswith("ev_") or X.loc[weeks_train, c].sum() > 0]
    X = X[keep]
    return X.loc[weeks_train], X.loc[weeks_future]


def fit_forecast(y: pd.Series, horizon: int, queue: str, alpha: float = 0.2) -> pd.DataFrame:
    """Fit on log volume; return P50 (median) and the (1-alpha) interval in item units."""
    weeks_train = y.index
    weeks_future = pd.date_range(weeks_train[-1] + pd.Timedelta(weeks=1), periods=horizon, freq="W-MON")
    Xtr, Xf = _design(weeks_train, weeks_future, queue)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = SARIMAX(np.log(y.to_numpy()), exog=Xtr.to_numpy(), order=ORDER, trend="t",
                      enforce_stationarity=False, enforce_invertibility=False).fit(disp=False, maxiter=200)
        fc = res.get_forecast(horizon, exog=Xf.to_numpy())
    ci = fc.conf_int(alpha=alpha)
    return pd.DataFrame({
        "p50": np.exp(fc.predicted_mean),
        "p10": np.exp(ci[:, 0]),
        "p90": np.exp(ci[:, 1]),
    }, index=weeks_future)


def seasonal_naive(y: pd.Series, horizon: int) -> np.ndarray:
    """Same week last year (52 weeks back)."""
    return y.to_numpy()[-52:][:horizon]


def seasonal_naive_growth(y: pd.Series, horizon: int) -> np.ndarray:
    """Same week last year, scaled by the year-on-year growth of the last 13 weeks.
    A fairer baseline: it is what a planner would do in a spreadsheet."""
    v = y.to_numpy()
    yoy = v[-13:].sum() / v[-65:-52].sum()
    return v[-52:][:horizon] * yoy


def backtest(weekly: pd.DataFrame, n_folds: int = 4, horizon: int = P.HORIZON_WEEKS) -> pd.DataFrame:
    """Rolling-origin backtest: n_folds consecutive 13-week windows covering the last year."""
    rows = []
    for q in P.QUEUES:
        y = weekly[weekly.queue == q].set_index("week")["items"].astype(float).asfreq("W-MON")
        for f in range(n_folds, 0, -1):
            cut = len(y) - f * horizon
            train, test = y.iloc[:cut], y.iloc[cut:cut + horizon]
            fc = fit_forecast(train, horizon, q)
            sn = seasonal_naive(train, horizon)
            sng = seasonal_naive_growth(train, horizon)
            for i, wk in enumerate(test.index):
                rows.append({"queue": q, "fold": n_folds - f + 1, "week": wk, "actual": test.iloc[i],
                             "sarimax": fc["p50"].iloc[i], "sarimax_p10": fc["p10"].iloc[i],
                             "sarimax_p90": fc["p90"].iloc[i], "seasonal_naive": sn[i], "seasonal_naive_growth": sng[i]})
    return pd.DataFrame(rows)


def score(bt: pd.DataFrame, by: str | None = "queue") -> pd.DataFrame:
    def _s(g):
        a = g["actual"]
        return pd.Series({
            "wape_sarimax": (g["sarimax"] - a).abs().sum() / a.sum(),
            "wape_seasonal_naive": (g["seasonal_naive"] - a).abs().sum() / a.sum(),
            "wape_seasonal_naive_growth": (g["seasonal_naive_growth"] - a).abs().sum() / a.sum(),
            "bias_sarimax": (g["sarimax"] - a).sum() / a.sum(),
            "p10_p90_coverage": ((a >= g["sarimax_p10"]) & (a <= g["sarimax_p90"])).mean(),
        })
    if by is None:
        return _s(bt).to_frame("all").T
    return bt.groupby(by).apply(_s, include_groups=False)


def forecast_all(weekly: pd.DataFrame, horizon: int = P.HORIZON_WEEKS) -> pd.DataFrame:
    out = []
    for q in P.QUEUES:
        y = weekly[weekly.queue == q].set_index("week")["items"].astype(float).asfreq("W-MON")
        fc = fit_forecast(y, horizon, q).reset_index(names="week")
        fc.insert(1, "queue", q)
        fc.insert(2, "horizon_week", range(1, horizon + 1))
        out.append(fc)
    return pd.concat(out, ignore_index=True)
