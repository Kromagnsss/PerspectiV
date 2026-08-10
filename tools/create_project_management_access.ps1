param(
    [string]$TemplatePath = "C:\Users\111624\Downloads\MSDBP.accdb",
    [string]$OutputPath = "C:\Users\111624\Downloads\PerspectiV\PerspectiV\Gestion_Projets_Access.accdb"
)

$ErrorActionPreference = "Stop"

$dbText = 10
$dbByte = 2
$dbLong = 4
$dbCurrency = 5
$dbDouble = 7
$dbDate = 8
$dbMemo = 12
$dbFailOnError = 128

$acTable = 0
$acQuery = 1
$acForm = 2
$acModule = 5
$acDesign = 1
$acDetail = 0
$acSaveYes = 1
$acLabel = 100
$acCommandButton = 104
$acTextBox = 109
$acComboBox = 111
$acSubform = 112
$acPage = 124

function Test-TableExists {
    param($Database, [string]$Name)
    try {
        $null = $Database.TableDefs.Item($Name)
        return $true
    } catch {
        return $false
    }
}

function Test-FieldExists {
    param($TableDef, [string]$Name)
    try {
        $null = $TableDef.Fields.Item($Name)
        return $true
    } catch {
        return $false
    }
}

function Test-QueryExists {
    param($Database, [string]$Name)
    try {
        $null = $Database.QueryDefs.Item($Name)
        return $true
    } catch {
        return $false
    }
}

function Test-IndexExists {
    param($TableDef, [string]$Name)
    try {
        $null = $TableDef.Indexes.Item($Name)
        return $true
    } catch {
        return $false
    }
}

function Test-RelationExists {
    param($Database, [string]$Name)
    try {
        $null = $Database.Relations.Item($Name)
        return $true
    } catch {
        return $false
    }
}

function Invoke-DaoSql {
    param($Database, [string]$Sql)
    $Database.Execute($Sql, $dbFailOnError)
}

function Add-FieldIfMissing {
    param(
        $Database,
        [string]$TableName,
        [string]$FieldName,
        [int]$Type,
        [int]$Size = 0,
        [string]$DefaultValue = $null,
        [string]$ValidationRule = $null,
        [string]$ValidationText = $null
    )

    $table = $Database.TableDefs.Item($TableName)
    if (Test-FieldExists $table $FieldName) {
        return
    }

    if ($Size -gt 0) {
        $field = $table.CreateField($FieldName, $Type, $Size)
    } else {
        $field = $table.CreateField($FieldName, $Type)
    }

    if ($null -ne $DefaultValue) {
        $field.DefaultValue = $DefaultValue
    }
    if ($ValidationRule) {
        $field.ValidationRule = $ValidationRule
    }
    if ($ValidationText) {
        $field.ValidationText = $ValidationText
    }

    $table.Fields.Append($field)
    $table.Fields.Refresh()
}

function Add-IndexIfMissing {
    param(
        $Database,
        [string]$TableName,
        [string]$IndexName,
        [string[]]$Fields,
        [bool]$Unique = $false
    )

    $table = $Database.TableDefs.Item($TableName)
    if (Test-IndexExists $table $IndexName) {
        return
    }

    $index = $table.CreateIndex($IndexName)
    $index.Unique = $Unique
    foreach ($fieldName in $Fields) {
        $index.Fields.Append($index.CreateField($fieldName))
    }
    $table.Indexes.Append($index)
    $table.Indexes.Refresh()
}

function Add-RelationIfMissing {
    param(
        $Database,
        [string]$RelationName,
        [string]$PrimaryTable,
        [string]$ForeignTable,
        [string]$PrimaryField,
        [string]$ForeignField
    )

    if (Test-RelationExists $Database $RelationName) {
        return
    }

    $relation = $Database.CreateRelation($RelationName, $PrimaryTable, $ForeignTable, 0)
    $field = $relation.CreateField($PrimaryField)
    $field.ForeignName = $ForeignField
    $relation.Fields.Append($field)
    $Database.Relations.Append($relation)
    $Database.Relations.Refresh()
}

function Set-PropertySafe {
    param($Object, [string]$Name, $Value)
    try {
        $Object.$Name = $Value
    } catch {
        # Some Access properties are unavailable until the object is saved or shown.
    }
}

function Add-TextControl {
    param(
        $Access,
        [string]$FormName,
        [string]$Name,
        [string]$ControlSource,
        [int]$Left,
        [int]$Top,
        [int]$Width,
        [int]$Height = 300,
        [string]$Format = $null,
        [string]$FontName = $null,
        [bool]$Locked = $false
    )

    $control = $Access.CreateControl($FormName, $acTextBox, $acDetail, $null, $ControlSource, $Left, $Top, $Width, $Height)
    $control.Name = $Name
    $control.ControlSource = $ControlSource
    if ($Format) { $control.Format = $Format }
    if ($FontName) { $control.FontName = $FontName }
    if ($Locked) { $control.Locked = $true }
    Set-PropertySafe $control "ColumnWidth" $Width
    return $control
}

function Add-ComboControl {
    param(
        $Access,
        [string]$FormName,
        [string]$Name,
        [string]$ControlSource,
        [string]$RowSource,
        [int]$Left,
        [int]$Top,
        [int]$Width,
        [int]$Height = 300,
        [string]$ColumnWidths = "0;2880"
    )

    $control = $Access.CreateControl($FormName, $acComboBox, $acDetail, $null, $ControlSource, $Left, $Top, $Width, $Height)
    $control.Name = $Name
    $control.ControlSource = $ControlSource
    $control.RowSourceType = "Table/Query"
    $control.RowSource = $RowSource
    $control.ColumnCount = 2
    $control.ColumnWidths = $ColumnWidths
    $control.BoundColumn = 1
    $control.LimitToList = $true
    Set-PropertySafe $control "AutoExpand" $true
    Set-PropertySafe $control "ColumnWidth" $Width
    return $control
}

