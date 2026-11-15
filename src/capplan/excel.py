"""Write an editable Excel capacity model: inputs and scenario levers drive live formulas."""
from __future__ import annotations

import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import params as P

FONT = "Arial"
BLUE = Font(name=FONT, color="0000FF")
BLACK = Font(name=FONT)
GREEN = Font(name=FONT, color="008000")
BOLD = Font(name=FONT, bold=True)
HEAD = Font(name=FONT, bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", start_color="1F3864")
YELLOW = PatternFill("solid", start_color="FFFF00")
THIN = Border(bottom=Side(style="thin", color="BFBFBF"))


def _header(ws, row, values, col=1):
    for i, v in enumerate(values):
        c = ws.cell(row=row, column=col + i, value=v)
        c.font, c.fill = HEAD, HEAD_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def build_workbook(forecast: pd.DataFrame, path: str) -> None:
    queues = list(P.QUEUES)
    nq = len(queues)
    wb = Workbook()

    # ---- Inputs ------------------------------------------------------------
    ws = wb.active
    ws.title = "Inputs"
    ws["A1"] = "Content-review capacity model: inputs"
    ws["A1"].font = Font(name=FONT, bold=True, size=14)
    ws["A2"] = ("Edit blue cells (yellow = scenario levers). All values are illustrative assumptions "
                "for a synthetic operation; see Notes.")
    ws["A2"].font = Font(name=FONT, italic=True)

    glob = [
        ("Contracted hours per FTE per week", P.CONTRACT_HOURS_PER_WEEK, "0.0", "Standard full-time week"),
        ("Shrinkage", P.SHRINKAGE, "0.0%", "Leave, training, meetings, wellness breaks"),
        ("Utilisation", P.UTILISATION, "0.0%", "Share of available time spent handling items"),
        ("QA re-review rate", P.QA_RATE, "0.0%", "Share of items re-reviewed by quality auditors"),
        ("Volume case (P50 or P90)", "P50", "@", "P50 = median forecast; P90 = plan-for-risk case"),
        ("Shrinkage change (scenario, +pp)", 0.0, "0.0%", "e.g. 0.05 during a retraining fortnight"),
    ]
    ws["A4"], ws["B4"], ws["C4"] = "Global assumption", "Value", "Note"
    for c in ("A4", "B4", "C4"):
        ws[c].font, ws[c].fill = HEAD, HEAD_FILL
    for i, (label, val, fmt, note) in enumerate(glob, start=5):
        ws.cell(row=i, column=1, value=label).font = BLACK
        c = ws.cell(row=i, column=2, value=val)
        c.font, c.number_format = BLUE, fmt
        if i >= 9:
            c.fill = YELLOW
        ws.cell(row=i, column=3, value=note).font = Font(name=FONT, italic=True, color="595959")
    ws["B11"] = "=B5*(1-(B6+B10))*B7"
    ws["A11"] = "Productive hours per FTE per week"
    ws["B11"].number_format = "0.00"
    ws["A11"].font = ws["B11"].font = BOLD
    ws["C11"] = "Contract hours x (1 - shrinkage) x utilisation"
    ws["C11"].font = Font(name=FONT, italic=True, color="595959")

    _header(ws, 13, ["Queue", "Market / language", "AHT (seconds)", "Staffed FTE",
                     "Volume multiplier (scenario)", "AHT multiplier (scenario)"])
    ws.row_dimensions[13].height = 30
    q_row = {}
    for i, q in enumerate(queues, start=14):
        q_row[q] = i
        ws.cell(row=i, column=1, value=q).font = BOLD
        ws.cell(row=i, column=2, value=P.QUEUES[q]["name"]).font = BLACK
        for col, val, fmt in ((3, P.QUEUES[q]["aht_s"], "0"), (4, P.CURRENT_HC[q], "#,##0"),
                              (5, 1.0, '0.00"x"'), (6, 1.0, '0.00"x"')):
            c = ws.cell(row=i, column=col, value=val)
            c.font, c.number_format = BLUE, fmt
            if col >= 5:
                c.fill = YELLOW
    last_q = 13 + nq
    ws.cell(row=last_q + 1, column=1, value="Total").font = BOLD
    c = ws.cell(row=last_q + 1, column=4, value=f"=SUM(D14:D{last_q})")
    c.font, c.number_format = BOLD, "#,##0"
    ws["A22"] = ("Example: to test a snap election in Malaysia, set MY volume multiplier to 1.40 and EN to 1.10, "
                 "then read the Gap sheet.")
    ws["A22"].font = Font(name=FONT, italic=True)
    for col, w in zip("ABCDEF", (36, 26, 14, 12, 16, 16)):
        ws.column_dimensions[col].width = w

    # ---- Forecast (values from the Python model) -----------------------------
    wf = wb.create_sheet("Forecast")
    wf["A1"] = "Weekly human-review volume forecast (items). Source: SARIMAX model, scripts/run_all.py"
    wf["A1"].font = BOLD
    cols = ["Week (Mon)", "Horizon week"] + [f"{q} P50" for q in queues] + [f"{q} P90" for q in queues]
    _header(wf, 3, cols)
    piv50 = forecast.pivot(index="week", columns="queue", values="p50")[queues]
    piv90 = forecast.pivot(index="week", columns="queue", values="p90")[queues]
    for r, wk in enumerate(piv50.index, start=4):
        wf.cell(row=r, column=1, value=wk.date()).number_format = "dd-mmm-yy"
        wf.cell(row=r, column=2, value=r - 3)
        for j, q in enumerate(queues):
            for base, piv in ((3, piv50), (3 + nq, piv90)):
                c = wf.cell(row=r, column=base + j, value=round(float(piv.loc[wk, q])))
                c.font, c.number_format = BLUE, "#,##0"
    first, last = 4, 3 + len(piv50)
    wf.column_dimensions["A"].width = 12
    for j in range(3, 3 + 2 * nq):
        wf.column_dimensions[get_column_letter(j)].width = 11

    # ---- Required FTE (formulas) -----------------------------------------
    wr = wb.create_sheet("Required_FTE")
    wr["A1"] = ("Required FTE = items x vol. multiplier x (1 + QA) x AHT x AHT multiplier / 3600 "
                "/ productive hours per FTE")
    wr["A1"].font = BOLD
    _header(wr, 3, ["Week (Mon)", "Horizon week"] + queues + ["Total"])
    for r in range(first, last + 1):
        wr.cell(row=r, column=1, value=f"=Forecast!A{r}").number_format = "dd-mmm-yy"
        wr.cell(row=r, column=1).font = GREEN
        wr.cell(row=r, column=2, value=f"=Forecast!B{r}").font = GREEN
        for j, q in enumerate(queues):
            p50 = f"Forecast!{get_column_letter(3 + j)}{r}"
            p90 = f"Forecast!{get_column_letter(3 + nq + j)}{r}"
            qr = q_row[q]
            f = (f"=IF(Inputs!$B$9=\"P90\",{p90},{p50})*Inputs!$E${qr}*(1+Inputs!$B$8)"
                 f"*Inputs!$C${qr}*Inputs!$F${qr}/3600/Inputs!$B$11")
            c = wr.cell(row=r, column=3 + j, value=f)
            c.number_format = "#,##0.0"
        c = wr.cell(row=r, column=3 + nq, value=f"=SUM(C{r}:{get_column_letter(2 + nq)}{r})")
        c.font, c.number_format = BOLD, "#,##0.0"
    wr.column_dimensions["A"].width = 12

    # ---- Gap (formulas) ------------------------------------------------------
    wg = wb.create_sheet("Gap")
    wg["A1"] = "Staffed minus required FTE (negative = shortfall to cover with overtime, vendor or cross-skilling)"
    wg["A1"].font = BOLD
    _header(wg, 3, ["Week (Mon)", "Horizon week"] + queues + ["Total"])
    for r in range(first, last + 1):
        wg.cell(row=r, column=1, value=f"=Forecast!A{r}").number_format = "dd-mmm-yy"
        wg.cell(row=r, column=1).font = GREEN
        wg.cell(row=r, column=2, value=f"=Forecast!B{r}").font = GREEN
        for j, q in enumerate(queues):
            col = get_column_letter(3 + j)
            c = wg.cell(row=r, column=3 + j, value=f"=Inputs!$D${q_row[q]}-Required_FTE!{col}{r}")
            c.number_format = "#,##0.0;(#,##0.0);-"
        tcol = get_column_letter(3 + nq)
        c = wg.cell(row=r, column=3 + nq, value=f"=Inputs!$D${last_q + 1}-Required_FTE!{tcol}{r}")
        c.font, c.number_format = BOLD, "#,##0.0;(#,##0.0);-"
    rng = f"C{first}:{get_column_letter(3 + nq)}{last}"
    wg.conditional_formatting.add(rng, CellIsRule(operator="lessThan", formula=["0"],
                                                  fill=PatternFill("solid", start_color="F8CBAD")))
    s = last + 2
    labels = ["Worst-week shortfall (FTE)", "Weeks short (any queue total < 0)", "Average gap (FTE)"]
    for i, lab in enumerate(labels):
        wg.cell(row=s + i, column=1, value=lab).font = BOLD
    for j in range(nq + 1):
        col = get_column_letter(3 + j)
        r = f"{col}{first}:{col}{last}"
        c1 = wg.cell(row=s, column=3 + j, value=f"=MAX(0,-MIN({r}))")
        c2 = wg.cell(row=s + 1, column=3 + j, value=f"=COUNTIF({r},\"<0\")")
        c3 = wg.cell(row=s + 2, column=3 + j, value=f"=AVERAGE({r})")
        c1.number_format = c3.number_format = "#,##0.0;(#,##0.0);-"
        c2.number_format = "0"
    wg.column_dimensions["A"].width = 34

    # ---- Escalation (Erlang C, values) ---------------------------------------
    from .capacity import escalation_staffing
    esc, summ = escalation_staffing()
    we = wb.create_sheet("Escalation_ErlangC")
    we["A1"] = (f"Priority escalation queue: {P.ESCALATION['service_level']:.0%} of items picked up within "
                f"{P.ESCALATION['target_wait_min']:.0f} min, AHT {P.ESCALATION['aht_min']:.0f} min "
                "(Erlang C, computed in Python: src/capplan/capacity.py)")
    we["A1"].font = BOLD
    _header(we, 3, ["Hour", "Items per hour", "Workload (agents)", "Erlang C agents", "Occupancy", "Service level"])
    for i, row in esc.iterrows():
        r = 4 + i
        vals = (int(row.hour), row.items_per_hour, row.workload_agents, int(row.erlang_agents),
                row.occupancy, row.service_level)
        for j, (v, fmt) in enumerate(zip(vals, ("0", "#,##0", "0.0", "0", "0.0%", "0.0%"))):
            c = we.cell(row=r, column=1 + j, value=v)
            c.number_format, c.font = fmt, BLUE if j < 4 else BLACK
    endr = 4 + len(esc) - 1
    we.cell(row=endr + 2, column=1, value="Agent-hours per day").font = BOLD
    we.cell(row=endr + 2, column=3, value=f"=SUM(C4:C{endr})").number_format = "#,##0"
    we.cell(row=endr + 2, column=4, value=f"=SUM(D4:D{endr})").number_format = "#,##0"
    we.cell(row=endr + 3, column=1, value="Erlang C uplift vs workload-only").font = BOLD
    c = we.cell(row=endr + 3, column=4, value=f"=D{endr + 2}/C{endr + 2}-1")
    c.number_format = "0.0%"
    we.cell(row=endr + 4, column=1, value="FTE needed (7 days, after shrinkage)").font = BOLD
    c = we.cell(row=endr + 4, column=4, value=f"=D{endr + 2}*7/(Inputs!B5*(1-Inputs!B6))")
    c.number_format = "#,##0.0"
    c.comment = Comment("Scheduled agent-hours / (contract hours x (1 - shrinkage)). No utilisation factor: "
                        "Erlang C already builds in the idle time needed to meet the wait target.", "model")
    for col in "ABCDEF":
        we.column_dimensions[col].width = 16
    we.column_dimensions["A"].width = 34

    # ---- Notes ---------------------------------------------------------------
    wn = wb.create_sheet("Notes")
    notes = [
        "How to use",
        "1. Inputs: blue cells are assumptions; yellow cells are scenario levers (volume/AHT multipliers, "
        "volume case, shrinkage change).",
        "2. Forecast: weekly P50 and P90 volume from the Python SARIMAX model (values, re-run "
        "scripts/run_all.py to refresh).",
        "3. Required_FTE and Gap recalculate from Inputs. Red cells in Gap are shortfalls.",
        "4. Escalation_ErlangC: real-time priority queue sized with Erlang C (values from Python; totals are formulas).",
        "",
        "Colour code: blue = hardcoded input, black = formula, green = link to another sheet, yellow fill = lever.",
        "",
        "Caveat: every number is an illustrative assumption on synthetic data. The model shows the method, "
        "not any real company's operation.",
    ]
    for i, t in enumerate(notes, start=1):
        wn.cell(row=i, column=1, value=t).font = BOLD if i == 1 else BLACK
    wn.column_dimensions["A"].width = 120

    for sheet in wb.worksheets:
        sheet.freeze_panes = "C4" if sheet.title in ("Forecast", "Required_FTE", "Gap") else None
    wb.save(path)
