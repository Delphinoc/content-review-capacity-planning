"""Allocate flex capacity (overtime, vendor surge, cross-skilled English reviewers, new hires)
across queues and weeks at least cost, keeping backlog within the 24h SLA where possible.

Linear program (PuLP / CBC), in handling hours. For queue q and week t:

  supply[q,t] = staffed[q,t] + overtime[q,t] + vendor[q,t] + hires[q](t > lead)
                + lent_in[q,t] - lent_out[q,t]
  backlog[q,t] >= backlog[q,t-1] + workload[q,t] - supply[q,t],  backlog >= 0
  breach[q,t]  >= backlog[q,t] - workload[q,t] / 7               (backlog beyond one day of work)

  min  cost(overtime, vendor, hires) + penalty x breach + small cost x backlog
"""
from __future__ import annotations

import pandas as pd
import pulp

from . import params as P
from .capacity import productive_hours_per_fte

FTE_WEEK_HOURS = productive_hours_per_fte()     # productive hours in one FTE-week at baseline shrinkage
BACKLOG_COST = 0.1                               # per FTE-week of backlog carried (prefer clearing it)


def allocate(plan: pd.DataFrame, budget: float | None = None) -> tuple[pd.DataFrame, dict]:
    queues = list(dict.fromkeys(plan.queue))
    weeks = sorted(plan.horizon_week.unique())
    H = len(weeks)
    p = plan.set_index(["queue", "horizon_week"])
    wl = p["workload_h"].to_dict()
    cap = p["capacity_h"].to_dict()
    staffed = p["staffed_fte"].to_dict()
    shrink = p["shrinkage"].to_dict()

    m = pulp.LpProblem("flex_allocation", pulp.LpMinimize)
    ot = {(q, t): pulp.LpVariable(f"ot_{q}_{t}", 0,
                                  P.OVERTIME_MAX_SHARE * staffed[q, t] * P.CONTRACT_HOURS_PER_WEEK * P.UTILISATION)
          for q in queues for t in weeks}
    vend = {(q, t): pulp.LpVariable(f"vendor_{q}_{t}", 0, P.VENDOR_QUEUES[q] if t > P.VENDOR_LEAD_WEEKS else 0)
            for q in P.VENDOR_QUEUES if q in queues for t in weeks}
    lend = {(q, t): pulp.LpVariable(f"lend_{q}_{t}", 0, P.CROSS_SKILL_SHARE[q] * wl[q, t])
            for q in P.CROSS_SKILL_SHARE if q in queues for t in weeks}
    hire = {q: pulp.LpVariable(f"hire_{q}", 0, P.HIRE_MAX_PER_QUEUE, cat="Integer") for q in queues}
    bl = {(q, t): pulp.LpVariable(f"backlog_{q}_{t}", 0) for q in queues for t in weeks}
    br = {(q, t): pulp.LpVariable(f"breach_{q}_{t}", 0) for q in queues for t in weeks}

    def supply(q, t):
        s = cap[q, t] + ot[q, t]
        if (q, t) in vend:
            s += vend[q, t] * productive_hours_per_fte(shrink[q, t])
        if t > P.HIRING_LEAD_WEEKS:
            s += hire[q] * productive_hours_per_fte(shrink[q, t])
        if (q, t) in lend:
            s += lend[q, t]
        if q == "EN":
            s -= pulp.lpSum(lend[k, t] for k in P.CROSS_SKILL_SHARE if (k, t) in lend)
        return s

    for q in queues:
        for i, t in enumerate(weeks):
            prev = bl[q, weeks[i - 1]] if i else 0
            m += bl[q, t] >= prev + wl[q, t] - supply(q, t)
            m += br[q, t] >= bl[q, t] - wl[q, t] / 7

    hour_cost = 1.0 / (P.CONTRACT_HOURS_PER_WEEK * P.UTILISATION)  # cost per productive overtime hour at 1.0x
    flex_cost = (pulp.lpSum(ot.values()) * hour_cost * P.OVERTIME_COST_MULT
                 + pulp.lpSum(vend.values()) * P.VENDOR_COST_MULT
                 + pulp.lpSum(hire.values()) * H * P.COST_PER_FTE_WEEK)
    m += (flex_cost
          + pulp.lpSum(br[q, t] * P.UNMET_PENALTY * P.QUEUE_SEVERITY[q] for q in queues for t in weeks) / FTE_WEEK_HOURS
          + pulp.lpSum(bl.values()) * BACKLOG_COST / FTE_WEEK_HOURS)
    if budget is not None:
        m += flex_cost <= budget
    status = m.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=60))

    rows = []
    for q in queues:
        for t in weeks:
            rows.append({
                "queue": q, "horizon_week": t,
                "overtime_fte": ot[q, t].value() / FTE_WEEK_HOURS,
                "vendor_fte": vend[q, t].value() if (q, t) in vend else 0.0,
                "lent_from_EN_fte": lend[q, t].value() / FTE_WEEK_HOURS if (q, t) in lend else 0.0,
                "new_hires_productive": hire[q].value() if t > P.HIRING_LEAD_WEEKS else 0.0,
                "backlog_days": bl[q, t].value() / (wl[q, t] / 7),
                "sla_risk": br[q, t].value() > 1e-6,
            })
    out = pd.DataFrame(rows)
    summary = {
        "status": pulp.LpStatus[status],
        "flex_cost_fte_weeks": pulp.value(flex_cost),
        "overtime_fte_weeks": out.overtime_fte.sum(),
        "vendor_fte_weeks": out.vendor_fte.sum(),
        "lent_from_EN_fte_weeks": out.lent_from_EN_fte.sum(),
        "hires": {q: int(round(hire[q].value())) for q in queues if hire[q].value() > 0.5},
        "sla_risk_queue_weeks_after": int(out.sla_risk.sum()),
    }
    return out, summary