function Remove-FormIfExists {
    param($Access, [string]$Name)
    try { $Access.DoCmd.Close($acForm, $Name, 0) } catch {}
    try { $Access.DoCmd.DeleteObject($acForm, $Name) } catch {}
}

function New-DatasheetForm {
    param(
        $Access,
        [string]$Name,
        [string]$RecordSource,
        [string]$Caption,
        [object[]]$Columns,
        [string]$AfterUpdateExpression = $null,
        [string]$AfterInsertExpression = $null
    )

    Remove-FormIfExists $Access $Name

    $form = $Access.CreateForm()
    $createdName = $form.Name
    $form.Caption = $Caption
    $form.RecordSource = $RecordSource
    $form.DefaultView = 2
    Set-PropertySafe $form "AllowDatasheetView" $true
    Set-PropertySafe $form "AllowFormView" $true
    Set-PropertySafe $form "NavigationButtons" $true
    Set-PropertySafe $form "DividingLines" $true
    Set-PropertySafe $form "ScrollBars" 2
    if ($AfterUpdateExpression) { Set-PropertySafe $form "AfterUpdate" $AfterUpdateExpression }
    if ($AfterInsertExpression) { Set-PropertySafe $form "AfterInsert" $AfterInsertExpression }

    $left = 0
    foreach ($column in $Columns) {
        $width = [int]$column.Width
        if ($column.Kind -eq "combo") {
            $control = Add-ComboControl $Access $createdName $column.Name $column.Source $column.RowSource $left 0 $width 300 $column.ColumnWidths
        } else {
            $control = Add-TextControl $Access $createdName $column.Name $column.Source $left 0 $width 300 $column.Format $column.FontName ([bool]$column.Locked)
        }
        if ($column.Caption) {
            Set-PropertySafe $control "DatasheetCaption" $column.Caption
        }
        if ($column.DefaultValue) {
            Set-PropertySafe $control "DefaultValue" $column.DefaultValue
        }
        $left += $width
    }

    $Access.DoCmd.Save($acForm, $createdName)
    $Access.DoCmd.Close($acForm, $createdName, $acSaveYes)
    $Access.DoCmd.Rename($Name, $acForm, $createdName)
}

function Get-Scalar {
    param($Database, [string]$Sql)
    $rs = $Database.OpenRecordset($Sql)
    try {
        if ($rs.EOF) { return $null }
        return $rs.Fields.Item(0).Value
    } finally {
        $rs.Close()
    }
}

function Add-ProjectIfMissing {
    param(
        $Database,
        [string]$ProjectName,
        [datetime]$StartDate,
        [datetime]$EndDate,
        [int]$OwnerId
    )

    $existing = Get-Scalar $Database "SELECT [ID] FROM [Projets] WHERE [Nom du projet]='$($ProjectName.Replace("'","''"))'"
    if ($null -ne $existing) {
        return [int]$existing
    }

    $rs = $Database.OpenRecordset("Projets", 2)
    try {
        $rs.AddNew()
        $rs.Fields.Item("Nom du projet").Value = $ProjectName
        $rs.Fields.Item("Propriétaire").Value = $OwnerId
        $rs.Fields.Item("Catégorie").Value = "(1) Catégorie"
        $rs.Fields.Item("Priorité").Value = "(2) Normale"
        $rs.Fields.Item("Statut").Value = "En cours"
        $rs.Fields.Item("Date de début").Value = $StartDate
        $rs.Fields.Item("Date de fin").Value = $EndDate
        $rs.Fields.Item("Budget en jours").Value = 45
        $rs.Fields.Item("Budget").Value = 38000
        $rs.Fields.Item("Remarques").Value = "Projet exemple ajouté par le générateur Access."
        $rs.Update()
        $rs.Bookmark = $rs.LastModified
        return [int]$rs.Fields.Item("ID").Value
    } finally {
        $rs.Close()
    }
}

function Add-Task {
    param(
        $Database,
        [int]$ProjectId,
        [string]$Title,
        [int]$Level,
        [Nullable[int]]$ParentId,
        [datetime]$StartDate,
        [datetime]$EndDate,
        [double]$PlannedHours,
        [double]$PlannedCost,
        [int]$Order,
        [int]$AssignedTo
    )

    $rs = $Database.OpenRecordset("Tâches", 2)
    try {
        $rs.AddNew()
        $rs.Fields.Item("Projet").Value = $ProjectId
        $rs.Fields.Item("Référence").Value = [string]("TMP-{0}" -f ([guid]::NewGuid().ToString("N").Substring(0, 20)))
        $rs.Fields.Item("Titre").Value = $Title
        $rs.Fields.Item("Niveau").Value = $Level
        if ($ParentId.HasValue) { $rs.Fields.Item("Tâche parente").Value = $ParentId.Value }
        $rs.Fields.Item("Début").Value = $StartDate
        $rs.Fields.Item("Échéance").Value = $EndDate
        $rs.Fields.Item("Temps prévu").Value = $PlannedHours
        $rs.Fields.Item("Coût prévu").Value = $PlannedCost
        $rs.Fields.Item("Coût").Value = $PlannedCost
        $rs.Fields.Item("Coût en jours").Value = [double]([math]::Round($PlannedHours / 8, 2))
        $rs.Fields.Item("Statut").Value = "En cours"
        $rs.Fields.Item("Priorité").Value = "(2) Normale"
        $rs.Fields.Item("% achevé").Value = 0
        $rs.Fields.Item("Ordre").Value = $Order
        $rs.Fields.Item("Affecté à").Value = $AssignedTo
        $rs.Update()
        $rs.Bookmark = $rs.LastModified
        $taskId = [int]$rs.Fields.Item("ID").Value
        return $taskId
    } finally {
        $rs.Close()
    }
}

