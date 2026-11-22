#!/usr/bin/env bash
# One-time setup (macOS / Linux): creates .venv and installs everything. Needs Python 3.10 - 3.13.
set -e
cd "$(dirname "$0")"

PY=""
for c in python3.12 python3.11 python3.10 python3.13 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,14) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 - 3.13 was not found. Install Python 3.12 (https://www.python.org/downloads/) and run ./install.sh again." >&2
  exit 1
fi

echo "Using $($PY --version)"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip >/dev/null
echo "Installing packages (first time takes a few minutes)..."
.venv/bin/python -m pip install -e .
echo
.venv/bin/python -m tryon doctor
echo
echo "Done. Start the website with: ./run.sh"
