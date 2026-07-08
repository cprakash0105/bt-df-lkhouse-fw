#!/bin/bash
# EastSide Dagster VM — Startup Script
# Installs Dagster + deps, configures systemd services, sets up nginx reverse proxy.
# Runs once on first boot (idempotent — safe to re-run).

set -e

DAGSTER_HOME="/opt/dagster"
DAGSTER_USER="dagster"
WORKSPACE_DIR="/opt/dagster/workspace"
VENV_DIR="/opt/dagster/venv"

# ============================================================
# 1. System packages
# ============================================================
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx git

# ============================================================
# 2. Dagster user + directories
# ============================================================
id -u $DAGSTER_USER &>/dev/null || useradd -r -m -d $DAGSTER_HOME -s /bin/bash $DAGSTER_USER
mkdir -p $WORKSPACE_DIR $DAGSTER_HOME/storage $DAGSTER_HOME/logs
chown -R $DAGSTER_USER:$DAGSTER_USER $DAGSTER_HOME

# ============================================================
# 3. Python venv + Dagster install
# ============================================================
if [ ! -f "$VENV_DIR/bin/dagster" ]; then
  python3 -m venv $VENV_DIR
  $VENV_DIR/bin/pip install --quiet --upgrade pip
  $VENV_DIR/bin/pip install --quiet \
    dagster dagster-webserver \
    google-cloud-dataproc google-cloud-storage google-cloud-bigquery pyyaml
fi

# ============================================================
# 4. Pull workspace code from GCS
# ============================================================
gsutil -q cp gs://eastside-lakehouse/orchestration/workspace.yaml $WORKSPACE_DIR/
gsutil -q -m cp -r gs://eastside-lakehouse/orchestration/eastside_dagster/ $WORKSPACE_DIR/
gsutil -q cp gs://eastside-lakehouse/orchestration/setup.py $WORKSPACE_DIR/

# Install the dagster project package
cd $WORKSPACE_DIR && $VENV_DIR/bin/pip install --quiet -e .
chown -R $DAGSTER_USER:$DAGSTER_USER $DAGSTER_HOME

# ============================================================
# 5. Dagster config (dagster.yaml)
# ============================================================
cat > $DAGSTER_HOME/dagster.yaml << 'EOF'
storage:
  sqlite:
    base_dir: /opt/dagster/storage

run_launcher:
  module: dagster.core.launcher
  class: DefaultRunLauncher

telemetry:
  enabled: false
EOF
chown $DAGSTER_USER:$DAGSTER_USER $DAGSTER_HOME/dagster.yaml

# ============================================================
# 6. Systemd — Dagster Daemon (schedules, sensors, run queue)
# ============================================================
cat > /etc/systemd/system/dagster-daemon.service << EOF
[Unit]
Description=Dagster Daemon
After=network.target

[Service]
Type=simple
User=$DAGSTER_USER
Environment=DAGSTER_HOME=$DAGSTER_HOME
WorkingDirectory=$WORKSPACE_DIR
ExecStart=$VENV_DIR/bin/dagster-daemon run -w $WORKSPACE_DIR/workspace.yaml
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# ============================================================
# 7. Systemd — Dagster Webserver (UI on port 3000 internally)
# ============================================================
cat > /etc/systemd/system/dagster-webserver.service << EOF
[Unit]
Description=Dagster Webserver
After=network.target

[Service]
Type=simple
User=$DAGSTER_USER
Environment=DAGSTER_HOME=$DAGSTER_HOME
WorkingDirectory=$WORKSPACE_DIR
ExecStart=$VENV_DIR/bin/dagster-webserver -h 127.0.0.1 -p 3000 -w $WORKSPACE_DIR/workspace.yaml
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# ============================================================
# 8. Nginx reverse proxy (port 80 → localhost:3000)
# ============================================================
cat > /etc/nginx/sites-available/dagster << 'EOF'
server {
    listen 80 default_server;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
EOF

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/dagster /etc/nginx/sites-enabled/dagster

# ============================================================
# 9. Enable and start everything
# ============================================================
systemctl daemon-reload
systemctl enable dagster-daemon dagster-webserver nginx
systemctl restart dagster-daemon dagster-webserver nginx

echo "[dagster-startup] Complete. Dagster UI available on port 80."
