#!/usr/bin/env bash
# Starts the website and opens it in your browser. Ctrl+C to stop.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then echo "Not installed yet. Run ./install.sh first." >&2; exit 1; fi
exec .venv/bin/python -m tryon run "$@"
