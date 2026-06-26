# PerspectiV

Excel Project manager.

## Livrables

- `Gestion_Projets.xlsm` : modèle Excel de gestion multi-projets avec onglets de synthèse, utilisateurs, suivi des temps et projets.
- `tools/create_project_management_xlsm.py` : générateur reproductible du classeur à partir de la bibliothèque standard Python.
- `ProjectManagementMacros.bas` : module VBA prêt à importer/adapter pour les automatisations Excel.

## Fonctionnalités du modèle

- Onglet **Récap Projets** avec liens vers les onglets projet dédiés.
- Onglet **Utilisateurs** servant de référentiel de ressources.
- Un onglet par projet avec KPI, tâches hiérarchisées sur 4 niveaux, références uniques, dates, budgets, ressources, avancement et Gantt.
- Colonnes **Parent** et **Prédécesseurs** pour modéliser les liens parent/enfant et les dépendances Gantt.
- Onglet **Suivi Temps** pour saisir les heures effectives par tâche et utilisateur.
- Injection automatique du temps passé par tâche dans les onglets projet via formules `SUMIFS`.

## Régénération

```bash
python3 tools/create_project_management_xlsm.py
```
