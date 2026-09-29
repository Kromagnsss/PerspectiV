#!/usr/bin/env bash
# Source: https://github.com/Kromagnsss/PerspectiV

source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
color
verb_ip6
catch_errors
setting_up_container
network_check
update_os

if [[ -z "${var_public_url:-}" || -z "${var_oidc_issuer:-}" || -z "${var_oidc_client_secret:-}" ]]; then
  msg_error "var_public_url, var_oidc_issuer and var_oidc_client_secret are required; run tools/configure_keycloak.py first"
  exit 1
fi

msg_info "Installing PerspectiV dependencies"
$STD apt install -y build-essential libpq-dev nginx postgresql-17 postgresql-client
msg_ok "Installed PerspectiV dependencies"

PG_VERSION="17" setup_postgresql
PG_DB_NAME="perspectiv" PG_DB_USER="perspectiv" setup_postgresql_db
PYTHON_VERSION="3.12" setup_uv
fetch_and_deploy_gh_release "perspectiv" "Kromagnsss/PerspectiV" "tarball"

initial_release="$(date +%Y%m%d_%H%M%S)"
mv /opt/perspectiv "/opt/perspectiv-${initial_release}"
mkdir -p /opt/perspectiv/releases
mv "/opt/perspectiv-${initial_release}" "/opt/perspectiv/releases/${initial_release}"
ln -sfn "releases/${initial_release}" /opt/perspectiv/current

if [[ -z "${var_admin_pass:-}" ]]; then
  var_admin_pass=$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)
fi

msg_info "Setting up PerspectiV"
cd /opt/perspectiv/current
$STD uv sync --locked --no-editable --no-dev
mkdir -p /etc/perspectiv /var/lib/perspectiv/backups /var/log/perspectiv
cookie_secret=$(openssl rand -hex 32)
cat <<EOF >/etc/perspectiv/perspectiv.env
PERSPECTIV_ENV=production
PERSPECTIV_DATABASE_URL=postgresql+psycopg://perspectiv:${PG_DB_PASS}@127.0.0.1:5432/perspectiv
PERSPECTIV_PUBLIC_URL=${var_public_url}
PERSPECTIV_OIDC_ISSUER=${var_oidc_issuer:-}
PERSPECTIV_OIDC_AUDIENCE=perspectiv-api
PERSPECTIV_MCP_ALLOWED_HOSTS=$(echo "${var_public_url}" | sed -E 's#https?://##'),127.0.0.1:*,localhost:*
PERSPECTIV_MCP_ALLOWED_ORIGINS=${var_public_url},http://127.0.0.1:*,http://localhost:*
PERSPECTIV_BOOTSTRAP_ADMIN_USERNAME=${var_admin_user}
PERSPECTIV_BOOTSTRAP_ADMIN_NAME=${var_admin_name}
PERSPECTIV_BOOTSTRAP_ADMIN_EMAIL=${var_admin_email:-}
PERSPECTIV_BOOTSTRAP_ADMIN_PASSWORD=${var_admin_pass}
EOF
chmod 600 /etc/perspectiv/perspectiv.env

mkdir -p /root/.streamlit
cat <<EOF >/root/.streamlit/secrets.toml
[auth]
redirect_uri = "${var_public_url}/oauth2callback"
cookie_secret = "${cookie_secret}"

[auth.keycloak]
client_id = "${var_oidc_client_id}"
client_secret = "${var_oidc_client_secret}"
server_metadata_url = "${var_oidc_issuer}/.well-known/openid-configuration"
EOF
chmod 600 /root/.streamlit/secrets.toml

set -a
source /etc/perspectiv/perspectiv.env
set +a
$STD /opt/perspectiv/current/.venv/bin/alembic upgrade head
$STD /opt/perspectiv/current/.venv/bin/perspectiv init-db
msg_ok "Set up PerspectiV"

msg_info "Creating PerspectiV services"
cat <<EOF >/etc/systemd/system/perspectiv-api.service
[Unit]
Description=PerspectiV API and MCP
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/perspectiv/current
EnvironmentFile=/etc/perspectiv/perspectiv.env
ExecStart=/opt/perspectiv/current/.venv/bin/uvicorn perspectiv.api:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

cat <<EOF >/etc/systemd/system/perspectiv-ui.service
[Unit]
Description=PerspectiV Streamlit UI
After=network-online.target perspectiv-api.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/perspectiv/current
EnvironmentFile=/etc/perspectiv/perspectiv.env
ExecStart=/opt/perspectiv/current/.venv/bin/streamlit run streamlit_app.py --server.address=127.0.0.1 --server.port=8501 --server.headless=true
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

cat <<'EOF' >/etc/nginx/sites-available/perspectiv
map $http_upgrade $connection_upgrade {
  default upgrade;
  '' close;
}
limit_req_zone $binary_remote_addr zone=perspectiv_api:10m rate=30r/s;
server {
  listen 8080;
  server_name _;
  client_max_body_size 25m;
  location = /health { proxy_pass http://127.0.0.1:8000/health; }
  location ^~ /.well-known/ { proxy_pass http://127.0.0.1:8000; }
  location ^~ /api/ { limit_req zone=perspectiv_api burst=60 nodelay; proxy_pass http://127.0.0.1:8000; proxy_set_header X-Forwarded-Proto $scheme; proxy_set_header X-Forwarded-Host $host; }
  location ^~ /mcp { limit_req zone=perspectiv_api burst=60 nodelay; proxy_pass http://127.0.0.1:8000; proxy_buffering off; proxy_read_timeout 3600s; proxy_set_header Host $host; }
  location / {
    proxy_pass http://127.0.0.1:8501;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 86400;
  }
}
EOF
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/perspectiv /etc/nginx/sites-enabled/perspectiv
nginx -t

install -m 0755 /opt/perspectiv/current/proxmox/scripts/perspectiv-update-check.sh /usr/local/sbin/perspectiv-update-check
systemctl daemon-reload
systemctl enable -q --now perspectiv-api perspectiv-ui nginx
msg_ok "Created PerspectiV services"

if [[ -n "${var_cloudflare_token:-}" ]]; then
  msg_info "Installing Cloudflare Tunnel for PerspectiV"
  arch=$(dpkg --print-architecture)
  curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${arch}.deb" -o /tmp/cloudflared.deb
  $STD apt install -y /tmp/cloudflared.deb
  cloudflared service install "${var_cloudflare_token}"
  rm -f /tmp/cloudflared.deb
  msg_ok "Installed Cloudflare Tunnel for PerspectiV"
fi

cat <<EOF >/root/perspectiv-credentials.txt
URL: ${var_public_url}
Initial administrator: ${var_admin_user}
Initial password: ${var_admin_pass}
API health: ${var_public_url}/health
MCP endpoint: ${var_public_url}/mcp
EOF
chmod 600 /root/perspectiv-credentials.txt

motd_ssh
customize
cleanup_lxc
