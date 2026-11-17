"""Read-only material inputs under the owner's Doom II and DBP50 WAD stack.

Callers can select the inherited names or the full effective namespace to
derive auxiliary maps from the original layered art.
"""

from __future__ import annotations
import hashlib
from pathlib import Path
import re
import struct

import material_generator as material

IWAD_SHA256 = "31740ef23994b3959800134b41aaf86b04a2847336d328af8c4ae890450630ab"
PWAD_SHA256 = "da722cb243d39e2c3736742df4b69fa9d5c3b4d5e0de53f4a5404dae770e0fd2"
np = material.np


def _lumps(path, expected, magic):
    raw = Path(path).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected, "Content identity differs"
    kind, count, directory = struct.unpack_from("<4sII", raw)
    assert kind == magic and directory + count * 16 <= len(raw)
    result = {}
    for i in range(count):
        offset, size, name = struct.unpack_from("<II8s", raw, directory + i * 16)
        assert offset + size <= len(raw)
        name = name.rstrip(b"\0").decode("ascii").upper()
        result[name] = raw[offset : offset + size]
    return result


def _flat_namespace(path):
    raw = Path(path).read_bytes()
    _, count, directory = struct.unpack_from("<4sII", raw)
    result, active = {}, False
    for i in range(count):
        offset, size, name = struct.unpack_from("<II8s", raw, directory + i * 16)
        name = name.rstrip(b"\0").decode("ascii").upper()
        if re.fullmatch(r"F(?:F|\d+)?_START", name):
            active = True
        elif name in ("F_END", "FF_END"):
            active = False
        elif active and size == 4096:
            result[name] = raw[offset : offset + size]
    return result


class _IndexedOverlay(material.Wad):
    def __init__(self, lookup):
        self.by_name = lookup
        self.patch_cache = {}
        self.palette = np.repeat(np.arange(256, dtype=np.uint8)[:, None], 3, axis=1)

    def lump(self, name):
        return self.by_name[name]

    def selected_textures(self, definition_source, names):
        pnames = definition_source["PNAMES"]
        count = struct.unpack_from("<I", pnames)[0]
        assert 4 + count * 8 <= len(pnames)
        patches = [
            pnames[4 + i * 8 : 12 + i * 8].rstrip(b"\0").decode("ascii").upper()
            for i in range(count)
        ]
        result = {}
        for source_name in ("TEXTURE1", "TEXTURE2"):
            if source_name not in definition_source:
                continue
            data = definition_source[source_name]
            count = struct.unpack_from("<I", data)[0]
            assert 4 + count * 4 <= len(data)
            for i in range(count):
                at = struct.unpack_from("<I", data, 4 + i * 4)[0]
                raw_name, flags, width, height, _, patch_count = struct.unpack_from(
                    "<8sIhhIh", data, at
                )
                name = raw_name.rstrip(b"\0").decode("ascii").upper()
                if names is not None and name not in names:
                    continue
                assert 0 < width <= 4096 and 0 < height <= 4096 and patch_count >= 0
                pixels = np.zeros((height, width, 4), dtype=np.uint8)
                patch_names = []
                for j in range(patch_count):
                    ox, oy, pi, _, _ = struct.unpack_from(
                        "<hhhhh", data, at + 22 + j * 10
                    )
                    pname = patches[pi]
                    patch_names.append(pname)
                    patch = self.patch(pname)
                    ph, pw = patch.shape[:2]
                    x0, y0, x1, y1 = (
                        max(0, ox),
                        max(0, oy),
                        min(width, ox + pw),
                        min(height, oy + ph),
                    )
                    if x1 > x0 and y1 > y0:
                        src = patch[y0 - oy : y1 - oy, x0 - ox : x1 - ox]
                        dst = pixels[y0:y1, x0:x1]
                        mask = src[:, :, 3] != 0
                        dst[mask] = src[mask]
                result[name] = dict(
                    name=name,
                    kind="wall",
                    pixels=pixels,
                    source_lump=source_name,
                    source_index=i,
                    patches=patch_names,
                    placeholder=(i == 0 and name == "AASHITTY"),
                )
        return result


