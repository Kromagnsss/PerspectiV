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

  updater=/usr/local/sbin/perspectiv-update
  if [[ ! -x "${updater}" ]]; then
    msg_info "Installing PerspectiV updater"
    curl -fsSL --retry 3 \
      "https://raw.githubusercontent.com/Kromagnsss/PerspectiV/main/proxmox/scripts/perspectiv-update.sh" \
      -o "${updater}"
    chmod 0755 "${updater}"
    ln -sfn "${updater}" /usr/bin/update
    msg_ok "Installed PerspectiV updater"
  fi

  exec "${updater}" "$@"
}

start
build_container
description

msg_ok "Completed Successfully!\n"
echo -e "${INFO}${YW}Access PerspectiV using:${CL}"
echo -e "${GATEWAY}${BGN}http://${IP}:8080${CL}"
