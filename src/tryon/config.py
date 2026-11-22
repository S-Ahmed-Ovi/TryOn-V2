"""All settings in one place. Values come from environment variables or a `.env` file in the project root."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PACKAGE_DIR / "assets"
WEB_DIR = PACKAGE_DIR / "web"
RESOURCES_DIR = PACKAGE_DIR / "resources"
FACE_MODEL_PATH = ASSETS_DIR / "models" / "face_landmarker.task"


def _find_home() -> Path:
    """Project root: TRYON_HOME, else the source checkout, else the current folder."""
    if os.environ.get("TRYON_HOME"):
        return Path(os.environ["TRYON_HOME"]).expanduser().resolve()
    checkout = PACKAGE_DIR.parent.parent
    if (checkout / "data").is_dir():
        return checkout
    return Path.cwd()


def _load_dotenv(home: Path) -> None:
    """Tiny .env reader (KEY=VALUE per line). Real environment variables always win."""
    env_file = home / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


@dataclass(frozen=True)
class Settings:
    home: Path
    data_dir: Path
    models_dir: Path            # the 3D models (.glb) and manifest.json: the catalogue is built from these
    catalog_dir: Path           # generated 2D cut-outs, thumbnails and catalog.json
    host: str
    port: int
    site_name: str
    max_upload_bytes: int
    max_live_sessions: int = 4          # people using the live 3D camera at the same time (each one is a CPU-heavy video stream)

    @property
    def catalog_json(self) -> Path:
        return self.catalog_dir / "catalog.json"

    @property
    def manifest_json(self) -> Path:
        return self.models_dir / "manifest.json"


def load_settings() -> Settings:
    home = _find_home()
    _load_dotenv(home)
    data_dir = home / "data"
    return Settings(
        home=home,
        data_dir=data_dir,
        models_dir=data_dir / "models3d",
        catalog_dir=data_dir / "catalog",
        host=os.environ.get("TRYON_HOST", "127.0.0.1"),
        port=int(os.environ.get("TRYON_PORT", "8000")),
        site_name=os.environ.get("TRYON_SITE_NAME", "TryOn"),
        max_upload_bytes=int(float(os.environ.get("TRYON_MAX_UPLOAD_MB", "12")) * 1024 * 1024),
        max_live_sessions=max(1, int(os.environ.get("TRYON_MAX_LIVE", "4"))),
    )
