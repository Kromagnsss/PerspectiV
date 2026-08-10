# Recherche bibliothèques pour PerspectiV Python

Objectif : remplacer le prototype Access par une application locale inspirée d'OpenProject et ClickUp, avec frontend Python, backend SQL, visualisations avancées et usage multi-utilisateurs.

## Choix retenu pour le MVP

- Frontend : Streamlit.
- Backend applicatif : Python + SQLAlchemy.
- Base de données : SQLite en local par défaut, PostgreSQL possible via `PERSPECTIV_DATABASE_URL`.
- Visualisations : Plotly.
- Synthèses tabulaires : pandas.
- Dépendances et chemin critique : NetworkX.
- Export PDF : ReportLab.

Ce choix donne une application très rapide à livrer et à maintenir localement. Pour une version plus proche d'un vrai SaaS multi-postes, l'évolution naturelle serait FastAPI + PostgreSQL + frontend web plus riche, ou Django si l'administration et l'authentification avancées deviennent centrales.

## Bibliothèques candidates par typologie

| Fonction | 3 bibliothèques candidates | Lecture |
| --- | --- | --- |
| Frontend Python local | Streamlit, Dash, NiceGUI | Streamlit est le plus rapide pour un outil interne data/app ; Dash est très solide pour app Plotly plus structurée ; NiceGUI est intéressant pour une UI Python plus applicative. |
| Backend/API | FastAPI, Django, Flask | FastAPI si API séparée ; Django si besoin d'admin/auth/permissions très cadrées ; Flask pour minimalisme. |
| ORM/base SQL | SQLAlchemy, SQLModel, Django ORM | SQLAlchemy est le socle le plus flexible ; SQLModel simplifie les modèles FastAPI ; Django ORM est excellent dans une stack Django complète. |
| Timesheet | Streamlit `st.data_editor`, streamlit-aggrid, django-timepiece | Pour le MVP, formulaire + table suffisent ; AgGrid apporte une grille plus riche ; django-timepiece est une base existante si on bascule Django. |
| Gantt | Plotly timeline, Frappe Gantt, DHTMLX Gantt | Plotly est natif Python et simple ; Frappe Gantt est open source et plus interactif ; DHTMLX est plus complet mais JavaScript/licence à vérifier. |
| Planification/dépendances | NetworkX, OR-Tools, workalendar | NetworkX pour graphe et chemin critique ; OR-Tools pour optimisation sous contraintes ; workalendar pour jours ouvrés et calendriers pays. |
| Budget | pandas, py-moneyed, Babel | pandas pour agrégations ; py-moneyed pour types monétaires stricts ; Babel pour formatage localisé devise. |
| Synthèses/KPI | Plotly, Altair, streamlit-echarts | Plotly est polyvalent ; Altair est élégant pour statistiques ; ECharts donne beaucoup de types de graphiques via composant Streamlit. |
| Export PDF | ReportLab, WeasyPrint, fpdf2 | ReportLab contrôle fin et pure Python ; WeasyPrint est idéal HTML/CSS vers PDF ; fpdf2 est plus simple pour rapports légers. |
| Auth locale | PBKDF2 standard library, Streamlit OIDC, Streamlit-Authenticator | Le MVP utilise PBKDF2 sans dépendance ; Streamlit OIDC est meilleur avec un fournisseur d'identité ; Streamlit-Authenticator est pratique pour login local. |

## Architecture cible

```text
streamlit_app.py        # frontend Python
perspectiv/
  database.py           # moteur SQL et seed
  models.py             # modèle relationnel
  services.py           # opérations métier
  charts.py             # visualisations Plotly/NetworkX
  reports.py            # exports PDF
data/perspectiv.db      # backend SQLite local par défaut
reports/                # PDFs générés
```

## Passage à plusieurs utilisateurs

SQLite convient pour un usage local léger ou un petit partage réseau avec prudence. Pour plusieurs utilisateurs actifs en même temps, utiliser PostgreSQL :

```powershell
$env:PERSPECTIV_DATABASE_URL = "postgresql+psycopg://user:password@serveur:5432/perspectiv"
streamlit run streamlit_app.py
```

Il faudra alors ajouter le driver PostgreSQL choisi dans `requirements.txt`.
