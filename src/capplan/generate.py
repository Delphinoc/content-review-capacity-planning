"""Generate a synthetic daily human-review volume history for each queue."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import params as P


def event_activity(dates: pd.DatetimeIndex, queue: str) -> pd.DataFrame:
    """1.0 on days an event is active for this queue, else 0.0 (one column per event type)."""
    out = pd.DataFrame(0.0, index=dates, columns=list(P.EVENTS))
    for ev, by_queue in P.EVENTS.items():
        for start, end in by_queue.get(queue, []):
            out.loc[(dates >= start) & (dates <= end), ev] = 1.0
    return out


def annual_seasonality(dates: pd.DatetimeIndex) -> np.ndarray:
    """Year-end peak (shopping festivals, holidays) and a smaller mid-year school-holiday bump."""
    doy = dates.dayofyear.to_numpy()
    return 1 + 0.08 * np.cos(2 * np.pi * (doy - 350) / 365.25) + 0.03 * np.cos(4 * np.pi * (doy - 195) / 365.25)


DOW = np.array([0.95, 0.94, 0.95, 0.97, 1.02, 1.09, 1.08])  # Mon..Sun, weekends busier


def generate_daily(seed: int = P.SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range(P.HISTORY_START, P.HISTORY_END, freq="D")
    years = (dates - dates[0]).days.to_numpy() / 365.25
    frames = []
    for q, cfg in P.QUEUES.items():
        base = cfg["base_weekly"] / 7
        trend = (1 + cfg["growth"]) ** years
        ev = event_activity(dates, q)
        ev_mult = np.ones(len(dates))
        for name, uplift in P.EVENT_UPLIFT.items():
            ev_mult *= 1 + uplift * ev[name].to_numpy()
        policy = np.ones(len(dates))
        if q == P.POLICY_SHIFT["queue"]:
            policy[dates >= P.POLICY_SHIFT["date"]] = 1 + P.POLICY_SHIFT["uplift"]
        noise = rng.lognormal(0, 0.05, len(dates))
        vol = base * trend * annual_seasonality(dates) * DOW[dates.dayofweek] * ev_mult * policy * noise
        frames.append(pd.DataFrame({"date": dates, "queue": q, "items": np.round(vol).astype(int)}))
    return pd.concat(frames, ignore_index=True)


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """Weeks start on Monday; the label is the Monday."""
    d = daily.copy()
    d["week"] = d["date"] - pd.to_timedelta(d["date"].dt.dayofweek, unit="D")
    return d.groupby(["week", "queue"], as_index=False)["items"].sum()