function Add-ResourceAssignment {
    param($Database, [int]$TaskId, [int]$EmployeeId, [string]$Role, [double]$Hours)
    $rs = $Database.OpenRecordset("Ressources des tâches", 2)
    try {
        $rs.AddNew()
        $rs.Fields.Item("Tâche").Value = $TaskId
        $rs.Fields.Item("Employé").Value = $EmployeeId
        $rs.Fields.Item("Rôle").Value = $Role
        $rs.Fields.Item("Charge prévue heures").Value = $Hours
        $rs.Update()
    } finally {
        $rs.Close()
    }
}

function Add-TimeEntry {
    param($Database, [int]$ProjectId, [int]$TaskId, [int]$EmployeeId, [datetime]$EntryDate, [double]$Hours, [string]$Comment)
    $rs = $Database.OpenRecordset("Suivi des temps", 2)
    try {
        $rs.AddNew()
        $rs.Fields.Item("Date saisie").Value = $EntryDate
        $rs.Fields.Item("Projet").Value = $ProjectId
        $rs.Fields.Item("Tâche").Value = $TaskId
        $rs.Fields.Item("Employé").Value = $EmployeeId
        $rs.Fields.Item("Heures").Value = $Hours
        $rs.Fields.Item("Commentaire").Value = $Comment
        $rs.Update()
    } finally {
        $rs.Close()
    }
}

function Add-Dependency {
    param($Database, [int]$PredecessorId, [int]$SuccessorId, [string]$Type, [int]$LagDays)
    $rs = $Database.OpenRecordset("Dépendances des tâches", 2)
    try {
        $rs.AddNew()
        $rs.Fields.Item("Prédécesseur").Value = $PredecessorId
        $rs.Fields.Item("Successeur").Value = $SuccessorId
        $rs.Fields.Item("Type de lien").Value = $Type
        $rs.Fields.Item("Décalage jours").Value = $LagDays
        $rs.Update()
    } finally {
        $rs.Close()
    }
}

if (!(Test-Path -LiteralPath $TemplatePath)) {
    throw "Template introuvable : $TemplatePath"
}

Copy-Item -LiteralPath $TemplatePath -Destination $OutputPath -Force

$dbe = New-Object -ComObject DAO.DBEngine.120
$db = $dbe.OpenDatabase($OutputPath)

