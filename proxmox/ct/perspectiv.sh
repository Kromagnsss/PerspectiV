#!/usr/bin/env bash
_cs_boot="${COMMUNITY_SCRIPTS_CORE_DIR:-$(dirname "${BASH_SOURCE[0]}")/../../../core}/core/build.func"
source "$_cs_boot" 2>/dev/null || source <(curl -fsSL "${COMMUNITY_SCRIPTS_CORE_URL:-https://raw.githubusercontent.com/community-scripts/core/main}/core/build.func")
# Source: https://github.com/Kromagnsss/PerspectiV

APP="PerspectiV"
var_tags="${var_tags:-project-management;planning;timesheet}"
var_cpu="${var_cpu:-2}"
var_ram="${var_ram:-4096}"
var_disk="${var_disk:-16}"
var_os="${var_os:-debian}"
var_version="${var_version:-13}"
var_arm64="${var_arm64:-yes}"
var_unprivileged="${var_unprivileged:-1}"

export var_public_url="${var_public_url:-}"
export var_oidc_issuer="${var_oidc_issuer:-}"
export var_oidc_client_id="${var_oidc_client_id:-perspectiv-web}"
export var_oidc_client_secret="${var_oidc_client_secret:-}"
export var_admin_user="${var_admin_user:-admin}"
export var_admin_name="${var_admin_name:-Administrateur}"
export var_admin_email="${var_admin_email:-}"
export var_admin_pass="${var_admin_pass:-}"
export var_cloudflare_token="${var_cloudflare_token:-}"

header_info "$APP"
variables
color
catch_errors

function update_script() {
  header_info
  check_container_storage
  check_container_resources

  if [[ ! -L /opt/perspectiv/current ]]; then
    msg_error "No PerspectiV Installation Found!"
    exit 1
  fi

  if check_for_gh_release "perspectiv" "Kromagnsss/PerspectiV"; then
    timestamp=$(date +%Y%m%d_%H%M%S)
    backup_dir="/var/lib/perspectiv/backups/${timestamp}"
    mkdir -p "$backup_dir"
    set -a
    source /etc/perspectiv/perspectiv.env
    set +a
    pg_url="${PERSPECTIV_DATABASE_URL/postgresql+psycopg:/postgresql:}"
    previous_release=$(readlink /opt/perspectiv/current)

    msg_info "Backing up PerspectiV"
    pg_dump --format=custom --file="$backup_dir/database.dump" "$pg_url"
    cp /etc/perspectiv/perspectiv.env "$backup_dir/perspectiv.env"
    msg_ok "Backed up PerspectiV"

    msg_info "Stopping PerspectiV"
    systemctl stop perspectiv-ui perspectiv-api
    msg_ok "Stopped PerspectiV"

    mv /opt/perspectiv "/opt/perspectiv-root-${timestamp}"
    if ! CLEAN_INSTALL=1 fetch_and_deploy_gh_release "perspectiv" "Kromagnsss/PerspectiV" "tarball"; then
      mv "/opt/perspectiv-root-${timestamp}" /opt/perspectiv
      systemctl start perspectiv-api perspectiv-ui
      msg_error "Release download failed; the previous release is still active"
      exit 1
    fi
    mv /opt/perspectiv "/opt/perspectiv-release-${timestamp}"
    mv "/opt/perspectiv-root-${timestamp}" /opt/perspectiv
    mv "/opt/perspectiv-release-${timestamp}" "/opt/perspectiv/releases/${timestamp}"
    ln -sfn "releases/${timestamp}" /opt/perspectiv/current
    cd /opt/perspectiv/current
    if uv sync --locked --no-editable --no-dev && .venv/bin/alembic upgrade head; then
      install -m 0755 /opt/perspectiv/current/proxmox/scripts/perspectiv-update-check.sh /usr/local/sbin/perspectiv-update-check
      systemctl start perspectiv-api perspectiv-ui
      if curl -fsS --retry 12 --retry-delay 2 http://127.0.0.1:8000/health >/dev/null; then
        find /var/lib/perspectiv/backups -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | tail -n +8 | cut -d' ' -f2- | xargs -r rm -rf
        find /opt/perspectiv/releases -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | tail -n +5 | cut -d' ' -f2- | xargs -r rm -rf
        msg_ok "Updated PerspectiV successfully"
        exit 0
      fi
    fi

    msg_error "PerspectiV health check failed; restoring the previous release"
    systemctl stop perspectiv-ui perspectiv-api || true
    ln -sfn "$previous_release" /opt/perspectiv/current
    rm -rf "/opt/perspectiv/releases/${timestamp}"
    pg_restore --clean --if-exists --no-owner --dbname="$pg_url" "$backup_dir/database.dump"
    systemctl start perspectiv-api perspectiv-ui
    curl -fsS --retry 12 --retry-delay 2 http://127.0.0.1:8000/health >/dev/null || msg_error "Rollback failed; restore $backup_dir manually"
    exit 1
  fi
  exit 0
}

start
build_container
description

msg_ok "Completed Successfully!\n"
echo -e "${INFO}${YW}Access PerspectiV using:${CL}"
echo -e "${GATEWAY}${BGN}http://${IP}:8080${CL}"
