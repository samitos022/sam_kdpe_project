#!/usr/bin/env bash
#
# Idempotent Cloud Agent install script for the KDPE project.
#
# Prepares three services that normally run via docker-compose, but here they
# run natively (Docker is not available in the Cloud Agent VM):
#   - Neo4j 5  (graph database)         -> $HOME/neo4j
#   - FastAPI backend (Python venv)     -> code/.venv
#   - React + Vite frontend (Node)      -> code/frontend/node_modules
#
# This script only prepares durable state. Long-running services are launched
# from the `terminals` entries in .cursor/environment.json.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODE_DIR="$REPO_ROOT/code"
NEO4J_HOME="$HOME/neo4j"
NEO4J_VERSION="5.26.0"

log() { echo "[install] $*"; }

sudo_if_needed() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

# ── 1. System packages: Python venv support + a JRE for Neo4j ────────────────
log "Ensuring system packages (python venv + JRE)..."
NEED_PKGS=()
python3 -c "import venv, ensurepip" >/dev/null 2>&1 || NEED_PKGS+=("python3-venv")
command -v java >/dev/null 2>&1 || NEED_PKGS+=("openjdk-21-jre-headless")
command -v wget >/dev/null 2>&1 || NEED_PKGS+=("wget")
if [ "${#NEED_PKGS[@]}" -gt 0 ]; then
  log "Installing: ${NEED_PKGS[*]}"
  sudo_if_needed apt-get update -qq
  sudo_if_needed apt-get install -y -qq "${NEED_PKGS[@]}"
else
  log "System packages already present."
fi

# ── 2. Backend Python virtualenv ─────────────────────────────────────────────
log "Setting up backend virtualenv..."
cd "$CODE_DIR"
if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
pip install --upgrade pip -q
pip install -q -r requirements.txt
deactivate
log "Backend dependencies installed."

# ── 3. Frontend Node dependencies ────────────────────────────────────────────
log "Installing frontend dependencies..."
cd "$CODE_DIR/frontend"
npm ci --no-audit --no-fund
log "Frontend dependencies installed."

# ── 4. Neo4j (native install) ────────────────────────────────────────────────
if [ ! -x "$NEO4J_HOME/bin/neo4j" ]; then
  log "Downloading Neo4j ${NEO4J_VERSION}..."
  TARBALL="/tmp/neo4j-community-${NEO4J_VERSION}-unix.tar.gz"
  wget -q "https://dist.neo4j.org/neo4j-community-${NEO4J_VERSION}-unix.tar.gz" -O "$TARBALL"
  tar -xzf "$TARBALL" -C /tmp
  rm -rf "$NEO4J_HOME"
  mv "/tmp/neo4j-community-${NEO4J_VERSION}" "$NEO4J_HOME"
  rm -f "$TARBALL"
  # Set the initial password (must happen before first start).
  "$NEO4J_HOME/bin/neo4j-admin" dbms set-initial-password password
  log "Neo4j installed at $NEO4J_HOME"
else
  log "Neo4j already installed at $NEO4J_HOME"
fi

# ── 5. Backend .env ──────────────────────────────────────────────────────────
if [ ! -f "$CODE_DIR/.env" ]; then
  log "Creating code/.env from .env.example..."
  cp "$CODE_DIR/.env.example" "$CODE_DIR/.env"
  # Provide the frontend API URL used by the Vite client.
  echo "VITE_API_URL=http://localhost:8000" >> "$CODE_DIR/.env"
fi

log "Install complete."
