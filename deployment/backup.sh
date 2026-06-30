#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
require_runtime

cd "${PROJECT_ROOT}"
exec "${PYTHON}" scripts/backup_db.py
