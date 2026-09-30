from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from babel.numbers import format_currency
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .settings import REPORT_DIR


def eur(value: float) -> str:
    return format_currency(value or 0, "EUR", locale="fr_FR")


def build_project_pdf(
    project_label: str,
    kpis: dict,
    tasks: pd.DataFrame,
    budget: pd.DataFrame,
    risks: pd.DataFrame | None = None,
) -> Path:
    safe_name = "".join(ch for ch in project_label if ch.isalnum() or ch in (" ", "-", "_")).strip().replace(" ", "_")
    output = REPORT_DIR / f"rapport_{safe_name}_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    doc = SimpleDocTemplate(str(output), pagesize=landscape(A4), rightMargin=1.2 * cm, leftMargin=1.2 * cm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"Rapport projet - {project_label}", styles["Title"]),
        Paragraph(f"Généré le {datetime.now():%d/%m/%Y %H:%M}", styles["Normal"]),
        Spacer(1, 0.35 * cm),
    ]

    kpi_rows = [
        ["Tâches", kpis.get("tasks", 0), "Avancement moyen", f"{kpis.get('progress', 0)}%"],
        ["Heures prévues", f"{kpis.get('planned_hours', 0):.1f}", "Heures passées", f"{kpis.get('actual_hours', 0):.1f}"],
        ["Budget prévu", eur(kpis.get("planned_budget", 0)), "Budget réel", eur(kpis.get("actual_budget", 0))],
        ["Tâches en retard", kpis.get("late_tasks", 0), "", ""],
    ]
    story.append(_styled_table(kpi_rows, [4 * cm, 4 * cm, 4 * cm, 4 * cm]))
    story.append(Spacer(1, 0.35 * cm))

    story.append(Paragraph("Tâches principales", styles["Heading2"]))
    task_cols = ["Référence", "Titre", "Budget", "Statut", "Temps prévu", "Temps passé", "Temps planifié", "Coût réel total"]
    story.append(
        _df_table(
            tasks[task_cols].head(20),
            widths=[2.2 * cm, 5.2 * cm, 4.4 * cm, 2.5 * cm, 2 * cm, 2 * cm, 2.2 * cm, 2.5 * cm],
        )
    )
    story.append(Spacer(1, 0.35 * cm))

    story.append(Paragraph("Budget", styles["Heading2"]))
    if not budget.empty:
        budget_cols = ["Référence", "Budget", "Prévu", "Engagé", "Reste"]
        story.append(_df_table(budget[budget_cols], widths=[4 * cm, 7 * cm, 3 * cm, 3 * cm, 3 * cm]))
    else:
        story.append(Paragraph("Aucune ligne budgétaire.", styles["Normal"]))

    risks = risks if risks is not None else pd.DataFrame()
    story.append(Spacer(1, 0.35 * cm))
    story.append(Paragraph("Gestion des risques", styles["Heading2"]))
    if risks.empty:
        story.append(Paragraph("Aucun risque enregistré.", styles["Normal"]))
    else:
        likelihoods = ["A", "B", "C", "D", "E"]
        consequences = [1, 2, 3, 4, 5]
        counts = {(likelihood, consequence): 0 for likelihood in likelihoods for consequence in consequences}
        for row in risks.to_dict("records"):
            key = (str(row.get("Vraisemblance courante", "")), int(row.get("Conséquence courante", 0) or 0))
            if key in counts:
                counts[key] += 1
        matrix_rows = [["Vrais. / Cons.", *consequences]] + [
            [likelihood, *[counts[(likelihood, consequence)] for consequence in consequences]]
            for likelihood in likelihoods
        ]
        matrix = Table(matrix_rows, colWidths=[3 * cm, *([1.6 * cm] * 5)])
        level_colors = {
            "Low": colors.HexColor("#dcfce7"),
            "Medium": colors.HexColor("#fef3c7"),
            "High": colors.HexColor("#fed7aa"),
            "Extreme": colors.HexColor("#fecaca"),
        }
        from .services import RISK_MATRIX

        matrix_style = [
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#172033")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]
        for row_index, likelihood in enumerate(likelihoods, start=1):
            for col_index, consequence in enumerate(consequences, start=1):
                matrix_style.append(("BACKGROUND", (col_index, row_index), (col_index, row_index), level_colors[RISK_MATRIX[likelihood][consequence - 1]]))
        matrix.setStyle(TableStyle(matrix_style))
        story.append(matrix)
        story.append(Spacer(1, 0.25 * cm))
        risk_cols = ["Référence", "Danger", "Niveau initial", "Niveau courant", "Acceptation"]
        story.append(_df_table(risks[risk_cols], widths=[4 * cm, 8 * cm, 3 * cm, 3 * cm, 4 * cm]))

    doc.build(story)
    return output


def _styled_table(rows: list[list], widths: list[float]) -> Table:
    table = Table(rows, colWidths=widths)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f7fb")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d8dde8")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ]
        )
    )
    return table


def _df_table(df: pd.DataFrame, widths: list[float]) -> Table:
    display = df.copy()
    for col in display.columns:
        if col in {"Prévu", "Engagé", "Réel", "Reste", "Coût réel total"}:
            display[col] = display[col].apply(eur)
        else:
            display[col] = display[col].astype(str)
    rows = [list(display.columns)] + display.values.tolist()
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#172033")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d8dde8")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ]
        )
    )
    return table
