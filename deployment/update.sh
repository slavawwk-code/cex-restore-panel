#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
require_runtime

if command -v systemctl >/dev/null 2>&1 \
  && systemctl is-active --quiet "${SERVICE_NAME}"; then
  echo "Stop ${SERVICE_NAME} before updating: sudo ./deployment/stop.sh" >&2
  exit 1
fi

cd "${PROJECT_ROOT}"
"${PROJECT_ROOT}/deployment/backup.sh"
git pull --ff-only
"${PYTHON}" -m pip install -r requirements.txt
"${PYTHON}" -m pip check
"${PYTHON}" scripts/smoke_test.py

echo "Update verified. Run deployment/restart.sh to activate it."
