"""All planning assumptions in one place.

Every value here is an ILLUSTRATIVE assumption for a synthetic content-review
operation. Nothing describes a real company's volumes, staffing or costs.
"""
from __future__ import annotations

SEED = 42

# History and planning horizon ------------------------------------------------
HISTORY_START = "2023-01-02"   # a Monday
HISTORY_END = "2026-11-08"     # a Sunday: last complete week before planning
HORIZON_WEEKS = 13             # one quarter ahead
HIRING_LEAD_WEEKS = 8          # recruit + onboarding + policy training before a hire is productive

# Review queues (one per market / language) -----------------------------------
# base_weekly: human-review items per week at HISTORY_START (after machine auto-actioning)
# growth: annual volume growth; aht_s: average handle time per item in seconds
QUEUES = {
    "ID": {"name": "Indonesia (Bahasa)", "base_weekly": 420_000, "growth": 0.12, "aht_s": 38},
    "TH": {"name": "Thailand (Thai)", "base_weekly": 230_000, "growth": 0.09, "aht_s": 41},
    "VN": {"name": "Vietnam (Vietnamese)", "base_weekly": 260_000, "growth": 0.11, "aht_s": 39},
    "PH": {"name": "Philippines (Tagalog/EN)", "base_weekly": 300_000, "growth": 0.10, "aht_s": 36},
    "MY": {"name": "Malaysia (Malay/EN)", "base_weekly": 120_000, "growth": 0.08, "aht_s": 37},
    "EN": {"name": "Global English", "base_weekly": 650_000, "growth": 0.07, "aht_s": 34},
}

# Reviewer productivity --------------------------------------------------------
CONTRACT_HOURS_PER_WEEK = 40.0
SHRINKAGE = 0.30        # leave, training, team meetings, wellness breaks (time paid but not reviewing)
UTILISATION = 0.85      # share of available time spent handling items (rest: system lag, short idle)
QA_RATE = 0.05          # share of items re-reviewed by quality auditors (adds workload)

# Current staffed headcount (FTE) entering the quarter: about 6% above the last
# 8 weeks' requirement, i.e. staffed for recent volume, not for the year-end peak.
CURRENT_HC = {"ID": 321, "TH": 172, "VN": 199, "PH": 204, "MY": 77, "EN": 407}

# Backlog / SLA ----------------------------------------------------------------
SLA_HOURS = 24          # items should be actioned within 24h of entering the queue
# A week is "SLA at risk" when the carried-over backlog exceeds one day of that week's workload.

# Flex levers used by the allocation model -------------------------------------
COST_PER_FTE_WEEK = 1.0            # cost unit: one in-house FTE-week = 1.0
OVERTIME_MAX_SHARE = 0.05          # overtime capped at 5% of staffed hours (reviewer wellbeing)
OVERTIME_COST_MULT = 1.5
VENDOR_QUEUES = {"ID": 40, "PH": 40, "EN": 60}   # queues a vendor can staff, with max FTE
VENDOR_LEAD_WEEKS = 2
VENDOR_COST_MULT = 1.3
# English-capable reviewers in EN can take the English-language share of these queues
CROSS_SKILL_SHARE = {"PH": 0.30, "MY": 0.25}
HIRE_MAX_PER_QUEUE = 40
UNMET_PENALTY = 10.0               # cost per unmet FTE-week (SLA breach), scaled by queue severity
QUEUE_SEVERITY = {"ID": 1.0, "TH": 1.0, "VN": 1.0, "PH": 1.0, "MY": 1.0, "EN": 1.0}

# Priority escalation queue (real-time, sized with Erlang C) --------------------
ESCALATION = {
    "peak_items_per_hour": 240,   # e.g. urgent live-stream reports at the evening peak
    "aht_min": 6.0,
    "service_level": 0.90,        # 90% picked up ...
    "target_wait_min": 5.0,       # ... within 5 minutes
}
# Share of the peak hourly arrival rate, by hour of day (0-23)
ESCALATION_HOURLY_PROFILE = [
    0.55, 0.45, 0.35, 0.30, 0.25, 0.25, 0.30, 0.40, 0.50, 0.55, 0.60, 0.65,
    0.70, 0.70, 0.65, 0.65, 0.70, 0.75, 0.85, 0.95, 1.00, 1.00, 0.90, 0.70,
]

