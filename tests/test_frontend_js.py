"""Runs the JavaScript tests (the CPU 3D renderer, placement and pose smoothing) when Node.js is installed."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_javascript_tests_pass():
    proc = subprocess.run(["node", "--test", "tests/js/tryon3d.test.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-1500:]
