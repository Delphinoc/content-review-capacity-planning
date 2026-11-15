import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capplan import params as P  # noqa: E402
from capplan.allocate import allocate  # noqa: E402
from capplan.capacity import (agents_needed, erlang_c_wait_prob, productive_hours_per_fte,  # noqa: E402
                              required_fte, service_level, simulate_backlog)
from capplan.forecast import backtest, forecast_all, score  # noqa: E402
from capplan.generate import generate_daily, to_weekly  # noqa: E402
from capplan.scenarios import build_plan  # noqa: E402


@pytest.fixture(scope="module")
def weekly():
    return to_weekly(generate_daily())


@pytest.fixture(scope="module")
def fc(weekly):
    return forecast_all(weekly)


def test_generation_is_reproducible_and_complete(weekly):
    again = to_weekly(generate_daily())
    pd.testing.assert_frame_equal(weekly, again)
    assert weekly.groupby("queue").size().eq(201).all()
    assert (weekly["items"] > 0).all()


def test_productive_hours():
    assert productive_hours_per_fte() == pytest.approx(40 * 0.70 * 0.85)


def test_required_fte_hand_calculation():
    # 100,000 items x 1.05 QA x 36 s = 1,050 h; / 23.8 productive h = 44.12 FTE
    assert required_fte(100_000, 36) == pytest.approx(1050 / 23.8)


def test_backlog_carries_over_and_flags_sla():
    sim = simulate_backlog(np.array([700.0, 700.0, 700.0]), np.array([600.0, 600.0, 800.0]))
    assert sim.backlog_h.tolist() == [100.0, 200.0, 100.0]
    # one day of work = 100 h; risk only when backlog > 1 day
    assert sim.sla_risk.tolist() == [False, True, False]


def test_erlang_c_textbook_value():
    # A = 10 Erlangs, N = 11 agents -> P(wait) ~ 0.682 (standard Erlang C table)
    assert erlang_c_wait_prob(11, 10.0) == pytest.approx(0.6821, abs=1e-3)
    assert erlang_c_wait_prob(10, 10.0) == 1.0


def test_agents_needed_meets_target_and_is_minimal():
    n = agents_needed(240, 6.0, 0.90, 5.0)
    traffic = 240 * 6 / 60
    assert service_level(n, traffic, 6.0, 5.0) >= 0.90
    assert service_level(n - 1, traffic, 6.0, 5.0) < 0.90


def test_forecast_beats_baselines_in_backtest(weekly):
    s = score(backtest(weekly, n_folds=2), by=None).iloc[0]
    assert s.wape_sarimax < s.wape_seasonal_naive_growth < s.wape_seasonal_naive
    assert s.wape_sarimax < 0.05


def test_forecast_shape_and_intervals(fc):
    assert len(fc) == P.HORIZON_WEEKS * len(P.QUEUES)
    assert ((fc.p10 <= fc.p50) & (fc.p50 <= fc.p90)).all()


def test_scenario_multipliers_apply(fc):
    base = build_plan(fc, "baseline").set_index(["queue", "horizon_week"])
    el = build_plan(fc, "election_spike").set_index(["queue", "horizon_week"])
    assert el.loc[("MY", 7), "items"] == pytest.approx(base.loc[("MY", 7), "items"] * 1.40)
    assert el.loc[("MY", 5), "items"] == pytest.approx(base.loc[("MY", 5), "items"])
    att = build_plan(fc, "attrition").set_index(["queue", "horizon_week"])
    assert att.loc[("ID", 4), "staffed_fte"] == pytest.approx(P.CURRENT_HC["ID"] * 0.92)


def test_allocation_respects_caps_and_clears_baseline(fc):
    plan = build_plan(fc, "baseline")
    alloc, summ = allocate(plan)
    assert summ["status"] == "Optimal"
    assert summ["sla_risk_queue_weeks_after"] == 0
    early_vendor = alloc[alloc.horizon_week <= P.VENDOR_LEAD_WEEKS].vendor_fte.sum()
    assert early_vendor == pytest.approx(0)
    early_hires = alloc[alloc.horizon_week <= P.HIRING_LEAD_WEEKS].new_hires_productive.sum()
    assert early_hires == 0
    staffed = plan.set_index(["queue", "horizon_week"]).staffed_fte
    ot_cap = P.OVERTIME_MAX_SHARE * staffed * P.CONTRACT_HOURS_PER_WEEK * P.UTILISATION / productive_hours_per_fte()
    a = alloc.set_index(["queue", "horizon_week"])
    assert (a.overtime_fte <= ot_cap + 1e-6).all()


def test_flex_cannot_go_negative_on_automation_gain(fc):
    _, summ = allocate(build_plan(fc, "automation_gain"))
    assert summ["flex_cost_fte_weeks"] == pytest.approx(0, abs=1e-6)
