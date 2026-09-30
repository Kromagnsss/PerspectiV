#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="${PERSPECTIV_GITHUB_REPOSITORY:-Kromagnsss/PerspectiV}"
INSTALL_ROOT="${PERSPECTIV_INSTALL_ROOT:-/opt/perspectiv}"
CONFIG_FILE="${PERSPECTIV_CONFIG_FILE:-/etc/perspectiv/perspectiv.env}"
BACKUP_ROOT="${PERSPECTIV_BACKUP_ROOT:-/var/lib/perspectiv/backups}"
HEALTH_URL="${PERSPECTIV_HEALTH_URL:-http://127.0.0.1:8000/health}"
KEEP_BACKUPS="${PERSPECTIV_KEEP_BACKUPS:-7}"
KEEP_RELEASES="${PERSPECTIV_KEEP_RELEASES:-4}"
HEALTH_ATTEMPTS="${PERSPECTIV_HEALTH_ATTEMPTS:-30}"
HEALTH_DELAY="${PERSPECTIV_HEALTH_DELAY:-2}"
FORCE=0
CHECK_ONLY=0
ALLOW_DOWNGRADE=0
RESTORE_LATEST=0
RESTORE_DIR=""
LIST_BACKUPS=0

usage() {
  cat <<'EOF'
Usage: update [--check] [--force] [--allow-downgrade]
              [--list-backups] [--restore-latest] [--restore CHEMIN]

  --check  Affiche la version disponible sans modifier l'installation.
  --force  Reinstalle la derniere version meme si elle est deja active.
  --allow-downgrade  Autorise explicitement l'installation d'une version inferieure.
  --list-backups     Liste les sauvegardes disponibles et leur release precedente.
  --restore-latest   Restaure la derniere sauvegarde et sa release precedente.
  --restore CHEMIN   Restaure explicitement la sauvegarde indiquee.
EOF
}

log() { printf '[PerspectiV] %s\n' "$*"; }
fail() { printf '[PerspectiV] ERREUR: %s\n' "$*" >&2; exit 1; }

