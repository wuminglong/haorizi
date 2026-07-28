#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

usage() {
  cat >&2 <<'EOF'
Usage: sudo ./deploy/bootstrap-github-deploy.sh \
  --repo-url https://github.com/OWNER/haorizi.git \
  --sha 40_CHARACTER_MAIN_SHA \
  --public-key-file /path/to/github-actions.pub
EOF
  exit 64
}

[[ "$(id -u)" -eq 0 ]] || {
  echo "bootstrap must run as root" >&2
  exit 1
}

repo_url=""
target_sha=""
public_key_file=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-url) repo_url="${2-}"; shift 2 ;;
    --sha) target_sha="${2-}"; shift 2 ;;
    --public-key-file) public_key_file="${2-}"; shift 2 ;;
    *) usage ;;
  esac
done

[[ "$repo_url" =~ ^https://github\.com/[A-Za-z0-9_.-]+/haorizi\.git$ ]] || usage
[[ "$target_sha" =~ ^[0-9a-f]{40}$ ]] || usage
[[ -f "$public_key_file" ]] || usage

readonly APP_ROOT="/opt/haorizi"
readonly DEPLOY_USER="haorizi-deploy"
readonly RUNTIME_GROUP="haorizi-runtime"
readonly DEPLOY_HOME="/var/lib/haorizi-deploy"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ -d "$APP_ROOT/backend" && ! -L "$APP_ROOT/backend" ]] || {
  echo "expected the existing /opt/haorizi/backend directory" >&2
  exit 1
}
[[ -d "$APP_ROOT/frontend" && ! -L "$APP_ROOT/frontend" ]] || {
  echo "expected the existing /opt/haorizi/frontend directory" >&2
  exit 1
}
[[ -f "$APP_ROOT/backend/.env" ]] || {
  echo "existing production environment file was not found" >&2
  exit 1
}

getent group "$RUNTIME_GROUP" >/dev/null || groupadd --system "$RUNTIME_GROUP"
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$DEPLOY_HOME" --shell /bin/bash "$DEPLOY_USER"
fi
usermod -a -G "$RUNTIME_GROUP" "$DEPLOY_USER"
usermod -a -G "$RUNTIME_GROUP" ubuntu
passwd --lock "$DEPLOY_USER" >/dev/null 2>&1 || true

install -d -o root -g "$RUNTIME_GROUP" -m 0750 "$APP_ROOT/shared"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0750 \
  "$APP_ROOT/releases" "$APP_ROOT/backups"

if [[ ! -f "$APP_ROOT/shared/backend.env" ]]; then
  install -o root -g "$RUNTIME_GROUP" -m 0640 \
    "$APP_ROOT/backend/.env" "$APP_ROOT/shared/backend.env"
fi

python3 - "$APP_ROOT/shared/backend.env" <<'PY'
from pathlib import Path
import os
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
updated = []
found = False
for line in lines:
    if line.startswith("AUTO_CREATE_TABLES="):
        updated.append("AUTO_CREATE_TABLES=false")
        found = True
    else:
        updated.append(line)
if not found:
    updated.append("AUTO_CREATE_TABLES=false")
temporary = path.with_suffix(".tmp")
temporary.write_text("\n".join(updated) + "\n", encoding="utf-8")
os.chmod(temporary, 0o640)
os.replace(temporary, path)
PY
chown root:"$RUNTIME_GROUP" "$APP_ROOT/shared/backend.env"

install -o root -g root -m 0755 \
  "$SCRIPT_DIR/server/haorizi-deploy" /usr/local/sbin/haorizi-deploy
install -o root -g root -m 0755 \
  "$SCRIPT_DIR/server/haorizi-github-command" /usr/local/sbin/haorizi-github-command

cat > /etc/haorizi-deploy.conf <<EOF
HAORIZI_REPO_URL='$repo_url'
EOF
chown root:root /etc/haorizi-deploy.conf
chmod 0644 /etc/haorizi-deploy.conf

cat > /etc/sudoers.d/haorizi-deploy <<'EOF'
Defaults:haorizi-deploy !requiretty
haorizi-deploy ALL=(root) NOPASSWD: /usr/local/sbin/haorizi-deploy *
EOF
chmod 0440 /etc/sudoers.d/haorizi-deploy
visudo -cf /etc/sudoers.d/haorizi-deploy >/dev/null

public_key="$(sed -n '1p' "$public_key_file")"
[[ "$public_key" =~ ^ssh-ed25519\  ]] || {
  echo "the deployment public key must be an ssh-ed25519 key" >&2
  exit 1
}

install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0700 "$DEPLOY_HOME/.ssh"
printf 'restrict,command="/usr/local/sbin/haorizi-github-command" %s\n' "$public_key" \
  > "$DEPLOY_HOME/.ssh/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "$DEPLOY_HOME/.ssh/authorized_keys"
chmod 0600 "$DEPLOY_HOME/.ssh/authorized_keys"

/usr/local/sbin/haorizi-deploy --bootstrap "$target_sha"

systemctl is-active --quiet haorizi-api.service
systemctl is-active --quiet haorizi-worker.service
curl --fail --silent --show-error http://127.0.0.1:8000/api/public/health >/dev/null

echo "GitHub deployment bootstrap completed for $target_sha"
