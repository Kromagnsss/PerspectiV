#!/usr/bin/env python3
"""Generate a macro-enabled project management workbook template.

The workbook is built with the Open XML format using only the Python standard
library so it can be regenerated in constrained environments.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import html

OUT = Path('Gestion_Projets.xlsm')

SHEETS = [
    ('Récap Projets', 'recap'),
    ('Utilisateurs', 'users'),
    ('Suivi Temps', 'time'),
    ('Listes', 'lists'),
    ('Projet_001', 'p001'),
    ('Projet_002', 'p002'),
]


def esc(v):
    return html.escape(str(v), quote=True)


def col(n):
    s = ''
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def cell_ref(r, c):
    return f'{col(c)}{r}'


def sheet_xml(rows, merges=None, validations=None, hyperlinks=None, cond_formats=None, widths=None, freeze=None):
    merges = merges or []
    validations = validations or []
    hyperlinks = hyperlinks or []
    cond_formats = cond_formats or []
    widths = widths or {}
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">']
    if widths:
        parts.append('<cols>')
        for c, w in widths.items():
            parts.append(f'<col min="{c}" max="{c}" width="{w}" customWidth="1"/>')
        parts.append('</cols>')
    if freeze:
        parts.append(f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{freeze}" topLeftCell="A{freeze+1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>')
    parts.append('<sheetData>')
    for r, row in enumerate(rows, 1):
        parts.append(f'<row r="{r}">')
        for c, value in enumerate(row, 1):
            if value is None:
                continue
            ref = cell_ref(r, c)
            style = 0
            formula = None
            if isinstance(value, tuple):
                value, style = value[0], value[1]
            if isinstance(value, str) and value.startswith('='):
                formula = value[1:]
                parts.append(f'<c r="{ref}" s="{style}"><f>{esc(formula)}</f></c>')
            elif isinstance(value, (int, float)):
                parts.append(f'<c r="{ref}" s="{style}"><v>{value}</v></c>')
            elif isinstance(value, date):
                serial = (value - date(1899, 12, 30)).days
                parts.append(f'<c r="{ref}" s="{style or 3}"><v>{serial}</v></c>')
            else:
                parts.append(f'<c r="{ref}" s="{style}" t="inlineStr"><is><t>{esc(value)}</t></is></c>')
        parts.append('</row>')
    parts.append('</sheetData>')
    if merges:
        parts.append(f'<mergeCells count="{len(merges)}">' + ''.join(f'<mergeCell ref="{m}"/>' for m in merges) + '</mergeCells>')
    if validations:
        parts.append(f'<dataValidations count="{len(validations)}">')
        for sqref, formula in validations:
            parts.append(f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" sqref="{sqref}"><formula1>{esc(formula)}</formula1></dataValidation>')
        parts.append('</dataValidations>')
    for sqref, formula, dxf in cond_formats:
        parts.append(f'<conditionalFormatting sqref="{sqref}"><cfRule type="expression" priority="1" dxfId="{dxf}"><formula>{esc(formula)}</formula></cfRule></conditionalFormatting>')
    if hyperlinks:
        parts.append('<hyperlinks>' + ''.join(f'<hyperlink ref="{ref}" location="{esc(loc)}" display="{esc(text)}"/>' for ref, loc, text in hyperlinks) + '</hyperlinks>')
    parts.append('<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>')
    return ''.join(parts)


def project_rows(project_id, project_name):
    start = date(2026, 7, 1)
    rows = [[(project_name, 1)], [], ['KPI', 'Valeur', 'Formule'],
            ['Avancement', '=IFERROR(AVERAGE($K$10:$K$60),0)', 'Moyenne avancement tâches'],
            ['Budget prévu', '=SUM($G$10:$G$60)', 'Somme coûts prévus'],
            ['Temps prévu', '=SUM($F$10:$F$60)', 'Somme heures prévues'],
            ['Temps passé', '=SUM($I$10:$I$60)', 'Somme injectée depuis Suivi Temps'],
            ['Tâches en retard', '=COUNTIFS($D$10:$D$60,"<"&TODAY(),$J$10:$J$60,"")', 'Fin estimée dépassée sans fin effective'],
            [],
            ['Réf.', 'Niveau', 'Parent', 'Tâche', 'Début', 'Fin estimée', 'Temps prévu (h)', 'Coût prévu', 'Ressources', 'Temps passé (h)', 'Fin effective', 'Avancement', 'Prédécesseurs', 'Notes']]
    tasks = [
        (1, '', 'Cadrage', 0, 10, 24, 3000, 'Alice Martin; Karim Benali', .7),
        (2, f'{project_id}-001', 'Kick-off', 0, 2, 6, 600, 'Alice Martin', 1),
        (3, f'{project_id}-002', 'Collecte besoins', 2, 5, 10, 1200, 'Karim Benali', .6),
        (4, f'{project_id}-003', 'Atelier métiers #1', 3, 4, 4, 500, 'Léa Dubois', .5),
        (1, '', 'Réalisation', 11, 35, 80, 12000, 'Alice Martin; Léa Dubois', .25),
        (2, f'{project_id}-005', 'Conception', 11, 18, 22, 3500, 'Léa Dubois', .4),
        (3, f'{project_id}-006', 'Développement lot 1', 18, 28, 36, 5200, 'Karim Benali', .2),
        (4, f'{project_id}-007', 'Paramétrage écran A', 20, 23, 12, 1500, 'Nina Rossi', .1),
        (1, '', 'Déploiement', 36, 48, 30, 4500, 'Nina Rossi', 0),
    ]
    for i, t in enumerate(tasks, 1):
        lvl, parent, name, off, dur, planned, cost, res, progress = t
        ref = f'{project_id}-{i:03d}'
        rows.append([ref, lvl, parent, name, start + timedelta(days=off), start + timedelta(days=off+dur), planned, cost, res,
                     f'=SUMIFS(\'Suivi Temps\'!$D:$D,\'Suivi Temps\'!$A:$A,"{ref}")', '', progress, '', ''])
    for i in range(len(tasks)+1, 52):
        rows.append([f'{project_id}-{i:03d}', '', '', '', '', '', '', '', '', f'=SUMIFS(\'Suivi Temps\'!$D:$D,\'Suivi Temps\'!$A:$A,"{project_id}-{i:03d}")', '', '', '', ''])
    gantt_start_col = 15
    dates = [start + timedelta(days=i) for i in range(60)]
    rows[8] += ['Gantt'] + dates
    for r in range(9, len(rows)):
        rows[r] += [''] + [f'=IF(AND({col(gantt_start_col+c)}$9>=$E{r+1},{col(gantt_start_col+c)}$9<=$F{r+1}),"■","")' for c in range(1, 61)]
    validations = [('B10:B60', 'Listes!$A$2:$A$5'), ('C10:C60', f'{project_name}!$A$10:$A$60'), ('I10:I60', 'Utilisateurs!$A$2:$A$100'), ('M10:M60', f'{project_name}!$A$10:$A$60')]
    widths = {1:12,2:8,3:12,4:28,5:12,6:14,7:14,8:12,9:24,10:15,11:14,12:12,13:16,14:24}
    for c in range(15, 76): widths[c] = 3
    cond = [('O10:BW60', f'AND(O$9>=$E10,O$9<=$F10)', 0)]
    return sheet_xml(rows, merges=['A1:N1'], validations=validations, cond_formats=cond, widths=widths, freeze=9)


def build():
    recap = [[('Gestion multi-projets',1)], [], ['ID Projet','Nom','Chef de projet','Statut','Onglet','Lien'],
             ['P001','Projet pilote','Alice Martin','En cours','Projet_001','Ouvrir'], ['P002','Projet client','Karim Benali','À lancer','Projet_002','Ouvrir']]
    users = [[('Utilisateurs',1)], [], ['Nom','Rôle','Taux horaire','Email'], ['Alice Martin','Chef de projet',95,'alice@example.com'], ['Karim Benali','Analyste',75,'karim@example.com'], ['Léa Dubois','Développeuse',80,'lea@example.com'], ['Nina Rossi','QA / Déploiement',70,'nina@example.com']]
    time = [[('Suivi des temps',1)], [], ['Réf. tâche','Utilisateur','Date','Heures effectives','Commentaire'], ['P001-002','Alice Martin',date(2026,7,2),3,'Kick-off'], ['P001-003','Karim Benali',date(2026,7,6),5,'Entretiens']]
    lists = [['Niveaux','Statuts','Aide'], [1,'À lancer','Les ressources utilisent une liste déroulante utilisateur; séparez plusieurs noms par ;'], [2,'En cours','Les temps passés sont calculés avec SUMIFS depuis Suivi Temps.'], [3,'Terminé','Les colonnes Parent et Prédécesseurs stockent les liens parent/enfant et dépendances Gantt.'], [4,'En retard','Ajoutez de nouveaux onglets projet en dupliquant un onglet Projet_XXX.']]
    files = {
        'xl/worksheets/sheet1.xml': sheet_xml(recap, merges=['A1:F1'], hyperlinks=[('F4', "'Projet_001'!A1", 'Ouvrir'), ('F5', "'Projet_002'!A1", 'Ouvrir')], widths={1:12,2:24,3:18,4:14,5:14,6:12}),
        'xl/worksheets/sheet2.xml': sheet_xml(users, merges=['A1:D1'], widths={1:24,2:22,3:14,4:24}),
        'xl/worksheets/sheet3.xml': sheet_xml(time, merges=['A1:E1'], validations=[('A4:A500', 'Listes!$E$2:$E$200'), ('B4:B500', 'Utilisateurs!$A$2:$A$100')], widths={1:14,2:24,3:12,4:18,5:40}),
        'xl/worksheets/sheet4.xml': sheet_xml(lists, widths={1:10,2:16,3:90}),
        'xl/worksheets/sheet5.xml': project_rows('P001','Projet_001'),
        'xl/worksheets/sheet6.xml': project_rows('P002','Projet_002'),
    }
    # append task reference list to Listes sheet via simple replacement
    refs = ''.join(f'<row r="{i+1}"><c r="E{i+1}" t="inlineStr"><is><t>{p}-{n:03d}</t></is></c></row>' for i,(p,n) in enumerate([(p,n) for p in ['P001','P002'] for n in range(1,61)],1))
    files['xl/worksheets/sheet4.xml'] = files['xl/worksheets/sheet4.xml'].replace('</sheetData>', refs + '</sheetData>')
    workbook = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + ''.join(f'<sheet name="{esc(n)}" sheetId="{i}" r:id="rId{i}"/>' for i,(n,_) in enumerate(SHEETS,1)) + '</sheets><calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>'
    rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    wb_rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,7)) + '<Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
    styles = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="16"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF5B9BD5"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="0" fillId="2" borderId="0" xfId="0"/><xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><dxfs count="1"><dxf><fill><patternFill patternType="solid"><fgColor rgb="FF70AD47"/></patternFill></fill></dxf></dxfs></styleSheet>'
    content = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.ms-excel.sheet.macroEnabled.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,7)) + '</Types>'
    with ZipFile(OUT, 'w', ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', content); z.writestr('_rels/.rels', rels); z.writestr('xl/workbook.xml', workbook); z.writestr('xl/_rels/workbook.xml.rels', wb_rels); z.writestr('xl/styles.xml', styles)
        for k,v in files.items(): z.writestr(k,v)

if __name__ == '__main__':
    build()
    print(f'Generated {OUT}')
