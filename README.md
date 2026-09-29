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

## API, MCP et deploiement Proxmox

L'API FastAPI et le serveur MCP sont servis par le meme processus :

```powershell
$env:PERSPECTIV_AUTH_DISABLED="true" # developpement local uniquement
.\.venv\Scripts\python -m uvicorn perspectiv.api:app --host 127.0.0.1 --port 8000
```

- API OpenAPI : `http://127.0.0.1:8000/docs`
- Sante : `http://127.0.0.1:8000/health`
- MCP Streamable HTTP : `http://127.0.0.1:8000/mcp`

En production, PostgreSQL, Keycloak et OAuth sont obligatoires. SQLite et `PERSPECTIV_AUTH_DISABLED` restent reserves au developpement.

### Installation Proxmox VE

1. Installer Keycloak dans un LXC separe avec le script officiel Community Scripts :

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/keycloak.sh)"
```

2. Configurer le realm, les clients Web/API/MCP et recuperer le secret du client Web :

```bash
python tools/configure_keycloak.py \
  --keycloak-url https://auth.example.com \
  --public-url https://perspectiv.example.com \
  --admin-user tmpadm \
  --admin-password 'mot-de-passe-keycloak'
```

3. Installer PerspectiV depuis le depot sur le shell Proxmox, avec les valeurs obtenues a l'etape precedente :

```bash
export var_public_url="https://perspectiv.example.com"
export var_oidc_issuer="https://auth.example.com/realms/perspectiv"
export var_oidc_client_secret="SECRET_RETOURNE_PAR_CONFIGURE_KEYCLOAK"
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Kromagnsss/PerspectiV/main/proxmox/ct/perspectiv.sh)"
```

Le mode avance permet de fournir l'URL publique, l'issuer Keycloak, le secret OIDC et, facultativement, le jeton Cloudflare Tunnel. Les routes Cloudflare doivent envoyer le domaine public vers le port `8080` du LXC. Le connecteur ChatGPT utilise `https://perspectiv.example.com/mcp`.

Les releases sont installees dans `/opt/perspectiv/releases`, la release active est exposee par `/opt/perspectiv/current`, la configuration est dans `/etc/perspectiv/perspectiv.env` et les sauvegardes dans `/var/lib/perspectiv/backups`. Relancer le script Community Scripts sur le conteneur existant declenche `update_script()` : sauvegarde PostgreSQL et configuration, nouvelle release isolee, migration Alembic, controle `/health`, puis restauration automatique de la base et de l'ancienne release en cas d'echec. Les sauvegardes Proxmox/PBS restent recommandees.

Pour importer la base SQLite historique apres installation :

```bash
set -a; source /etc/perspectiv/perspectiv.env; set +a
/opt/perspectiv/current/.venv/bin/perspectiv migrate-sqlite /chemin/perspectiv.db
```

### Connecteur ChatGPT

Creer un connecteur MCP dans ChatGPT avec l'URL `https://perspectiv.example.com/mcp`, le client OAuth public `perspectiv-mcp` et l'URL de retour affichee par ChatGPT. Si cette URL differe de la valeur par defaut, relancer `tools/configure_keycloak.py --chatgpt-redirect-uri ...`. Les outils MCP sont des commandes metier bornees : aucun SQL libre n'est disponible, les mutations sont auditees et toute suppression exige une previsualisation suivie d'un jeton de confirmation temporaire.

Les scopes disponibles sont `read`, `timesheet:write`, `planning:write`, `projects:write`, `delete` et `admin`. Les membres ne peuvent modifier que leurs propres pointages et planifications; les managers administrent les projets; les administrateurs gerent aussi les utilisateurs et l'audit.

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
