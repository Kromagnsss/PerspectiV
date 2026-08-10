# PerspectiV

Application de gestion de projets.

## Livrables

- `streamlit_app.py` : nouvelle application Python locale multi-utilisateurs.
- `perspectiv/` : backend SQL, services métier, visualisations et exports PDF.
- `requirements.txt` : dépendances Python du frontend et du backend local.
- `docs/library_research.md` : comparaison des bibliothèques candidates par fonction.
- `Gestion_Projets_Access.accdb` : application Access generee depuis le template `MSDBP.accdb`.
- `tools/create_project_management_access.ps1` : generateur reproductible de la base Access.
- `Gestion_Projets.xlsm` : ancien livrable Excel conserve dans le depot.
- `tools/create_project_management_xlsm.py` et `ProjectManagementMacros.bas` : generateur et macros du livrable Excel precedent.

## Application Python

La nouvelle version remplace l'interface Access par une application Streamlit locale :

- frontend Python accessible dans le navigateur ;
- backend SQL via SQLAlchemy ;
- base SQLite locale par defaut dans `data/perspectiv.db` ;
- modele multi-utilisateurs avec authentification locale ;
- projets, taches hierarchiques, dependances, Gantt, timesheet, budget, KPI et export PDF.
- budgets multiples par projet, rattachement des taches a un budget, recalcul du reel budgetaire depuis les temps pointes et les depenses directes de taches.
- edition directe des tables projets, taches, timesheet, budget et utilisateurs via des grilles sauvegardees en base.
- table projets liee a un Gantt interactif, avec mise a jour automatique depuis les dates modifiees, boutons de plage et coloration par champ numerique.
- onglet taches avec Gantt interactif pleine largeur, coloration par champ numerique et table editable dessous.
- vue groupee des taches avec couleurs pastel par niveau, regroupement parent/enfants et lignes parentes calculees depuis leurs sous-taches.

### Installation

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

### Lancement

```powershell
.\.venv\Scripts\python -m streamlit run streamlit_app.py
```

Compte de demonstration :

- utilisateur : `admin`
- mot de passe : `admin`

Pour une base PostgreSQL au lieu de SQLite, definir `PERSPECTIV_DATABASE_URL` avant le lancement.

## Fonctionnalites Access

- Gestion de plusieurs projets via les tables et formulaires existants du template.
- Liste des utilisateurs basee sur la table et les formulaires `Employes`.
- Detail projet enrichi avec le sous-formulaire de taches avancees.
- Taches avec reference unique, niveau 1 a 4, parent, dates, temps/couts prevus, temps passe, fin effective, avancement et statut.
- Affectations multi-ressources via la table et le formulaire `Affectations ressources`.
- Dependances entre taches via la table et le formulaire `Dependances taches`.
- Suivi des temps par projet, tache, utilisateur et nombre d'heures.
- Recalcul du temps passe effectif dans les taches depuis les saisies de temps.
- Nouvel onglet `Apercu Gantt` dans `Details du projet`, avec axe temporel et barre Gantt texte.
- Onglet `Suivi temps` ajoute dans `Details du projet`.

## Regeneration Access

Depuis Windows PowerShell :

```powershell
$script = Get-Content -LiteralPath '.\tools\create_project_management_access.ps1' -Raw -Encoding UTF8
Invoke-Expression $script
```

Le script repart du template `C:\Users\111624\Downloads\MSDBP.accdb` et regenere `Gestion_Projets_Access.accdb`.
