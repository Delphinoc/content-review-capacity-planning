"""Turn forecast volume into reviewer headcount, and test it against staffed capacity."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import params as P


def productive_hours_per_fte(shrinkage: float = P.SHRINKAGE, utilisation: float = P.UTILISATION,
                             contract_hours: float = P.CONTRACT_HOURS_PER_WEEK) -> float:
    """Hours per week one FTE actually spends handling items."""
    return contract_hours * (1 - shrinkage) * utilisation


def workload_hours(items, aht_s, qa_rate: float = P.QA_RATE):
    """Handling hours needed: every item once, plus the QA re-review sample."""
    return np.asarray(items) * (1 + qa_rate) * np.asarray(aht_s) / 3600.0


def required_fte(items, aht_s, shrinkage=P.SHRINKAGE, utilisation=P.UTILISATION, qa_rate=P.QA_RATE):
    return workload_hours(items, aht_s, qa_rate) / productive_hours_per_fte(shrinkage, utilisation)


def simulate_backlog(workload_h: np.ndarray, capacity_h: np.ndarray, start_backlog_h: float = 0.0) -> pd.DataFrame:
    """Week-by-week backlog carry-over (hours of work not done by week end).

    SLA at risk when carried-over backlog exceeds one day of that week's workload:
    under first-in-first-out, some items have then waited more than 24 hours."""
    backlog, rows = start_backlog_h, []
    for w, c in zip(workload_h, capacity_h):
        backlog = max(0.0, backlog + w - c)
        backlog_days = backlog / (w / 7) if w > 0 else 0.0
        rows.append({"backlog_h": backlog, "backlog_days": backlog_days, "sla_risk": backlog_days > 1.0})
    return pd.DataFrame(rows)


# Erlang C for the real-time escalation queue ----------------------------------

def erlang_c_wait_prob(agents: int, traffic: float) -> float:
    """Probability an arriving item has to wait (Erlang C). traffic = arrival rate x AHT (Erlangs)."""
    if agents <= traffic:
        return 1.0
    # numerically stable recursion via Erlang B
    b = 1.0
    for k in range(1, agents + 1):
        b = traffic * b / (k + traffic * b)
    return agents * b / (agents - traffic * (1 - b))


def service_level(agents: int, traffic: float, aht_min: float, target_wait_min: float) -> float:
    pw = erlang_c_wait_prob(agents, traffic)
    return 1 - pw * math.exp(-(agents - traffic) * target_wait_min / aht_min)


def agents_needed(items_per_hour: float, aht_min: float, sl: float, target_wait_min: float) -> int:
    traffic = items_per_hour * aht_min / 60.0
    n = max(1, math.ceil(traffic))
    while service_level(n, traffic, aht_min, target_wait_min) < sl:
        n += 1
    return n


def escalation_staffing(cfg: dict = P.ESCALATION, profile=P.ESCALATION_HOURLY_PROFILE,
                        shrinkage: float = P.SHRINKAGE) -> tuple[pd.DataFrame, dict]:
    """Agents needed in each hour (Erlang C) vs a naive workload-only count; converted to FTE."""
    rows = []
    for h, share in enumerate(profile):
        lam = cfg["peak_items_per_hour"] * share
        traffic = lam * cfg["aht_min"] / 60
        n = agents_needed(lam, cfg["aht_min"], cfg["service_level"], cfg["target_wait_min"])
        rows.append({"hour": h, "items_per_hour": lam, "workload_agents": traffic, "erlang_agents": n,
                     "occupancy": traffic / n,
                     "service_level": service_level(n, traffic, cfg["aht_min"], cfg["target_wait_min"])})
    df = pd.DataFrame(rows)
    agent_hours_week = df["erlang_agents"].sum() * 7
    summary = {
        "erlang_agent_hours_per_day": float(df["erlang_agents"].sum()),
        "workload_agent_hours_per_day": float(df["workload_agents"].sum()),
        "erlang_uplift_vs_workload": float(df["erlang_agents"].sum() / df["workload_agents"].sum() - 1),
        "avg_occupancy": float(df["workload_agents"].sum() / df["erlang_agents"].sum()),
        # FTE: scheduled agent-hours / (contract hours x (1 - shrinkage)); no utilisation factor,
        # because Erlang C already sets idle time to meet the wait target
        "fte": float(agent_hours_week / (P.CONTRACT_HOURS_PER_WEEK * (1 - shrinkage))),
    }
    return df, summary
