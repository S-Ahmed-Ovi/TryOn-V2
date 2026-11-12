"""SHA-256 hashing and in-run duplicate tracking."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class HashIndex:
    by_hash: dict[str, str] = field(default_factory=dict)   # sha256 -> first local_path
    by_url: dict[str, dict] = field(default_factory=dict)   # url -> stored result info

    def register(self, url: str, sha: str, local_path: str, info: dict) -> str | None:
        """Remember a stored image. Returns the path of an earlier identical file, if any."""
        self.by_url.setdefault(url, {**info, "local_path": local_path, "sha256": sha})
        first = self.by_hash.setdefault(sha, local_path)
        return first if first != local_path else None