# Known event calendar (used as forecast regressors) -----------------------------
# Approximate public dates. (start, end) inclusive; effect = volume uplift while active.
EVENTS = {
    "election": {
        "TH": [("2023-04-14", "2023-05-21")],
        "ID": [("2024-01-15", "2024-02-21")],
        "PH": [("2025-04-11", "2025-05-19")],
    },
    "ramadan": {  # evening usage rises in Muslim-majority markets
        "ID": [("2023-03-23", "2023-04-21"), ("2024-03-11", "2024-04-09"), ("2025-03-01", "2025-03-30"),
               ("2026-02-18", "2026-03-19"), ("2027-02-08", "2027-03-09")],
        "MY": [("2023-03-23", "2023-04-21"), ("2024-03-11", "2024-04-09"), ("2025-03-01", "2025-03-30"),
               ("2026-02-18", "2026-03-19"), ("2027-02-08", "2027-03-09")],
    },
    "tet": {
        "VN": [("2023-01-20", "2023-01-26"), ("2024-02-08", "2024-02-14"), ("2025-01-27", "2025-02-02"),
               ("2026-02-15", "2026-02-21"), ("2027-02-04", "2027-02-10")],
    },
    "songkran": {
        "TH": [("2023-04-12", "2023-04-16"), ("2024-04-12", "2024-04-16"), ("2025-04-12", "2025-04-16"),
               ("2026-04-12", "2026-04-16"), ("2027-04-12", "2027-04-16")],
    },
}
EVENT_UPLIFT = {"election": 0.35, "ramadan": 0.10, "tet": 0.15, "songkran": 0.12}

# One unannounced structural change in history: an EN policy update (Jul 2025)
# widened what gets sent to human review, a permanent +8% level shift.
POLICY_SHIFT = {"queue": "EN", "date": "2025-07-07", "uplift": 0.08}

# Scenarios for the coming quarter ------------------------------------------------
# Each scenario: per-queue volume multipliers and AHT multipliers for a range of
# horizon weeks (1-based, inclusive), plus shrinkage and headcount changes.
SCENARIOS = {
    "baseline": {"desc": "P50 forecast, current headcount"},
    "p90_volume": {"desc": "Volume at the forecast's 90th percentile in every week"},
    "election_spike": {
        "desc": "Snap election in Malaysia: MY +40% and EN +10% (regional English content) in weeks 6-10",
        "volume": [("MY", 6, 10, 1.40), ("EN", 6, 10, 1.10)],
    },
    "policy_update": {
        "desc": "New policy across all queues: AHT +15% for 6 weeks from week 3, "
                "plus +5pp shrinkage in weeks 3-4 for retraining",
        "aht": [("*", 3, 8, 1.15)],
        "shrinkage": [(3, 4, 0.05)],
    },
    "policy_update_phased": {
        "desc": "Same policy, phased: ID, PH, EN (vendor-supported queues) go live in week 3, "
                "TH, VN, MY in week 8; retraining shrinkage follows each wave",
        "aht": [("ID", 3, 8, 1.15), ("PH", 3, 8, 1.15), ("EN", 3, 8, 1.15),
                ("TH", 8, 13, 1.15), ("VN", 8, 13, 1.15), ("MY", 8, 13, 1.15)],
        "shrinkage_q": [("ID", 3, 4, 0.05), ("PH", 3, 4, 0.05), ("EN", 3, 4, 0.05),
                        ("TH", 8, 9, 0.05), ("VN", 8, 9, 0.05), ("MY", 8, 9, 0.05)],
    },
    "attrition": {
        "desc": "8% of reviewers in ID and VN leave by week 4 (backfills only land after the hiring lead time)",
        "hc": [("ID", 4, -0.08), ("VN", 4, -0.08)],
    },
    "automation_gain": {
        "desc": "Better machine pre-filtering removes 10% of human-review volume from week 5",
        "volume": [("*", 5, 13, 0.90)],
    },
}
