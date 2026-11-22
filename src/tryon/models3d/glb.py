"""Minimal glTF 2.0 binary (.glb) writer and reader. numpy only; no 3D library needed."""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

_FLOAT, _USHORT, _UINT = 5126, 5123, 5125
_ARRAY_BUFFER, _ELEMENT_ARRAY_BUFFER = 34962, 34963


class GlbError(ValueError):
    pass


def _pad(data: bytearray, fill: int = 0) -> None:
    while len(data) % 4:
        data.append(fill)


def write_glb(path: str | Path, parts: list[dict], materials: list[dict], extras: dict | None = None) -> int:
    """Write meshes to one .glb. Each part: name, v (n,3), n (n,3), f (m,3), material (index), optional c (n,4) colours.

    Returns the file size in bytes.
    """
    blob = bytearray()
    views, accessors, meshes, nodes = [], [], [], []

    def add(arr: np.ndarray, comp: int, kind: str, target: int, bounds: bool = False) -> int:
        _pad(blob)
        raw = np.ascontiguousarray(arr).tobytes()
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(raw), "target": target})
        blob.extend(raw)
        acc = {"bufferView": len(views) - 1, "componentType": comp, "count": int(arr.shape[0]), "type": kind}
        if bounds:
            acc["min"] = [float(x) for x in arr.min(0)]
            acc["max"] = [float(x) for x in arr.max(0)]
        accessors.append(acc)
        return len(accessors) - 1

    for part in parts:
        v = np.asarray(part["v"], np.float32)
        n = np.asarray(part["n"], np.float32)
        f = np.asarray(part["f"], np.int64)
        attrs = {"POSITION": add(v, _FLOAT, "VEC3", _ARRAY_BUFFER, bounds=True), "NORMAL": add(n, _FLOAT, "VEC3", _ARRAY_BUFFER)}
        if part.get("c") is not None:
            attrs["COLOR_0"] = add(np.asarray(part["c"], np.float32), _FLOAT, "VEC4", _ARRAY_BUFFER)
        if len(v) < 65536:
            idx = add(f.reshape(-1).astype(np.uint16), _USHORT, "SCALAR", _ELEMENT_ARRAY_BUFFER)
        else:
            idx = add(f.reshape(-1).astype(np.uint32), _UINT, "SCALAR", _ELEMENT_ARRAY_BUFFER)
        meshes.append({"name": part["name"], "primitives": [{"attributes": attrs, "indices": idx, "material": part["material"], "mode": 4}]})
        nodes.append({"name": part["name"], "mesh": len(meshes) - 1})

    root = {"name": "Sunglasses", "children": list(range(1, len(nodes) + 1))}
    doc = {
        "asset": {"version": "2.0", "generator": "TryOn model generator", "extras": extras or {}},
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [root] + nodes, "meshes": meshes, "materials": materials,
        "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(blob)}],
    }
    return pack_glb(path, doc, bytes(blob))


def pack_glb(path: str | Path, doc: dict, binary: bytes) -> int:
    """Write a JSON document and a binary chunk as a .glb. Returns the file size in bytes."""
    js = bytearray(json.dumps(doc, separators=(",", ":")).encode("utf-8"))
    _pad(js, 0x20)
    blob = bytearray(binary)
    _pad(blob)
    total = 12 + 8 + len(js) + 8 + len(blob)
    out = bytearray(struct.pack("<III", 0x46546C67, 2, total))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js
    out += struct.pack("<II", len(blob), 0x004E4942) + blob
    Path(path).write_bytes(bytes(out))
    return total


def read_glb(path: str | Path) -> tuple[dict, bytes]:
    """The JSON document and the binary chunk of a .glb."""
    data = Path(path).read_bytes()
    if len(data) < 20 or struct.unpack_from("<I", data, 0)[0] != 0x46546C67:
        raise GlbError("not a .glb file")
    pos, doc, binary = 12, None, b""
    while pos + 8 <= len(data):
        length, kind = struct.unpack_from("<II", data, pos)
        chunk = data[pos + 8: pos + 8 + length]
        if kind == 0x4E4F534A:
            doc = json.loads(chunk.decode("utf-8"))
        elif kind == 0x004E4942:
            binary = chunk
        pos += 8 + length
    if doc is None:
        raise GlbError("no JSON chunk")
    return doc, binary


_COMPONENTS = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_accessor(doc: dict, binary: bytes, index: int) -> np.ndarray:
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    code, size = _COMPONENTS[acc["componentType"]]
    width = _WIDTH[acc["type"]]
    stride = view.get("byteStride") or size * width
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    if stride == size * width:
        arr = np.frombuffer(binary, dtype=np.dtype(code).newbyteorder("<"), count=acc["count"] * width, offset=start)
    else:
        rows = [np.frombuffer(binary, dtype=np.dtype(code).newbyteorder("<"), count=width, offset=start + i * stride) for i in range(acc["count"])]
        arr = np.concatenate(rows) if rows else np.zeros(0)
    return arr.reshape(acc["count"], width) if width > 1 else arr


def model_bounds(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Axis-aligned bounds (min, max) of every mesh in a .glb, ignoring node transforms (the generator writes none)."""
    doc, binary = read_glb(path)
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for mesh in doc["meshes"]:
        for prim in mesh["primitives"]:
            pos = read_accessor(doc, binary, prim["attributes"]["POSITION"])
            lo, hi = np.minimum(lo, pos.min(0)), np.maximum(hi, pos.max(0))
    return lo, hi