while (($#)); do
  case "$1" in
    --check) CHECK_ONLY=1 ;;
    --force) FORCE=1 ;;
    --allow-downgrade) ALLOW_DOWNGRADE=1 ;;
    --list-backups) LIST_BACKUPS=1 ;;
    --restore-latest) RESTORE_LATEST=1 ;;
    --restore)
      shift
      [[ $# -gt 0 ]] || fail "--restore attend le chemin d'une sauvegarde."
      RESTORE_DIR="$1"
      ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; fail "Option inconnue: $1" ;;
  esac
  shift
done

[[ ${EUID} -eq 0 ]] || fail "La mise a jour doit etre executee en tant que root."
[[ -L "${INSTALL_ROOT}/current" ]] || fail "Installation absente: ${INSTALL_ROOT}/current est introuvable."
[[ -f "${CONFIG_FILE}" ]] || fail "Configuration absente: ${CONFIG_FILE} est introuvable."

if ! command -v jq >/dev/null 2>&1; then
  log "Installation de jq, requis pour interroger les releases GitHub..."
  apt-get update -qq
  apt-get install -y -qq jq
fi

for command in curl jq tar uv pg_dump pg_restore psql systemctl flock sha256sum; do
  command -v "${command}" >/dev/null 2>&1 || fail "Commande requise absente: ${command}"
done

exec 9>/run/lock/perspectiv-update.lock
flock -n 9 || fail "Une autre mise a jour PerspectiV est deja en cours."

HEALTH_RESPONSE=""
wait_for_health() {
  attempt=1
  while ((attempt <= HEALTH_ATTEMPTS)); do
    if HEALTH_RESPONSE="$(curl -fsS --connect-timeout 2 "${HEALTH_URL}" 2>/dev/null)"; then
      return 0
    fi
    sleep "${HEALTH_DELAY}"
    attempt=$((attempt + 1))
  done
  return 1
}

restore_backup() {
  restore_dir="$1"
  [[ -f "${restore_dir}/database.dump" ]] || fail "Sauvegarde PostgreSQL absente dans ${restore_dir}."
  set -a
  # shellcheck disable=SC1090
  source "${CONFIG_FILE}"
  set +a
  [[ -n "${PERSPECTIV_DATABASE_URL:-}" ]] || fail "PERSPECTIV_DATABASE_URL est absent de la configuration."
  restore_pg_url="${PERSPECTIV_DATABASE_URL/postgresql+psycopg:/postgresql:}"
  restore_release=""
  if [[ -f "${restore_dir}/previous-release" ]]; then
    restore_release="$(cat "${restore_dir}/previous-release")"
    [[ -d "${restore_release}" ]] || fail "Release de restauration introuvable: ${restore_release}"
  fi

  log "Arret des services pour restaurer ${restore_dir}..."
  systemctl stop perspectiv-ui perspectiv-api
  if [[ -n "${restore_release}" ]]; then
    ln -sfn "${restore_release}" "${INSTALL_ROOT}/current"
  fi
  psql "${restore_pg_url}" -v ON_ERROR_STOP=1 -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
  pg_restore --exit-on-error --no-owner --dbname="${restore_pg_url}" "${restore_dir}/database.dump"
  systemctl start perspectiv-api perspectiv-ui
  if ! wait_for_health; then
    journalctl -u perspectiv-api -u perspectiv-ui -n 100 --no-pager >&2 || true
    fail "La restauration est terminee mais le healthcheck echoue."
  fi
  log "Restauration terminee avec succes."
}

if ((LIST_BACKUPS)); then
  printf '%-32s %s\n' "SAUVEGARDE" "RELEASE PRECEDENTE"
  while IFS= read -r backup_path; do
    previous="inconnue"
    [[ -f "${backup_path}/previous-release" ]] && previous="$(cat "${backup_path}/previous-release")"
    printf '%-32s %s\n' "$(basename "${backup_path}")" "${previous}"
  done < <(find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -exec test -f '{}/database.dump' \; -print | sort)
  exit 0
fi

if [[ -n "${RESTORE_DIR}" ]]; then
  restore_backup "${RESTORE_DIR}"
  exit 0
fi

if ((RESTORE_LATEST)); then
  latest_backup="$(find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -exec test -f '{}/database.dump' \; -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"
  [[ -n "${latest_backup}" ]] || fail "Aucune sauvegarde PerspectiV utilisable."
  restore_backup "${latest_backup}"
  exit 0
fi

api_url="https://api.github.com/repos/${REPOSITORY}/releases/latest"
release_json="$(curl -fsSL --retry 3 --connect-timeout 10 "${api_url}")" || fail "Impossible de consulter la derniere release GitHub."
latest_tag="$(jq -er '.tag_name' <<<"${release_json}")" || fail "La release GitHub ne contient pas de tag."
latest_version="${latest_tag#v}"
archive_name="perspectiv-${latest_version}.tar.gz"
archive_url="$(jq -r --arg name "${archive_name}" '.assets[]? | select(.name == $name) | .browser_download_url' <<<"${release_json}" | head -n1)"
if [[ -z "${archive_url}" ]]; then
  archive_url="$(jq -er '.tarball_url' <<<"${release_json}")" || fail "Archive de release introuvable."
  archive_name="github-${latest_tag}.tar.gz"
fi
current_version="$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "${INSTALL_ROOT}/current/perspectiv/version.py" 2>/dev/null | head -n1)"
current_version="${current_version:-inconnue}"

log "Version installee: ${current_version}"
log "Derniere release:  ${latest_version}"
if ((CHECK_ONLY)); then
  if [[ "${current_version}" == "${latest_version}" ]]; then
    log "PerspectiV est a jour."
  elif [[ "${current_version}" != "inconnue" && "$(printf '%s\n%s\n' "${latest_version}" "${current_version}" | sort -V | head -n1)" == "${latest_version}" ]]; then
    log "La release publiee est plus ancienne que l'installation; aucune mise a jour ne sera appliquee."
  else
    log "Une mise a jour est disponible."
  fi
  exit 0
fi
if [[ "${current_version}" == "${latest_version}" && ${FORCE} -eq 0 ]]; then
  log "PerspectiV est deja a jour. Utilisez --force pour reinstaller cette release."
  exit 0
fi
if [[ "${current_version}" != "inconnue" && "$(printf '%s\n%s\n' "${latest_version}" "${current_version}" | sort -V | head -n1)" == "${latest_version}" && "${latest_version}" != "${current_version}" && ${ALLOW_DOWNGRADE} -eq 0 ]]; then
  fail "Refus du downgrade ${current_version} -> ${latest_version}. Utilisez --allow-downgrade uniquement si cette operation est voulue."
fi

timestamp="$(date +%Y%m%d_%H%M%S)"
backup_dir="${BACKUP_ROOT}/${timestamp}"
release_dir="${INSTALL_ROOT}/releases/${latest_version}-${timestamp}"
temp_dir="$(mktemp -d /tmp/perspectiv-update.XXXXXX)"
archive="${temp_dir}/${archive_name}"
previous_release="$(readlink -f "${INSTALL_ROOT}/current")"
activated=0
rollback_needed=0

cleanup() {
  rm -rf -- "${temp_dir}"
  if [[ ${activated} -eq 0 && -d "${release_dir}" ]]; then
    rm -rf -- "${release_dir}"
  fi
}
trap cleanup EXIT

log "Telechargement de ${latest_tag}..."
curl -fL --retry 3 --connect-timeout 10 "${archive_url}" -o "${archive}"
tar -tzf "${archive}" >/dev/null || fail "L'archive telechargee est invalide."

checksum_url="$(jq -r --arg name "${archive_name}.sha256" '.assets[]? | select(.name == $name) | .browser_download_url' <<<"${release_json}" | head -n1)"
if [[ -n "${checksum_url}" ]]; then
  checksum_file="${temp_dir}/checksums.sha256"
  curl -fsSL --retry 3 "${checksum_url}" -o "${checksum_file}"
  expected_checksum="$(grep -Eio '[a-f0-9]{64}' "${checksum_file}" | head -n1)"
  [[ -n "${expected_checksum}" ]] || fail "Somme SHA-256 illisible."
  actual_checksum="$(sha256sum "${archive}" | awk '{print $1}')"
  [[ "${actual_checksum}" == "${expected_checksum}" ]] || fail "La somme SHA-256 de l'archive ne correspond pas."
  log "Somme SHA-256 verifiee."
else
  log "Aucun fichier SHA-256 publie; integrite tar et transport HTTPS verifies."
fi

mkdir -p "${release_dir}" "${backup_dir}"
tar -xzf "${archive}" --strip-components=1 -C "${release_dir}"
[[ -f "${release_dir}/pyproject.toml" && -f "${release_dir}/uv.lock" ]] || fail "La release ne contient pas une application PerspectiV complete."
archive_version="$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "${release_dir}/perspectiv/version.py" | head -n1)"
[[ "${archive_version}" == "${latest_version}" ]] || fail "Le tag ${latest_tag} contient la version ${archive_version:-inconnue}; publication incoherente refusee."

log "Preparation de l'environnement Python..."
(
  cd "${release_dir}"
  uv sync --locked --no-editable --no-dev
)

set -a
# shellcheck disable=SC1090
source "${CONFIG_FILE}"
set +a
[[ -n "${PERSPECTIV_DATABASE_URL:-}" ]] || fail "PERSPECTIV_DATABASE_URL est absent de la configuration."
pg_url="${PERSPECTIV_DATABASE_URL/postgresql+psycopg:/postgresql:}"

log "Sauvegarde de PostgreSQL et de la configuration..."
pg_dump --format=custom --file="${backup_dir}/database.dump" "${pg_url}"
cp -a "${CONFIG_FILE}" "${backup_dir}/perspectiv.env"
if [[ -f /root/.streamlit/secrets.toml ]]; then
  mkdir -p "${backup_dir}/streamlit"
  cp -a /root/.streamlit/secrets.toml "${backup_dir}/streamlit/secrets.toml"
fi
printf '%s\n' "${previous_release}" >"${backup_dir}/previous-release"

rollback() {
  rollback_needed=0
  set +e
  log "Echec de la mise a jour; restauration de la release et de la base..."
  systemctl stop perspectiv-ui perspectiv-api >/dev/null 2>&1 || true
  ln -sfn "${previous_release}" "${INSTALL_ROOT}/current"
  restore_ok=1
  psql "${pg_url}" -v ON_ERROR_STOP=1 -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;' || restore_ok=0
  pg_restore --exit-on-error --no-owner --dbname="${pg_url}" "${backup_dir}/database.dump" || restore_ok=0
  systemctl start perspectiv-api perspectiv-ui || restore_ok=0
  if [[ ${restore_ok} -eq 1 ]] && wait_for_health; then
    log "Retour arriere termine."
  else
    printf '[PerspectiV] ERREUR: retour arriere incomplet; sauvegarde: %s\n' "${backup_dir}" >&2
    journalctl -u perspectiv-api -u perspectiv-ui -n 100 --no-pager >&2 || true
  fi
  set -e
}

on_error() {
  exit_code=$?
  trap - ERR
  if [[ ${rollback_needed} -eq 1 ]]; then
    rollback
  fi
  exit "${exit_code}"
}
trap on_error ERR

log "Application des migrations et activation de ${latest_tag}..."
rollback_needed=1
systemctl stop perspectiv-ui perspectiv-api
if ! (
  cd "${release_dir}"
  .venv/bin/alembic upgrade head
); then
  rollback
  exit 1
fi

printf '%s\n' "${latest_tag}" >"${release_dir}/.perspectiv-release"
ln -sfn "${release_dir}" "${INSTALL_ROOT}/current"
systemctl daemon-reload
systemctl start perspectiv-api perspectiv-ui

if ! wait_for_health; then
  journalctl -u perspectiv-api -u perspectiv-ui -n 100 --no-pager >&2 || true
  rollback
  exit 1
fi
active_version="$(jq -r '.version // empty' <<<"${HEALTH_RESPONSE}")"
if [[ "${active_version}" != "${latest_version}" ]]; then
  printf '[PerspectiV] ERREUR: /health annonce la version %s au lieu de %s.\n' "${active_version:-inconnue}" "${latest_version}" >&2
  rollback
  exit 1
fi
activated=1
rollback_needed=0

install -m 0755 "${INSTALL_ROOT}/current/proxmox/scripts/perspectiv-update.sh" /usr/local/sbin/perspectiv-update
install -m 0755 "${INSTALL_ROOT}/current/proxmox/scripts/perspectiv-update-check.sh" /usr/local/sbin/perspectiv-update-check
ln -sfn /usr/local/sbin/perspectiv-update /usr/bin/update

find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\0' \
  | sort -z -nr | tail -z -n "+$((KEEP_BACKUPS + 1))" | cut -z -d' ' -f2- | xargs -0r rm -rf --
find "${INSTALL_ROOT}/releases" -mindepth 1 -maxdepth 1 -type d ! -samefile "${INSTALL_ROOT}/current" -printf '%T@ %p\0' \
  | sort -z -nr | tail -z -n "+$((KEEP_RELEASES + 1))" | cut -z -d' ' -f2- | xargs -0r rm -rf --

log "Mise a jour vers ${latest_tag} terminee avec succes."
log "Sauvegarde: ${backup_dir}"
