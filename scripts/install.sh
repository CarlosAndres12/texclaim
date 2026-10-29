#!/usr/bin/env bash
# make install-global calls this
set -euo pipefail
command -v pipx >/dev/null || { echo "Install pipx first: https://pipx.pypa.io"; exit 1; }
cd "$(dirname "$0")/.."
pipx install --editable . --force --pip-args="-c constraints.txt"
pipx ensurepath
