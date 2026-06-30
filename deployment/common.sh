#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-${PROJECT_ROOT}/.venv}"
PYTHON="${VENV_DIR}/bin/python"
SERVICE_NAME="${SERVICE_NAME:-cex-restore.service}"

require_runtime() {
  if [[ ! -x "${PYTHON}" ]]; then
    echo "Virtual environment not found: ${VENV_DIR}" >&2
    echo "Run deployment/install.sh first." >&2
    exit 1
  fi
  if [[ ! -f "${PROJECT_ROOT}/.env" ]]; then
    echo "Missing ${PROJECT_ROOT}/.env" >&2
    echo "Copy .env.example to .env and configure it." >&2
    exit 1
  fi
}

run_systemctl() {
  if [[ "$(id -u)" -eq 0 ]]; then
    systemctl "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo systemctl "$@"
  else
    echo "Root privileges are required to manage ${SERVICE_NAME}." >&2
    exit 1
  fi
}
