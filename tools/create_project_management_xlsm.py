#!/usr/bin/env python3
"""Generate a macro-enabled project management workbook template.

The workbook is built directly as an Open XML package with the Python standard
library so it can be regenerated in constrained environments.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import html

OUT = Path("Gestion_Projets.xlsm")

SHEETS = [
    ("Récap Projets", "recap"),
    ("Utilisateurs", "users"),
    ("Suivi Temps", "time"),
    ("Listes", "lists"),
    ("Projet_001", "p001"),
    ("Projet_002", "p002"),
]

TASK_FIRST_ROW = 11
TASK_LAST_ROW = 61
TIMELINE_ROW = 9
TIMELINE_START_COL = 16  # P
GANTT_DAYS = 60
GANTT_BLOCK = "\u25A0"


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def col(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def cell_ref(row: int, column: int) -> str:
    return f"{col(column)}{row}"


def sheet_extent(rows: list[list[object]]) -> str:
    max_row = max(len(rows), 1)
    max_col = 1
    for row in rows:
        for index, value in enumerate(row, 1):
            if value is not None and value != "":
                max_col = max(max_col, index)
    return f"A1:{cell_ref(max_row, max_col)}"


def styled_row(values: list[object], style: int) -> list[tuple[object, int]]:
    return [(value, style) for value in values]


def sheet_xml(
    rows: list[list[object]],
    merges: list[str] | None = None,
    validations: list[tuple[str, str]] | None = None,
    hyperlinks: list[tuple[str, str, str]] | None = None,
    cond_formats: list[tuple[str, str, int]] | None = None,
    widths: dict[int, int | float] | None = None,
    freeze: int | None = None,
) -> str:
    merges = merges or []
    validations = validations or []
    hyperlinks = hyperlinks or []
    cond_formats = cond_formats or []
    widths = widths or {}

    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
        f'<dimension ref="{sheet_extent(rows)}"/>',
        '<sheetViews><sheetView workbookViewId="0">',
    ]
    if freeze:
        parts.append(
            f'<pane ySplit="{freeze}" topLeftCell="A{freeze + 1}" '
            'activePane="bottomLeft" state="frozen"/>'
            f'<selection pane="bottomLeft" activeCell="A{freeze + 1}" sqref="A{freeze + 1}"/>'
        )
    parts.append("</sheetView></sheetViews>")
    parts.append('<sheetFormatPr defaultRowHeight="15"/>')

    if widths:
        parts.append("<cols>")
        for column, width in sorted(widths.items()):
            parts.append(f'<col min="{column}" max="{column}" width="{width}" customWidth="1"/>')
        parts.append("</cols>")

    parts.append("<sheetData>")
    for row_number, row in enumerate(rows, 1):
        parts.append(f'<row r="{row_number}">')
        for column_number, raw_value in enumerate(row, 1):
            if raw_value is None or raw_value == "":
                continue

            value = raw_value
            style = 0
            if isinstance(raw_value, tuple):
                value, style = raw_value
                if value is None or value == "":
                    continue

            ref = cell_ref(row_number, column_number)
            if isinstance(value, str) and value.startswith("="):
                parts.append(f'<c r="{ref}" s="{style}"><f>{esc(value[1:])}</f></c>')
            elif isinstance(value, (int, float)):
                parts.append(f'<c r="{ref}" s="{style}"><v>{value}</v></c>')
            elif isinstance(value, date):
                serial = (value - date(1899, 12, 30)).days
                parts.append(f'<c r="{ref}" s="{style or 3}"><v>{serial}</v></c>')
            else:
                parts.append(f'<c r="{ref}" s="{style}" t="inlineStr"><is><t>{esc(value)}</t></is></c>')
        parts.append("</row>")
    parts.append("</sheetData>")

    if merges:
        parts.append(f'<mergeCells count="{len(merges)}">')
        parts.extend(f'<mergeCell ref="{merge}"/>' for merge in merges)
        parts.append("</mergeCells>")

    for sqref, formula, dxf in cond_formats:
        parts.append(
            f'<conditionalFormatting sqref="{sqref}">'
            f'<cfRule type="expression" priority="1" dxfId="{dxf}">'
            f"<formula>{esc(formula)}</formula>"
            "</cfRule></conditionalFormatting>"
        )

    if validations:
        parts.append(f'<dataValidations count="{len(validations)}">')
        for sqref, formula in validations:
            parts.append(
                '<dataValidation type="list" allowBlank="1" showErrorMessage="1" '
                f'sqref="{sqref}"><formula1>{esc(formula)}</formula1></dataValidation>'
            )
        parts.append("</dataValidations>")

    if hyperlinks:
        parts.append("<hyperlinks>")
        parts.extend(
            f'<hyperlink ref="{ref}" location="{esc(location)}" display="{esc(text)}"/>'
            for ref, location, text in hyperlinks
        )
        parts.append("</hyperlinks>")

    parts.append(
        '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" '
        'header="0.3" footer="0.3"/></worksheet>'
    )
    return "".join(parts)


def project_rows(project_id: str, project_name: str) -> str:
    start = date(2026, 7, 1)
    rows: list[list[object]] = [
        [(project_name, 1)],
        [],
        styled_row(["KPI", "Valeur", "Formule"], 2),
        ["Avancement", f"=IFERROR(AVERAGE($L${TASK_FIRST_ROW}:$L${TASK_LAST_ROW}),0)", "Moyenne avancement tâches"],
        ["Budget prévu", f"=SUM($H${TASK_FIRST_ROW}:$H${TASK_LAST_ROW})", "Somme coûts prévus"],
        ["Temps prévu", f"=SUM($G${TASK_FIRST_ROW}:$G${TASK_LAST_ROW})", "Somme heures prévues"],
        ["Temps passé", f"=SUM($J${TASK_FIRST_ROW}:$J${TASK_LAST_ROW})", "Somme injectée depuis Suivi Temps"],
        [
            "Tâches en retard",
            f'=COUNTIFS($F${TASK_FIRST_ROW}:$F${TASK_LAST_ROW},"<"&TODAY(),$K${TASK_FIRST_ROW}:$K${TASK_LAST_ROW},"")',
            "Fin estimée dépassée sans fin effective",
        ],
        [None] * 14 + [("Gantt", 2)] + [start + timedelta(days=i) for i in range(GANTT_DAYS)],
        styled_row(
            [
                "Réf.",
                "Niveau",
                "Parent",
                "Tâche",
                "Début",
                "Fin estimée",
                "Temps prévu (h)",
                "Coût prévu",
                "Ressources",
                "Temps passé (h)",
                "Fin effective",
                "Avancement",
                "Prédécesseurs",
                "Notes",
            ],
            2,
        ),
    ]

    tasks = [
        (1, "", "Cadrage", 0, 10, 24, 3000, "Alice Martin; Karim Benali", 0.70),
        (2, f"{project_id}-001", "Kick-off", 0, 2, 6, 600, "Alice Martin", 1.00),
        (3, f"{project_id}-002", "Collecte besoins", 2, 5, 10, 1200, "Karim Benali", 0.60),
        (4, f"{project_id}-003", "Atelier métiers #1", 3, 4, 4, 500, "Léa Dubois", 0.50),
        (1, "", "Réalisation", 11, 35, 80, 12000, "Alice Martin; Léa Dubois", 0.25),
        (2, f"{project_id}-005", "Conception", 11, 18, 22, 3500, "Léa Dubois", 0.40),
        (3, f"{project_id}-006", "Développement lot 1", 18, 28, 36, 5200, "Karim Benali", 0.20),
        (4, f"{project_id}-007", "Paramétrage écran A", 20, 23, 12, 1500, "Nina Rossi", 0.10),
        (1, "", "Déploiement", 36, 48, 30, 4500, "Nina Rossi", 0.00),
    ]

    for index, task in enumerate(tasks, 1):
        level, parent, name, offset, duration, planned, cost, resources, progress = task
        ref = f"{project_id}-{index:03d}"
        rows.append(
            [
                ref,
                level,
                parent,
                name,
                start + timedelta(days=offset),
                start + timedelta(days=offset + duration),
                planned,
                cost,
                resources,
                f'=SUMIFS(\'Suivi Temps\'!$D:$D,\'Suivi Temps\'!$A:$A,"{ref}")',
                "",
                progress,
                "",
                "",
            ]
        )

    for index in range(len(tasks) + 1, TASK_LAST_ROW - TASK_FIRST_ROW + 2):
        ref = f"{project_id}-{index:03d}"
        rows.append(
            [
                ref,
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                f'=SUMIFS(\'Suivi Temps\'!$D:$D,\'Suivi Temps\'!$A:$A,"{ref}")',
                "",
                "",
                "",
                "",
            ]
        )

    for row_number in range(TASK_FIRST_ROW, TASK_LAST_ROW + 1):
        formulas = []
        for offset in range(GANTT_DAYS):
            timeline_col = col(TIMELINE_START_COL + offset)
            formulas.append(
                f'=IF(AND($E{row_number}<>"",$F{row_number}<>"",'
                f'{timeline_col}${TIMELINE_ROW}>=$E{row_number},'
                f'{timeline_col}${TIMELINE_ROW}<=$F{row_number}),"{GANTT_BLOCK}","")'
            )
        rows[row_number - 1] += [None] + formulas

    validations = [
        (f"B{TASK_FIRST_ROW}:B{TASK_LAST_ROW}", "Listes!$A$2:$A$5"),
        (f"C{TASK_FIRST_ROW}:C{TASK_LAST_ROW}", f"{project_name}!$A${TASK_FIRST_ROW}:$A${TASK_LAST_ROW}"),
        (f"I{TASK_FIRST_ROW}:I{TASK_LAST_ROW}", "Utilisateurs!$A$2:$A$100"),
        (f"M{TASK_FIRST_ROW}:M{TASK_LAST_ROW}", f"{project_name}!$A${TASK_FIRST_ROW}:$A${TASK_LAST_ROW}"),
    ]
    widths = {
        1: 12,
        2: 8,
        3: 12,
        4: 28,
        5: 12,
        6: 14,
        7: 14,
        8: 12,
        9: 24,
        10: 15,
        11: 14,
        12: 12,
        13: 16,
        14: 24,
        15: 3,
    }
    for column in range(TIMELINE_START_COL, TIMELINE_START_COL + GANTT_DAYS):
        widths[column] = 3

    last_gantt_col = col(TIMELINE_START_COL + GANTT_DAYS - 1)
    cond_formats = [
        (
            f"{col(TIMELINE_START_COL)}{TASK_FIRST_ROW}:{last_gantt_col}{TASK_LAST_ROW}",
            f'AND($E{TASK_FIRST_ROW}<>"",$F{TASK_FIRST_ROW}<>"",{col(TIMELINE_START_COL)}${TIMELINE_ROW}>=$E{TASK_FIRST_ROW},{col(TIMELINE_START_COL)}${TIMELINE_ROW}<=$F{TASK_FIRST_ROW})',
            0,
        )
    ]
    return sheet_xml(
        rows,
        merges=["A1:N1"],
        validations=validations,
        cond_formats=cond_formats,
        widths=widths,
        freeze=10,
    )


def lists_rows() -> list[list[object]]:
    help_rows: list[list[object]] = [
        styled_row(["Niveaux", "Statuts", "Aide"], 2),
        [1, "À lancer", "Les ressources utilisent une liste déroulante utilisateur; séparez plusieurs noms par ;"],
        [2, "En cours", "Les temps passés sont calculés avec SUMIFS depuis Suivi Temps."],
        [3, "Terminé", "Les colonnes Parent et Prédécesseurs stockent les liens parent/enfant et dépendances Gantt."],
        [4, "En retard", "Ajoutez de nouveaux onglets projet en dupliquant un onglet Projet_XXX."],
    ]
    refs = [f"{project}-{number:03d}" for project in ["P001", "P002"] for number in range(1, 61)]
    row_count = max(len(help_rows), len(refs) + 1)
    rows: list[list[object]] = []
    for index in range(row_count):
        row = list(help_rows[index]) if index < len(help_rows) else [None, None, None]
        row.append(None)
        if index == 0:
            row.append(("Réf. tâches", 2))
        elif index - 1 < len(refs):
            row.append(refs[index - 1])
        rows.append(row)
    return rows


def workbook_xml() -> str:
    sheets_xml = "".join(
        f'<sheet name="{esc(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, (name, _) in enumerate(SHEETS, 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<workbookViews><workbookView activeTab="0"/></workbookViews>'
        f'<sheets>{sheets_xml}</sheets>'
        '<calcPr calcId="191029" fullCalcOnLoad="1"/>'
        '</workbook>'
    )


def styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="3">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="16"/><name val="Calibri"/></font>'
        '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="4">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/></patternFill></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF70AD47"/></patternFill></fill>'
        '</fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="4">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        '<xf numFmtId="0" fontId="2" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
        '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '<dxfs count="1"><dxf><fill><patternFill patternType="solid">'
        '<fgColor rgb="FF70AD47"/></patternFill></fill></dxf></dxfs>'
        '<tableStyles count="0" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleLight16"/>'
        '</styleSheet>'
    )


def build() -> None:
    recap = [
        [("Gestion multi-projets", 1)],
        [],
        styled_row(["ID Projet", "Nom", "Chef de projet", "Statut", "Onglet", "Lien"], 2),
        ["P001", "Projet pilote", "Alice Martin", "En cours", "Projet_001", "Ouvrir"],
        ["P002", "Projet client", "Karim Benali", "À lancer", "Projet_002", "Ouvrir"],
    ]
    users = [
        [("Utilisateurs", 1)],
        [],
        styled_row(["Nom", "Rôle", "Taux horaire", "Email"], 2),
        ["Alice Martin", "Chef de projet", 95, "alice@example.com"],
        ["Karim Benali", "Analyste", 75, "karim@example.com"],
        ["Léa Dubois", "Développeuse", 80, "lea@example.com"],
        ["Nina Rossi", "QA / Déploiement", 70, "nina@example.com"],
    ]
    time = [
        [("Suivi des temps", 1)],
        [],
        styled_row(["Réf. tâche", "Utilisateur", "Date", "Heures effectives", "Commentaire"], 2),
        ["P001-002", "Alice Martin", date(2026, 7, 2), 3, "Kick-off"],
        ["P001-003", "Karim Benali", date(2026, 7, 6), 5, "Entretiens"],
    ]

    files = {
        "xl/worksheets/sheet1.xml": sheet_xml(
            recap,
            merges=["A1:F1"],
            hyperlinks=[("F4", "'Projet_001'!A1", "Ouvrir"), ("F5", "'Projet_002'!A1", "Ouvrir")],
            widths={1: 12, 2: 24, 3: 18, 4: 14, 5: 14, 6: 12},
        ),
        "xl/worksheets/sheet2.xml": sheet_xml(users, merges=["A1:D1"], widths={1: 24, 2: 22, 3: 14, 4: 24}),
        "xl/worksheets/sheet3.xml": sheet_xml(
            time,
            merges=["A1:E1"],
            validations=[("A4:A500", "Listes!$E$2:$E$200"), ("B4:B500", "Utilisateurs!$A$2:$A$100")],
            widths={1: 14, 2: 24, 3: 12, 4: 18, 5: 40},
        ),
        "xl/worksheets/sheet4.xml": sheet_xml(lists_rows(), widths={1: 10, 2: 16, 3: 90, 5: 14}),
        "xl/worksheets/sheet5.xml": project_rows("P001", "Projet_001"),
        "xl/worksheets/sheet6.xml": project_rows("P002", "Projet_002"),
    }

    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
            for index in range(1, 7)
        )
        + '<Relationship Id="rId7" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        '</Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.ms-excel.sheet.macroEnabled.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for index in range(1, 7)
        )
        + '</Types>'
    )

    with ZipFile(OUT, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("xl/workbook.xml", workbook_xml())
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/styles.xml", styles_xml())
        for path, payload in files.items():
            archive.writestr(path, payload)


if __name__ == "__main__":
    build()
    print(f"Generated {OUT}")