try {
    Add-FieldIfMissing $db "Tâches" "Référence" $dbText 30
    Add-FieldIfMissing $db "Tâches" "Niveau" $dbByte 0 "1" "Between 1 And 4" "Le niveau doit être compris entre 1 et 4."
    Add-FieldIfMissing $db "Tâches" "Tâche parente" $dbLong
    Add-FieldIfMissing $db "Tâches" "Ordre" $dbLong 0 "0"
    Add-FieldIfMissing $db "Tâches" "Temps prévu" $dbDouble 0 "0"
    Add-FieldIfMissing $db "Tâches" "Coût prévu" $dbCurrency 0 "0"
    Add-FieldIfMissing $db "Tâches" "Temps passé effectif" $dbDouble 0 "0"
    Add-FieldIfMissing $db "Tâches" "Date de fin effective" $dbDate
    Add-FieldIfMissing $db "Tâches" "Ressources affectées" $dbMemo
    Add-FieldIfMissing $db "Tâches" "Prédécesseurs" $dbMemo

    if (!(Test-TableExists $db "Suivi des temps")) {
        Invoke-DaoSql $db "CREATE TABLE [Suivi des temps] ([ID] COUNTER CONSTRAINT [pk_SuiviTemps] PRIMARY KEY, [Date saisie] DATETIME, [Projet] LONG, [Tâche] LONG, [Employé] LONG, [Heures] DOUBLE, [Commentaire] MEMO)"
    }

    if (!(Test-TableExists $db "Ressources des tâches")) {
        Invoke-DaoSql $db "CREATE TABLE [Ressources des tâches] ([ID] COUNTER CONSTRAINT [pk_RessourcesTaches] PRIMARY KEY, [Tâche] LONG, [Employé] LONG, [Rôle] TEXT(100), [Charge prévue heures] DOUBLE)"
    }

    if (!(Test-TableExists $db "Dépendances des tâches")) {
        Invoke-DaoSql $db "CREATE TABLE [Dépendances des tâches] ([ID] COUNTER CONSTRAINT [pk_DependancesTaches] PRIMARY KEY, [Prédécesseur] LONG, [Successeur] LONG, [Type de lien] TEXT(20), [Décalage jours] INTEGER, [Commentaire] MEMO)"
    }
    $db.TableDefs.Refresh()

    Invoke-DaoSql $db "UPDATE [Tâches] SET [Référence] = 'P' & [Projet] & '-T' & Format([ID],'0000') WHERE [Référence] Is Null OR [Référence]=''"
    Invoke-DaoSql $db "UPDATE [Tâches] SET [Coût prévu] = IIf([Coût] Is Null,0,[Coût]) WHERE [Coût prévu] Is Null OR [Coût prévu]=0"
    Invoke-DaoSql $db "UPDATE [Tâches] SET [Temps prévu] = IIf([Coût en jours] Is Null,0,[Coût en jours]) * 8 WHERE [Temps prévu] Is Null OR [Temps prévu]=0"

    Add-IndexIfMissing $db "Tâches" "ux_Taches_Reference" @("Référence") $true
    Add-IndexIfMissing $db "Tâches" "ix_Taches_Projet_Ordre" @("Projet", "Ordre", "ID") $false
    Add-IndexIfMissing $db "Suivi des temps" "ix_SuiviTemps_Tache" @("Tâche") $false
    Add-IndexIfMissing $db "Ressources des tâches" "ux_RessourcesTaches_TacheEmploye" @("Tâche", "Employé") $true
    Add-IndexIfMissing $db "Dépendances des tâches" "ux_DependancesTaches_Lien" @("Prédécesseur", "Successeur") $true

    Add-RelationIfMissing $db "rel_Taches_Parent" "Tâches" "Tâches" "ID" "Tâche parente"
    Add-RelationIfMissing $db "rel_SuiviTemps_Projets" "Projets" "Suivi des temps" "ID" "Projet"
    Add-RelationIfMissing $db "rel_SuiviTemps_Taches" "Tâches" "Suivi des temps" "ID" "Tâche"
    Add-RelationIfMissing $db "rel_SuiviTemps_Employes" "Employés" "Suivi des temps" "ID" "Employé"
    Add-RelationIfMissing $db "rel_RessourcesTaches_Taches" "Tâches" "Ressources des tâches" "ID" "Tâche"
    Add-RelationIfMissing $db "rel_RessourcesTaches_Employes" "Employés" "Ressources des tâches" "ID" "Employé"
    Add-RelationIfMissing $db "rel_Dependances_Predecesseur" "Tâches" "Dépendances des tâches" "ID" "Prédécesseur"
    Add-RelationIfMissing $db "rel_Dependances_Successeur" "Tâches" "Dépendances des tâches" "ID" "Successeur"

    $queryDefs = @{
        "Temps passés par tâche" = "SELECT [Tâche], Sum([Heures]) AS [Heures effectives] FROM [Suivi des temps] GROUP BY [Tâche];"
        "Liste tâches pour saisie temps" = "SELECT T.[ID], T.[Projet], Nz(T.[Référence],'T-' & T.[ID]) & ' - ' & T.[Titre] & ' (' & P.[Nom du projet] & ')' AS [Libellé tâche] FROM [Tâches] AS T INNER JOIN [Projets] AS P ON T.[Projet]=P.[ID] ORDER BY P.[Nom du projet], T.[Ordre], T.[ID];"
        "Aperçu Gantt tâches" = "SELECT T.[ID], T.[Projet], T.[Référence], T.[Niveau], T.[Titre], T.[Début], T.[Échéance], T.[Date de fin effective], T.[% achevé], T.[Statut], T.[Temps prévu], T.[Temps passé effectif], T.[Coût prévu], GanttLibelle([T].[ID]) AS [Libellé Gantt], GanttBar([T].[ID]) AS [Barre Gantt], RessourcesTache([T].[ID]) AS [Ressources], PredesseursTache([T].[ID]) AS [Prédécesseurs lisibles] FROM [Tâches] AS T ORDER BY T.[Projet], T.[Ordre], T.[ID];"
        "Générer références tâches manquantes" = "UPDATE [Tâches] SET [Référence] = 'P' & [Projet] & '-T' & Format([ID],'0000') WHERE Nz([Référence],'')='' OR [Référence] Like 'TMP-*';"
        "Actualiser temps passé tâches" = "UPDATE [Tâches] SET [Temps passé effectif] = Nz(DSum('[Heures]','[Suivi des temps]','[Tâche]=' & [ID]),0);"
    }

    foreach ($name in $queryDefs.Keys) {
        if (Test-QueryExists $db $name) {
            $db.QueryDefs.Delete($name)
        }
        $null = $db.CreateQueryDef($name, $queryDefs[$name])
    }

    $ownerId = [int](Get-Scalar $db "SELECT Min([ID]) FROM [Employés]")
    if ($ownerId -le 0) { $ownerId = 1 }
    $secondEmployee = Get-Scalar $db "SELECT Max([ID]) FROM [Employés]"
    if ($null -eq $secondEmployee) { $secondEmployee = $ownerId }
    $secondEmployee = [int]$secondEmployee

    $projectId = [int](Get-Scalar $db "SELECT TOP 1 [ID] FROM [Projets] ORDER BY [ID]")
    if ($projectId -le 0) {
        $projectId = Add-ProjectIfMissing $db "Projet exemple Access" ([datetime]"2026-07-01") ([datetime]"2026-08-31") $ownerId
    }
    $null = Add-ProjectIfMissing $db "Projet portefeuille démonstration" ([datetime]"2026-09-01") ([datetime]"2026-12-15") $ownerId

    $taskCount = [int](Get-Scalar $db "SELECT Count(*) FROM [Tâches] WHERE [Projet]=$projectId")
    if ($taskCount -eq 0) {
        $cadrage = Add-Task $db $projectId "Cadrage" 1 $null ([datetime]"2026-07-01") ([datetime]"2026-07-10") 40 4500 10 $ownerId
        $ateliers = Add-Task $db $projectId "Ateliers besoins" 2 $cadrage ([datetime]"2026-07-01") ([datetime]"2026-07-04") 18 1800 20 $ownerId
        $cartographie = Add-Task $db $projectId "Cartographie processus" 3 $ateliers ([datetime]"2026-07-02") ([datetime]"2026-07-05") 14 1400 30 $secondEmployee
        $compteRendu = Add-Task $db $projectId "Consolidation comptes rendus" 4 $cartographie ([datetime]"2026-07-05") ([datetime]"2026-07-07") 8 800 40 $ownerId
        $conception = Add-Task $db $projectId "Conception" 1 $null ([datetime]"2026-07-11") ([datetime]"2026-07-25") 56 7200 50 $secondEmployee
        $architecture = Add-Task $db $projectId "Architecture cible" 2 $conception ([datetime]"2026-07-11") ([datetime]"2026-07-17") 28 3600 60 $secondEmployee
        $modele = Add-Task $db $projectId "Modèle de données" 3 $architecture ([datetime]"2026-07-15") ([datetime]"2026-07-20") 24 3000 70 $secondEmployee
        $realisation = Add-Task $db $projectId "Réalisation" 1 $null ([datetime]"2026-07-26") ([datetime]"2026-08-20") 96 13500 80 $ownerId
        $recette = Add-Task $db $projectId "Recette et déploiement" 1 $null ([datetime]"2026-08-21") ([datetime]"2026-08-31") 48 6500 90 $ownerId

        Add-ResourceAssignment $db $cadrage $ownerId "Pilotage" 24
        Add-ResourceAssignment $db $ateliers $ownerId "Animation ateliers" 18
        Add-ResourceAssignment $db $cartographie $secondEmployee "Analyse processus" 14
        Add-ResourceAssignment $db $compteRendu $ownerId "Synthèse" 8
        Add-ResourceAssignment $db $architecture $secondEmployee "Architecture" 28
        Add-ResourceAssignment $db $modele $secondEmployee "Modélisation" 24
        Add-ResourceAssignment $db $realisation $ownerId "Coordination réalisation" 42
        Add-ResourceAssignment $db $realisation $secondEmployee "Développement" 54

        Add-TimeEntry $db $projectId $ateliers $ownerId ([datetime]"2026-07-02") 4 "Préparation atelier"
        Add-TimeEntry $db $projectId $ateliers $ownerId ([datetime]"2026-07-03") 6 "Atelier besoins"
        Add-TimeEntry $db $projectId $cartographie $secondEmployee ([datetime]"2026-07-04") 5 "Cartographie initiale"

        Add-Dependency $db $cadrage $conception "Fin-Début" 0
        Add-Dependency $db $conception $realisation "Fin-Début" 0
        Add-Dependency $db $realisation $recette "Fin-Début" 0
        Add-Dependency $db $cartographie $compteRendu "Fin-Début" 0

        Invoke-DaoSql $db "UPDATE [Tâches] SET [Référence] = 'P' & [Projet] & '-T' & Format([ID],'0000') WHERE [Référence] Like 'TMP-*' OR [Référence] Is Null OR [Référence]=''"
        Invoke-DaoSql $db "UPDATE [Tâches] SET [% achevé]=0.6 WHERE [ID] In ($ateliers,$cartographie)"
        Invoke-DaoSql $db "UPDATE [Tâches] SET [% achevé]=0.3 WHERE [ID]=$cadrage"
    }

    Invoke-DaoSql $db "UPDATE [Tâches] SET [Temps passé effectif] = 0 WHERE [Temps passé effectif] Is Null"
} finally {
    $db.Close()
}

