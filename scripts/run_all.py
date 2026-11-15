"""Run the full pipeline: data -> forecast + backtest -> capacity plan -> scenarios -> allocation -> Excel + charts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from capplan import params as P  # noqa: E402
from capplan.allocate import allocate  # noqa: E402
from capplan.capacity import escalation_staffing  # noqa: E402
from capplan.excel import build_workbook  # noqa: E402
from capplan.forecast import backtest, forecast_all, score  # noqa: E402
from capplan.generate import generate_daily, to_weekly  # noqa: E402
from capplan.scenarios import build_plan, summarise  # noqa: E402

DATA, OUT, CH = ROOT / "data", ROOT / "outputs", ROOT / "outputs" / "charts"
for d in (DATA, OUT, CH):
    d.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
C_MAIN, C_ALT, C_BAD, C_GREY = "#1F3864", "#2E75B6", "#C00000", "#A6A6A6"


def main() -> None:
    # 1. Data ---------------------------------------------------------------
    daily = generate_daily()
    weekly = to_weekly(daily)
    daily.to_csv(DATA / "daily_review_volume.csv", index=False)
    weekly.to_csv(DATA / "weekly_review_volume.csv", index=False)
    print(f"[1/6] data: {len(daily):,} daily rows, {weekly.week.nunique()} weeks x {weekly.queue.nunique()} queues")

    # 2. Forecast backtest + final forecast -------------------------------------
    bt = backtest(weekly)
    bt.to_csv(OUT / "backtest_predictions.csv", index=False)
    sc_q = score(bt)
    sc_all = score(bt, by=None)
    pd.concat([sc_q, sc_all]).round(4).to_csv(OUT / "backtest_scores.csv")
    fc = forecast_all(weekly)
    fc.to_csv(OUT / "forecast_13w.csv", index=False)
    print(f"[2/6] backtest WAPE: SARIMAX {sc_all.wape_sarimax.iat[0]:.1%} | seasonal naive + growth "
          f"{sc_all.wape_seasonal_naive_growth.iat[0]:.1%} | seasonal naive {sc_all.wape_seasonal_naive.iat[0]:.1%}")

    # 3-5. Scenarios and allocation ------------------------------------------------
    plans, summaries, allocs = [], [], []
    for s in P.SCENARIOS:
        plan = build_plan(fc, s)
        alloc, a_sum = allocate(plan)
        alloc.insert(0, "scenario", s)
        plans.append(plan)
        allocs.append(alloc)
        row = summarise(plan)
        row.update({"description": P.SCENARIOS[s]["desc"],
                    "flex_cost_fte_weeks": a_sum["flex_cost_fte_weeks"],
                    "overtime_fte_weeks": a_sum["overtime_fte_weeks"],
                    "vendor_fte_weeks": a_sum["vendor_fte_weeks"],
                    "cross_skill_fte_weeks": a_sum["lent_from_EN_fte_weeks"],
                    "hires": json.dumps(a_sum["hires"]),
                    "sla_risk_queue_weeks_after_flex": a_sum["sla_risk_queue_weeks_after"],
                    "lp_status": a_sum["status"]})
        summaries.append(row)
    plans = pd.concat(plans, ignore_index=True)
    allocs = pd.concat(allocs, ignore_index=True)
    summ = pd.DataFrame(summaries)
    plans.to_csv(OUT / "capacity_plan_by_scenario.csv", index=False)
    allocs.to_csv(OUT / "flex_allocation_by_scenario.csv", index=False)
    summ.round(2).to_csv(OUT / "scenario_summary.csv", index=False)
    print("[3/6] scenarios:")
    print(summ[["scenario", "required_fte_peak", "worst_week_shortfall_fte", "sla_risk_queue_weeks",
                "flex_cost_fte_weeks", "sla_risk_queue_weeks_after_flex"]].round(1).to_string(index=False))

    esc, esc_sum = escalation_staffing()
    esc.to_csv(OUT / "escalation_erlang_c.csv", index=False)
    print(f"[4/6] escalation queue: {esc_sum['fte']:.0f} FTE; Erlang C needs "
          f"{esc_sum['erlang_uplift_vs_workload']:.0%} more agent-hours than workload alone")

    build_workbook(fc, str(OUT / "capacity_model.xlsx"))
    print("[5/6] Excel model written: outputs/capacity_model.xlsx")

    charts(weekly, fc, sc_q, plans, summ, esc)
    print("[6/6] charts written to outputs/charts/")

    headline = {
        "weeks_history": int(weekly.week.nunique()),
        "queues": len(P.QUEUES),
        "backtest_wape_sarimax": float(sc_all.wape_sarimax.iat[0]),
        "backtest_wape_seasonal_naive_growth": float(sc_all.wape_seasonal_naive_growth.iat[0]),
        "backtest_wape_seasonal_naive": float(sc_all.wape_seasonal_naive.iat[0]),
        "p10_p90_coverage": float(sc_all.p10_p90_coverage.iat[0]),
        "staffed_fte": int(sum(P.CURRENT_HC.values())),
        "escalation": esc_sum,
        "scenarios": summ.set_index("scenario")[["required_fte_peak", "worst_week_shortfall_fte",
                                                 "sla_risk_queue_weeks", "flex_cost_fte_weeks",
                                                 "sla_risk_queue_weeks_after_flex", "hires"]].round(2).to_dict("index"),
    }
    (OUT / "headline_metrics.json").write_text(json.dumps(headline, indent=2, default=float))


def charts(weekly, fc, sc_q, plans, summ, esc) -> None:
    # 01 total history + forecast
    tot = weekly.groupby("week")["items"].sum() / 1e6
    ftot = fc.groupby("week")[["p10", "p50", "p90"]].sum() / 1e6
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(tot.index, tot.values, color=C_MAIN, lw=1.4, label="Actual (synthetic)")
    ax.plot(ftot.index, ftot.p50, color=C_ALT, lw=2, label="Forecast P50")
    ax.fill_between(ftot.index, ftot.p10, ftot.p90, color=C_ALT, alpha=0.25, label="P10-P90")
    ax.set_ylabel("Human-review items per week (M)")
    ax.set_title("Weekly review volume, all queues: history and 13-week forecast", loc="left")
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout(); fig.savefig(CH / "01_volume_forecast.png", dpi=150); plt.close(fig)

    # 02 backtest
    s = sc_q[["wape_sarimax", "wape_seasonal_naive_growth", "wape_seasonal_naive"]] * 100
    fig, ax = plt.subplots(figsize=(8, 3.8))
    x = range(len(s))
    w = 0.27
    for i, (col, lab, colr) in enumerate([("wape_sarimax", "SARIMAX + events", C_MAIN),
                                          ("wape_seasonal_naive_growth", "Seasonal naive + growth", C_ALT),
                                          ("wape_seasonal_naive", "Seasonal naive", C_GREY)]):
        ax.bar([v + (i - 1) * w for v in x], s[col], w, label=lab, color=colr)
    ax.set_xticks(list(x)); ax.set_xticklabels(s.index)
    ax.set_ylabel("WAPE (%)"); ax.legend(frameon=False)
    ax.set_title("Backtest error, 4 rolling 13-week folds (lower is better)", loc="left")
    fig.tight_layout(); fig.savefig(CH / "02_backtest_wape.png", dpi=150); plt.close(fig)

    # 03 baseline required vs staffed
    b = plans[plans.scenario == "baseline"].groupby("week")[["required_fte", "staffed_fte"]].sum()
    p90 = plans[plans.scenario == "p90_volume"].groupby("week")["required_fte"].sum()
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.plot(b.index, b.required_fte, color=C_MAIN, lw=2, marker="o", ms=3, label="Required FTE (P50)")
    ax.plot(p90.index, p90.values, color=C_MAIN, lw=1, ls="--", label="Required FTE (P90)")
    ax.step(b.index, b.staffed_fte, where="mid", color=C_BAD, lw=1.5, label="Staffed FTE")
    ax.set_ylabel("FTE"); ax.legend(frameon=False, loc="lower right")
    ax.set_title("Baseline: required vs staffed reviewers, next 13 weeks", loc="left")
    fig.tight_layout(); fig.savefig(CH / "03_required_vs_staffed.png", dpi=150); plt.close(fig)

    # 04 scenarios
    sm = summ.set_index("scenario")
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    y = range(len(sm))
    axes[0].barh(y, sm.sla_risk_queue_weeks, color=C_GREY, label="No action")
    axes[0].barh(y, sm.sla_risk_queue_weeks_after_flex, color=C_BAD, label="After flex plan")
    axes[0].set_yticks(list(y)); axes[0].set_yticklabels(sm.index); axes[0].invert_yaxis()
    axes[0].set_xlabel("Queue-weeks with backlog > 24h"); axes[0].legend(frameon=False)
    axes[0].set_title("SLA risk by scenario", loc="left")
    axes[1].barh(y, sm.flex_cost_fte_weeks, color=C_MAIN)
    axes[1].set_yticks(list(y)); axes[1].set_yticklabels([]); axes[1].invert_yaxis()
    axes[1].set_xlabel("Flex cost (FTE-week equivalents)")
    axes[1].set_title("Cost of the least-cost flex plan", loc="left")
    fig.tight_layout(); fig.savefig(CH / "04_scenarios.png", dpi=150); plt.close(fig)

    # 05 Erlang C
    fig, ax = plt.subplots(figsize=(9, 3.5))
    ax.bar(esc.hour, esc.erlang_agents, color=C_ALT, label="Agents needed (Erlang C, 90% in 5 min)")
    ax.plot(esc.hour, esc.workload_agents, color=C_MAIN, lw=2, label="Workload only (arrivals x AHT)")
    ax.set_xlabel("Hour of day"); ax.set_ylabel("Agents on shift"); ax.legend(frameon=False)
    ax.set_title("Priority escalation queue: hourly staffing", loc="left")
    fig.tight_layout(); fig.savefig(CH / "05_escalation_erlang_c.png", dpi=150); plt.close(fig)


if __name__ == "__main__":
    main()
