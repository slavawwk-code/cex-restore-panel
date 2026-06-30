#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
require_runtime

cd "${PROJECT_ROOT}"
"${PYTHON}" scripts/smoke_test.py
run_systemctl restart "${SERVICE_NAME}"
run_systemctl --no-pager --full status "${SERVICE_NAME}"