$access = New-Object -ComObject Access.Application
$access.OpenCurrentDatabase($OutputPath)

try {
    $moduleCode = @'
Option Explicit

Public Function ReferenceTemporaire() As String
    Randomize
    ReferenceTemporaire = "TMP-" & Format(Now(), "yymmddhhnnss") & "-" & Format(Int(Rnd() * 1000), "000")
End Function

Public Sub GenererReferencesTaches()
    CurrentDb.Execute "UPDATE [Tâches] SET [Référence] = 'P' & [Projet] & '-T' & Format([ID],'0000') WHERE Nz([Référence],'')='' OR [Référence] Like 'TMP-*'", 128
End Sub

Public Sub RecalculerTempsPasses()
    GenererReferencesTaches
    CurrentDb.Execute "UPDATE [Tâches] SET [Temps passé effectif] = Nz(DSum('[Heures]','[Suivi des temps]','[Tâche]=' & [ID]),0)", 128
End Sub

Public Function ActualiserProjet() As Boolean
    On Error GoTo ErrHandler
    RecalculerTempsPasses
    If CurrentProject.AllForms("Détails du projet").IsLoaded Then
        Forms![Détails du projet].Requery
        On Error Resume Next
        Forms![Détails du projet]![Tasks subform].Form.Requery
        Forms![Détails du projet]![Gantt subform].Form.Requery
        Forms![Détails du projet]![Suivi temps subform].Form.Requery
        On Error GoTo ErrHandler
    End If
    ActualiserProjet = True
    Exit Function
ErrHandler:
    MsgBox "Actualisation impossible : " & Err.Description, vbExclamation
    ActualiserProjet = False
End Function

Public Function GanttLibelle(ByVal TaskID As Long) As String
    On Error GoTo CleanFail
    Dim rs As Object
    Set rs = CurrentDb.OpenRecordset("SELECT [Référence], [Niveau], [Titre] FROM [Tâches] WHERE [ID]=" & CLng(TaskID), 4)
    If rs.EOF Then
        GanttLibelle = ""
    Else
        GanttLibelle = String((Nz(rs.Fields("Niveau").Value, 1) - 1) * 3, " ") & Nz(rs.Fields("Référence").Value, "T-" & TaskID) & "  " & Nz(rs.Fields("Titre").Value, "")
    End If
    rs.Close
    Exit Function
CleanFail:
    GanttLibelle = ""
End Function

Public Function GanttBar(ByVal TaskID As Long) As String
    On Error GoTo CleanFail
    Dim rs As Object
    Dim projectStart As Variant
    Dim taskStart As Date
    Dim taskEnd As Date
    Dim offsetChars As Long
    Dim durationChars As Long
    Dim completeChars As Long
    Dim pct As Double

    Set rs = CurrentDb.OpenRecordset("SELECT [Projet], [Début], [Échéance], [% achevé] FROM [Tâches] WHERE [ID]=" & CLng(TaskID), 4)
    If rs.EOF Or IsNull(rs.Fields("Début").Value) Then
        GanttBar = ""
        GoTo CleanExit
    End If

    projectStart = DMin("[Début]", "[Tâches]", "[Projet]=" & CLng(rs.Fields("Projet").Value))
    If IsNull(projectStart) Then projectStart = rs.Fields("Début").Value
    taskStart = rs.Fields("Début").Value
    taskEnd = Nz(rs.Fields("Échéance").Value, taskStart)
    If taskEnd < taskStart Then taskEnd = taskStart

    offsetChars = DateDiff("ww", CDate(projectStart), taskStart) * 3
    If offsetChars < 0 Then offsetChars = 0
    durationChars = DateDiff("ww", taskStart, taskEnd) * 3 + 3
    If durationChars < 3 Then durationChars = 3

    pct = Nz(rs.Fields("% achevé").Value, 0)
    If pct > 1 Then pct = pct / 100
    If pct < 0 Then pct = 0
    If pct > 1 Then pct = 1
    completeChars = Int(durationChars * pct)

    GanttBar = Space(offsetChars) & String(completeChars, "=") & String(durationChars - completeChars, "-")

CleanExit:
    On Error Resume Next
    rs.Close
    Exit Function
CleanFail:
    GanttBar = ""
End Function

Public Function RessourcesTache(ByVal TaskID As Long) As String
    On Error GoTo CleanFail
    Dim rs As Object
    Dim value As String
    Set rs = CurrentDb.OpenRecordset("SELECT E.[Prénom], E.[Nom] FROM [Ressources des tâches] AS R INNER JOIN [Employés] AS E ON R.[Employé]=E.[ID] WHERE R.[Tâche]=" & CLng(TaskID) & " ORDER BY E.[Nom], E.[Prénom]", 4)
    Do While Not rs.EOF
        If Len(value) > 0 Then value = value & ", "
        value = value & Trim(Nz(rs.Fields("Prénom").Value, "") & " " & Nz(rs.Fields("Nom").Value, ""))
        rs.MoveNext
    Loop
    rs.Close
    RessourcesTache = value
    Exit Function
CleanFail:
    RessourcesTache = ""
End Function

Public Function PredesseursTache(ByVal TaskID As Long) As String
    On Error GoTo CleanFail
    Dim rs As Object
    Dim value As String
    Set rs = CurrentDb.OpenRecordset("SELECT T.[Référence] FROM [Dépendances des tâches] AS D INNER JOIN [Tâches] AS T ON D.[Prédécesseur]=T.[ID] WHERE D.[Successeur]=" & CLng(TaskID) & " ORDER BY T.[Ordre], T.[ID]", 4)
    Do While Not rs.EOF
        If Len(value) > 0 Then value = value & ", "
        value = value & Nz(rs.Fields("Référence").Value, "")
        rs.MoveNext
    Loop
    rs.Close
    PredesseursTache = value
    Exit Function
CleanFail:
    PredesseursTache = ""
End Function

Public Function DateAxeGantt(ByVal ProjectID As Long) As String
    On Error GoTo CleanFail
    Dim projectStart As Variant
    Dim i As Integer
    Dim value As String
    projectStart = DMin("[Début]", "[Tâches]", "[Projet]=" & CLng(ProjectID))
    If IsNull(projectStart) Then
        DateAxeGantt = ""
        Exit Function
    End If
    For i = 0 To 11
        value = value & Format(DateAdd("ww", i, CDate(projectStart)), "dd/mm") & Space(4)
    Next i
    DateAxeGantt = value
    Exit Function
CleanFail:
    DateAxeGantt = ""
End Function
'@

    try {
        $vbProject = $access.VBE.ActiveVBProject
        foreach ($component in @($vbProject.VBComponents)) {
            if ($component.Name -eq "modGestionProjets") {
                $vbProject.VBComponents.Remove($component)
            }
        }
        $module = $vbProject.VBComponents.Add(1)
        $module.Name = "modGestionProjets"
        $module.CodeModule.AddFromString($moduleCode)
        $access.DoCmd.Save($acModule, "modGestionProjets")
    } catch {
        throw "Impossible d'ajouter le module VBA modGestionProjets : $($_.Exception.Message)"
    }

    $employeeRowSource = "SELECT [Employés].ID, Trim(Nz([Prénom],'') & ' ' & Nz([Nom],'')) AS [Nom complet] FROM [Employés] ORDER BY [Nom], [Prénom];"
    $taskRowSource = "SELECT [ID], Nz([Référence],'T-' & [ID]) & ' - ' & [Titre] AS [Libellé] FROM [Tâches] ORDER BY [Projet], [Ordre], [ID];"
    $projectRowSource = "SELECT [ID], [Nom du projet] FROM [Projets] ORDER BY [Nom du projet];"

    New-DatasheetForm $access "Sous-formulaire Tâches projet avancé" "Tâches" "Tâches projet avancées" @(
        @{ Kind="text"; Name="colReference"; Source="Référence"; Caption="Référence"; Width=1500; DefaultValue="=ReferenceTemporaire()" },
        @{ Kind="combo"; Name="colNiveau"; Source="Niveau"; Caption="Niveau"; Width=850; RowSource="SELECT 1 AS ID, '1 - Phase' AS Libellé UNION SELECT 2, '2 - Étape' UNION SELECT 3, '3 - Sous-tâche' UNION SELECT 4, '4 - Opérationnel';"; ColumnWidths="0;1600" },
        @{ Kind="text"; Name="colTitre"; Source="Titre"; Caption="Titre"; Width=3000 },
        @{ Kind="text"; Name="colDebut"; Source="Début"; Caption="Date démarrage"; Width=1400; Format="Short Date" },
        @{ Kind="text"; Name="colFinEstimee"; Source="Échéance"; Caption="Fin estimée"; Width=1400; Format="Short Date" },
        @{ Kind="text"; Name="colTempsPrevu"; Source="Temps prévu"; Caption="Temps prévu"; Width=1200; Format="0.00" },
        @{ Kind="text"; Name="colCoutPrevu"; Source="Coût prévu"; Caption="Coût prévu"; Width=1300; Format="Currency" },
        @{ Kind="text"; Name="colTempsPasse"; Source="Temps passé effectif"; Caption="Temps passé"; Width=1300; Format="0.00"; Locked=$true },
        @{ Kind="text"; Name="colFinEffective"; Source="Date de fin effective"; Caption="Fin effective"; Width=1400; Format="Short Date" },
        @{ Kind="combo"; Name="colParent"; Source="Tâche parente"; Caption="Parent"; Width=2800; RowSource=$taskRowSource; ColumnWidths="0;3600" },
        @{ Kind="text"; Name="colRessources"; Source="Ressources affectées"; Caption="Ressources"; Width=2600 },
        @{ Kind="text"; Name="colPredesseurs"; Source="Prédécesseurs"; Caption="Prédécesseurs"; Width=2200 },
        @{ Kind="text"; Name="colAvancement"; Source="% achevé"; Caption="% achevé"; Width=1000; Format="Percent" },
        @{ Kind="text"; Name="colStatut"; Source="Statut"; Caption="Statut"; Width=1600 }
    ) $null "=ActualiserProjet()"

    New-DatasheetForm $access "Sous-formulaire Gantt projet" "Aperçu Gantt tâches" "Aperçu Gantt projet" @(
        @{ Kind="text"; Name="colGanttLabel"; Source="Libellé Gantt"; Caption="Tâche"; Width=4700; Locked=$true },
        @{ Kind="text"; Name="colGanttStart"; Source="Début"; Caption="Début"; Width=1200; Format="Short Date"; Locked=$true },
        @{ Kind="text"; Name="colGanttEnd"; Source="Échéance"; Caption="Fin estimée"; Width=1200; Format="Short Date"; Locked=$true },
        @{ Kind="text"; Name="colGanttProgress"; Source="% achevé"; Caption="%"; Width=800; Format="Percent"; Locked=$true },
        @{ Kind="text"; Name="colGanttResources"; Source="Ressources"; Caption="Ressources"; Width=2600; Locked=$true },
        @{ Kind="text"; Name="colGanttBar"; Source="Barre Gantt"; Caption="Gantt"; Width=6500; FontName="Consolas"; Locked=$true },
        @{ Kind="text"; Name="colGanttPred"; Source="Prédécesseurs lisibles"; Caption="Liens"; Width=2200; Locked=$true }
    )

    New-DatasheetForm $access "Sous-formulaire Suivi temps projet" "Suivi des temps" "Suivi temps projet" @(
        @{ Kind="text"; Name="colDateSaisie"; Source="Date saisie"; Caption="Date"; Width=1300; Format="Short Date" },
        @{ Kind="combo"; Name="colTempsProjet"; Source="Projet"; Caption="Projet"; Width=2400; RowSource=$projectRowSource; ColumnWidths="0;3000" },
        @{ Kind="combo"; Name="colTempsTache"; Source="Tâche"; Caption="Tâche"; Width=3900; RowSource=$taskRowSource; ColumnWidths="0;5000" },
        @{ Kind="combo"; Name="colTempsEmploye"; Source="Employé"; Caption="Utilisateur"; Width=2600; RowSource=$employeeRowSource; ColumnWidths="0;3200" },
        @{ Kind="text"; Name="colHeures"; Source="Heures"; Caption="Heures"; Width=1000; Format="0.00" },
        @{ Kind="text"; Name="colCommentaire"; Source="Commentaire"; Caption="Commentaire"; Width=4200 }
    ) "=ActualiserProjet()" "=ActualiserProjet()"

    New-DatasheetForm $access "Suivi des temps" "Suivi des temps" "Suivi des temps" @(
        @{ Kind="text"; Name="colDateSaisie"; Source="Date saisie"; Caption="Date"; Width=1300; Format="Short Date" },
        @{ Kind="combo"; Name="colProjet"; Source="Projet"; Caption="Projet"; Width=2500; RowSource=$projectRowSource; ColumnWidths="0;3200" },
        @{ Kind="combo"; Name="colTache"; Source="Tâche"; Caption="Tâche"; Width=4300; RowSource=$taskRowSource; ColumnWidths="0;5400" },
        @{ Kind="combo"; Name="colEmploye"; Source="Employé"; Caption="Utilisateur"; Width=2600; RowSource=$employeeRowSource; ColumnWidths="0;3200" },
        @{ Kind="text"; Name="colHeures"; Source="Heures"; Caption="Heures"; Width=1000; Format="0.00" },
        @{ Kind="text"; Name="colCommentaire"; Source="Commentaire"; Caption="Commentaire"; Width=4500 }
    ) "=ActualiserProjet()" "=ActualiserProjet()"

    New-DatasheetForm $access "Affectations ressources" "Ressources des tâches" "Affectations ressources" @(
        @{ Kind="combo"; Name="colRessTache"; Source="Tâche"; Caption="Tâche"; Width=4300; RowSource=$taskRowSource; ColumnWidths="0;5400" },
        @{ Kind="combo"; Name="colRessEmploye"; Source="Employé"; Caption="Utilisateur"; Width=2600; RowSource=$employeeRowSource; ColumnWidths="0;3200" },
        @{ Kind="text"; Name="colRole"; Source="Rôle"; Caption="Rôle"; Width=2500 },
        @{ Kind="text"; Name="colCharge"; Source="Charge prévue heures"; Caption="Charge prévue"; Width=1500; Format="0.00" }
    )

    $access.CloseCurrentDatabase()
    $access.Quit()
    $access = New-Object -ComObject Access.Application
    $access.OpenCurrentDatabase($OutputPath)

    New-DatasheetForm $access "Dépendances tâches" "Dépendances des tâches" "Dépendances tâches" @(
        @{ Kind="combo"; Name="colPred"; Source="Prédécesseur"; Caption="Prédécesseur"; Width=4300; RowSource=$taskRowSource; ColumnWidths="0;5400" },
        @{ Kind="combo"; Name="colSucc"; Source="Successeur"; Caption="Successeur"; Width=4300; RowSource=$taskRowSource; ColumnWidths="0;5400" },
        @{ Kind="text"; Name="colTypeLien"; Source="Type de lien"; Caption="Type"; Width=1600 },
        @{ Kind="text"; Name="colLag"; Source="Décalage jours"; Caption="Décalage"; Width=1100 },
        @{ Kind="text"; Name="colCommentaire"; Source="Commentaire"; Caption="Commentaire"; Width=4200 }
    )

    $access.DoCmd.OpenForm("Détails du projet", $acDesign)
    $projectForm = $access.Forms.Item("Détails du projet")
    $tasksSubform = $projectForm.Controls.Item("Tasks subform")
    $tasksSubform.SourceObject = "Form.Sous-formulaire Tâches projet avancé"
    $tasksSubform.LinkChildFields = "Projet"
    $tasksSubform.LinkMasterFields = "ID"
    $tasksSubform.Height = 2100

    try {
        $projectForm.Controls.Item("Tasks subform_Label").Caption = "Saisissez les tâches du projet ci-dessous : 4 niveaux hiérarchiques, dates, temps/coûts prévus, parents et liens de dépendance."
    } catch {}

    $ganttPage = $access.CreateControl("Détails du projet", $acPage, $acDetail, "Tasks Tab Control", $null, 0, 0, 0, 0)
    $ganttPage.Name = "Project Gantt_Page"
    $ganttPage.Caption = "Aperçu Gantt"

    $ganttTitle = $access.CreateControl("Détails du projet", $acLabel, $acDetail, $ganttPage.Name, $null, 600, 1200, 2800, 315)
    $ganttTitle.Name = "lblGanttAxis"
    $ganttTitle.Caption = "Axe temporel"

    $ganttAxis = $access.CreateControl("Détails du projet", $acTextBox, $acDetail, $ganttPage.Name, $null, 3400, 1200, 6250, 315)
    $ganttAxis.Name = "txtGanttAxis"
    $ganttAxis.ControlSource = "=DateAxeGantt([ID])"
    $ganttAxis.FontName = "Consolas"
    $ganttAxis.Locked = $true

    $refreshButton = $access.CreateControl("Détails du projet", $acCommandButton, $acDetail, $ganttPage.Name, $null, 9650, 1200, 700, 315)
    $refreshButton.Name = "cmdActualiserProjet"
    $refreshButton.Caption = "Actualiser"
    $refreshButton.OnClick = "=ActualiserProjet()"

    $ganttSubform = $access.CreateControl("Détails du projet", $acSubform, $acDetail, $ganttPage.Name, $null, 600, 1620, 9750, 2920)
    $ganttSubform.Name = "Gantt subform"
    $ganttSubform.SourceObject = "Form.Sous-formulaire Gantt projet"
    $ganttSubform.LinkChildFields = "Projet"
    $ganttSubform.LinkMasterFields = "ID"
    $ganttSubform.BorderColor = 0

    $timePage = $access.CreateControl("Détails du projet", $acPage, $acDetail, "Tasks Tab Control", $null, 0, 0, 0, 0)
    $timePage.Name = "Project Time_Page"
    $timePage.Caption = "Suivi temps"

    $timeLabel = $access.CreateControl("Détails du projet", $acLabel, $acDetail, $timePage.Name, $null, 600, 1200, 9600, 360)
    $timeLabel.Name = "lblTimeTracking"
    $timeLabel.Caption = "Saisissez ici les heures effectives par tâche et utilisateur. Le temps passé des tâches est recalculé automatiquement."

    $timeSubform = $access.CreateControl("Détails du projet", $acSubform, $acDetail, $timePage.Name, $null, 600, 1620, 9750, 2920)
    $timeSubform.Name = "Suivi temps subform"
    $timeSubform.SourceObject = "Form.Sous-formulaire Suivi temps projet"
    $timeSubform.LinkChildFields = "Projet"
    $timeSubform.LinkMasterFields = "ID"
    $timeSubform.BorderColor = 0

    $access.DoCmd.Close($acForm, "Détails du projet", $acSaveYes)

    try {
        $access.Run("GenererReferencesTaches")
        $access.Run("RecalculerTempsPasses")
    } catch {
        throw "Le module VBA a été ajouté, mais une procédure de vérification a échoué : $($_.Exception.Message)"
    }
} finally {
    try { $access.CloseCurrentDatabase() } catch {}
    try { $access.Quit() } catch {}
}

Write-Host "Base Access générée : $OutputPath"
