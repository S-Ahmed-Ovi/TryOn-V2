# Shortcuts for macOS / Linux (Windows: use install.bat / run.bat).
.PHONY: install run build models doctor test clean

install:           ## create .venv and install everything
	./install.sh

run:               ## start the website
	./run.sh

build:             ## re-render the 2D pictures from the 3D models (needs Node.js 18+)
	.venv/bin/python -m tryon build

models:            ## re-make the 24 built-in 3D frames, then re-render the 2D pictures
	.venv/bin/python -m tryon models3d generate
	.venv/bin/python -m tryon build

doctor:            ## check the installation
	.venv/bin/python -m tryon doctor

test:              ## run the test-suite
	.venv/bin/python -m pip install -q -e ".[dev]"
	.venv/bin/python -m pytest

clean:
	rm -rf .pytest_cache build dist src/*.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
