"""Build the quarter's capacity plan under each scenario and measure the gap and SLA risk."""
from __future__ import annotations

import pandas as pd

from . import params as P
from .capacity import productive_hours_per_fte, required_fte, simulate_backlog, workload_hours


def _apply(df: pd.DataFrame, rules, col: str):
    for q, w0, w1, mult in rules:
        m = df.horizon_week.between(w0, w1)
        if q != "*":
            m &= df.queue == q
        df.loc[m, col] *= mult


def build_plan(forecast: pd.DataFrame, scenario: str = "baseline") -> pd.DataFrame:
    """One row per queue x horizon week with volume, AHT, shrinkage, staffed and required FTE."""
    sc = P.SCENARIOS[scenario]
    df = forecast[["week", "queue", "horizon_week"]].copy()
    df["items"] = forecast["p90"] if scenario == "p90_volume" else forecast["p50"]
    df["aht_s"] = df.queue.map(lambda q: P.QUEUES[q]["aht_s"]).astype(float)
    df["shrinkage"] = P.SHRINKAGE
    df["staffed_fte"] = df.queue.map(P.CURRENT_HC).astype(float)
    _apply(df, sc.get("volume", []), "items")
    _apply(df, sc.get("aht", []), "aht_s")
    for w0, w1, delta in sc.get("shrinkage", []):
        df.loc[df.horizon_week.between(w0, w1), "shrinkage"] += delta
    for q, w0, w1, delta in sc.get("shrinkage_q", []):
        df.loc[(df.queue == q) & df.horizon_week.between(w0, w1), "shrinkage"] += delta
    for q, from_week, change in sc.get("hc", []):
        m = (df.queue == q) & (df.horizon_week >= from_week)
        df.loc[m, "staffed_fte"] *= 1 + change
    df["workload_h"] = workload_hours(df["items"], df["aht_s"])
    df["required_fte"] = required_fte(df["items"], df["aht_s"], df["shrinkage"])
    df["capacity_h"] = df["staffed_fte"] * df["shrinkage"].map(lambda s: productive_hours_per_fte(s))
    df["gap_fte"] = df["staffed_fte"] - df["required_fte"]
    parts = []
    for q, g in df.groupby("queue", sort=False):
        g = g.sort_values("horizon_week")
        sim = simulate_backlog(g["workload_h"].to_numpy(), g["capacity_h"].to_numpy())
        sim.index = g.index
        parts.append(sim)
    df = df.join(pd.concat(parts))
    df.insert(0, "scenario", scenario)
    return df


def summarise(plan: pd.DataFrame) -> dict:
    by_q = plan.groupby("queue")
    return {
        "scenario": plan.scenario.iat[0],
        "required_fte_avg": plan.groupby("horizon_week").required_fte.sum().mean(),
        "required_fte_peak": plan.groupby("horizon_week").required_fte.sum().max(),
        "staffed_fte_avg": plan.groupby("horizon_week").staffed_fte.sum().mean(),
        "worst_week_shortfall_fte": -plan.groupby("horizon_week").gap_fte.apply(lambda s: s[s < 0].sum()).min(),
        "sla_risk_queue_weeks": int(plan.sla_risk.sum()),
        "queues_at_risk": ", ".join(q for q, g in by_q if g.sla_risk.any()) or "none",
        "max_backlog_days": plan.backlog_days.max(),
    }