def _rgba(indexed, palette):
    result = np.empty_like(indexed)
    result[:, :, :3] = palette[indexed[:, :, 0]]
    result[:, :, 3] = indexed[:, :, 3]
    return result


def effective_rows(iwad, pwad, entries, include_custom=False):
    """Return effective RGBA rows for inherited or all world material names.

    Each row adds rgba_changed and pattern_changed booleans. They compare the
    actual replacement/palette result against baseline albedo, and raw indexed
    pattern/alpha independently. Output pixels are current DBP50 artwork, not
    substitute albedos to load into the game.
    """
    original = _lumps(iwad, IWAD_SHA256, b"IWAD")
    replacement = _lumps(pwad, PWAD_SHA256, b"PWAD")
    effective_flats = _flat_namespace(iwad) | _flat_namespace(pwad)
    return reconstruct_rows(original, replacement, effective_flats, entries, include_custom)


def texture_overrides(original, replacement):
    """Use the replacement texture tables with their own or inherited PNAMES."""
    tables = {
        key: replacement[key] for key in ("TEXTURE1", "TEXTURE2") if key in replacement
    }
    if tables:
        tables["PNAMES"] = replacement.get("PNAMES", original["PNAMES"])
    return tables


def reconstruct_rows(original, replacement, effective_flats, entries, include_custom=False):
    names = {e["name"] for e in entries if e["kind"] == "wall"}
    baseline = _IndexedOverlay(original).selected_textures(original, names)
    lookup = original | replacement
    decoder = _IndexedOverlay(lookup)
    current = decoder.selected_textures(original, names)
    tables = texture_overrides(original, replacement)
    if tables:
        current.update(decoder.selected_textures(tables, None if include_custom else names))
    before_palette = np.frombuffer(original["PLAYPAL"][:768], dtype=np.uint8).reshape(
        256, 3
    )
    after_palette = np.frombuffer(lookup["PLAYPAL"][:768], dtype=np.uint8).reshape(
        256, 3
    )
    custom_keys = set()
    if include_custom:
        from dbp50_structural_relief import family_of

        custom_keys = {("wall", name) for name in current} | {("flat", name) for name in effective_flats}
        custom_keys.difference_update((row["kind"], row["name"]) for row in entries)
        next_id = max((entry["id"] for entry in entries), default=0) + 1
        entries = [*entries, *(
            dict(kind=kind, name=name, id=next_id + ordinal,
                 family=family_of(name, kind, material.family_of(name, kind)),
                 source_index=current[name]["source_index"] if kind == "wall" else ordinal)
            for ordinal, (kind, name) in enumerate(sorted(custom_keys))
        )]
    rows = []
    for entry in entries:
        name, kind = entry["name"], entry["kind"]
        custom = (kind, name) in custom_keys
        before = None
        if kind == "wall":
            if not custom:
                before = baseline[name]["pixels"]
            item = current[name].copy()
            after = item["pixels"]
        else:
            assert len(effective_flats[name]) == 4096
            before = np.empty((64, 64, 4), dtype=np.uint8)
            after = np.empty_like(before)
            after[:, :, :3] = np.frombuffer(
                effective_flats[name], dtype=np.uint8
            ).reshape(64, 64, 1)
            after[:, :, 3] = 255
            if custom:
                before = None
            else:
                assert len(original[name]) == 4096
                before[:, :, :3] = np.frombuffer(original[name], dtype=np.uint8).reshape(64, 64, 1)
                before[:, :, 3] = 255
            item = dict(
                name=name,
                kind=kind,
                source_lump=name,
                source_index=entry["source_index"],
                patches=[],
                placeholder=False,
            )
        after_rgba = _rgba(after, after_palette)
        before_rgba = None if before is None else _rgba(before, before_palette)
        item.update(
            pixels=after_rgba,
            family=entry["family"],
            id=entry["id"],
            custom=custom,
            rgba_changed=(
                before_rgba is None or before_rgba.shape != after_rgba.shape
                or not np.array_equal(before_rgba, after_rgba)
            ),
            pattern_changed=(
                before is None or before.shape != after.shape or not np.array_equal(before, after)
            ),
        )
        rows.append(item)
    return rows
