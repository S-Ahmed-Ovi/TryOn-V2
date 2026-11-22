"""Start the website without installing the project itself:

    pip install -r requirements.txt
    python run.py                 # start the website
    python run.py build           # rebuild the catalog     (also: doctor, analyze photo.jpg)
    python run.py --port 9000     # any `tryon run` option works
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from tryon.cli import main  # noqa: E402

if __name__ == "__main__":
    main(sys.argv[1:])
