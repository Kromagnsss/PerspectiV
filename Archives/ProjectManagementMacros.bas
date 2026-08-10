Attribute VB_Name = "ProjectManagementMacros"
Option Explicit

' Macros à importer dans Gestion_Projets.xlsm si Excel signale que le projet VBA
' doit être recréé localement. Elles automatisent les usages prévus par le modèle.

Public Sub RecalculerTempsProjets()
    Application.CalculateFull
    MsgBox "Les temps passés ont été recalculés depuis l'onglet Suivi Temps.", vbInformation
End Sub

Public Sub AjouterProjet()
    Dim nomProjet As String, codeProjet As String, ws As Worksheet, recap As Worksheet, ligne As Long
    nomProjet = InputBox("Nom du nouvel onglet projet (ex: Projet_003)", "Ajouter un projet")
    If Len(nomProjet) = 0 Then Exit Sub
    codeProjet = InputBox("Code projet unique (ex: P003)", "Ajouter un projet")
    If Len(codeProjet) = 0 Then Exit Sub
    Worksheets("Projet_001").Copy After:=Worksheets(Worksheets.Count)
    Set ws = ActiveSheet
    ws.Name = nomProjet
    ws.Range("A1").Value = nomProjet
    ws.Range("A10:A60").Formula = codeProjet & "-" & "001"
    Set recap = Worksheets("Récap Projets")
    ligne = recap.Cells(recap.Rows.Count, 1).End(xlUp).Row + 1
    recap.Cells(ligne, 1).Value = codeProjet
    recap.Cells(ligne, 2).Value = nomProjet
    recap.Hyperlinks.Add Anchor:=recap.Cells(ligne, 6), Address:="", SubAddress:="'" & nomProjet & "'!A1", TextToDisplay:="Ouvrir"
End Sub

Public Sub DessinerDependancesGantt()
    MsgBox "Les dépendances sont stockées dans Parent et Prédécesseurs; utilisez-les pour tracer les flèches selon votre charte graphique Excel.", vbInformation
End Sub
