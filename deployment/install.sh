#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-${PROJECT_ROOT}/.venv}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "System Python was not found (${PYTHON_BIN})." >&2
  echo "Install Python 3.12 or newer; see DEPLOY.md." >&2
  exit 1
fi

if ! "${PYTHON_BIN}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "${PYTHON_BIN} must be Python 3.12 or newer." >&2
  exit 1
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/python" -m pip install -r "${PROJECT_ROOT}/requirements.txt"
"${VENV_DIR}/bin/python" -m pip check

if [[ ! -f "${PROJECT_ROOT}/.env" ]]; then
  cp "${PROJECT_ROOT}/.env.example" "${PROJECT_ROOT}/.env"
  chmod 600 "${PROJECT_ROOT}/.env"
  echo "Created .env from .env.example. Configure it before startup."
fi

cd "${PROJECT_ROOT}"
"${VENV_DIR}/bin/python" -c \
  'from app.config import ensure_runtime_directories, load_settings; settings = load_settings(False); ensure_runtime_directories(settings)'

echo "Installation complete. Configure .env, then run deployment/start.sh."
