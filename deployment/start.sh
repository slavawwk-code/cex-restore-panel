#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
require_runtime

if command -v systemctl >/dev/null 2>&1 \
  && systemctl is-active --quiet "${SERVICE_NAME}"; then
  echo "${SERVICE_NAME} is already active; refusing to start a second bot." >&2
  exit 1
fi

cd "${PROJECT_ROOT}"
"${PYTHON}" scripts/smoke_test.py
exec "${PYTHON}" main.py
