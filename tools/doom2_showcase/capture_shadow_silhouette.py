"""Trace independent flashlight rays through the stock sprite onto SHPDEMO's map surfaces."""

import struct

import numpy as np
from PIL import Image, ImageFilter

from capture_relief import require
from material_generator import Wad
from shadow_puppets import room_geometry


def receiver_hits(eye, size):
    """Intersect camera rays with the comparison room's floors, stair risers and end wall."""
    width, height = size
    pixels_y, pixels_x = np.indices((height, width))
    # The fixture faces due north, at zero pitch, 90-degree classic 4:3 horizontal FOV.
    focal = min(width * 0.5, height * (2 / 3))
    dx = (pixels_x + 0.5 - width / 2) / focal
    dz = (height / 2 - pixels_y - 0.5) / (focal * 1.2)  # stock Doom pixel stretch
    distance = np.full(dx.shape, np.inf)
    surface = np.full(dx.shape, "", dtype="<U5")

    def submit(t, inside, kind):
        hit = inside & (t > 0) & (t < distance)
        np.copyto(distance, t, where=hit)
        surface[hit] = kind

    rows = room_geometry().rows
    bounds = [[] for _ in rows["sector"]]
    for line in rows["linedef"]:
        a, b = [rows["vertex"][line[name]] for name in ("v1", "v2")]
        sectors = [rows["sidedef"][line[side]]["sector"] for side in ("sidefront", "sideback") if side in line]
        for index in sectors:
            bounds[index].extend([a, b])
        if a["y"] != b["y"] or a["y"] <= eye[1]:
            continue
        floors = [rows["sector"][index]["heightfloor"] for index in sectors]
        low, high = min(floors), max(floors) if len(sectors) == 2 else rows["sector"][sectors[0]]["heightceiling"]
        t = a["y"] - eye[1]
        x, z = eye[0] + t * dx, eye[2] + t * dz
        xmin, xmax = sorted((a["x"], b["x"]))
        submit(t, (x >= xmin) & (x <= xmax) & (z >= low) & (z <= high),
               "riser" if len(sectors) == 2 else "wall")
    for sector, vertices in zip(rows["sector"], bounds):
        t = np.divide(sector["heightfloor"] - eye[2], dz, out=np.full(dz.shape, np.inf), where=dz != 0)
        x, y = eye[0] + t * dx, eye[1] + t
        xs, ys = [v["x"] for v in vertices], [v["y"] for v in vertices]
        submit(t, (x >= min(xs)) & (x <= max(xs)) & (y >= min(ys)) & (y <= max(ys)), "floor")
    # Points outside those three receiver classes are excluded from the comparison.
    distance[~np.isfinite(distance)] = 0
    return (eye[0] + distance * dx, eye[1] + distance, eye[2] + distance * dz), surface


def sprite_hit(origin, receiver, actor, alpha, left, top, mirrored):
    x, y, z = receiver
    t = np.divide(actor[1] - origin[1], y - origin[1], out=np.zeros(y.shape), where=y != origin[1])
    offset = origin[0] + (x - origin[0]) * t - actor[0]
    u = np.floor(left - offset if mirrored else left + offset).astype(int)
    v = np.floor(top + actor[2] - origin[2] - (z - origin[2]) * t).astype(int)
    h, w = alpha.shape
    in_front = (t > 0) & (t < 1) & (u >= 0) & (u < w) & (v >= 0) & (v < h)
    return in_front & alpha[v.clip(0, h - 1), u.clip(0, w - 1)]


def filter_mask(mask, kernel):
    return np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(kernel)) != 0


def verify_projection(iwad, captures, ambient, folder):
    off, state = captures[0]
    wad = Wad(iwad)
    texture = state["source_sprite"]
    _, _, left, top = struct.unpack_from("<hhhh", wad.lump(texture))
    alpha = wad.patch(texture)[:, :, 3] >= 128
    eye, lamp, actor = state["camera"]["position"], state["light_origin"], state["walker_pose"]
    receiver, surface = receiver_hits(eye, off.size)
    expected = sprite_hit(lamp, receiver, actor, alpha, left, top, state["source_mirrored"])
    actor_mask = sprite_hit(eye, receiver, actor, alpha, left, top, state["source_mirrored"])
    # Keep an explicit transition band for camera rasterization, MSAA and light-space filtering.
    covered = filter_mask(expected, ImageFilter.MinFilter(5))
    clear = ~filter_mask(expected, ImageFilter.MaxFilter(5))
    visible = ~filter_mask(actor_mask, ImageFilter.MaxFilter(7))
    foreground = filter_mask(actor_mask, ImageFilter.MinFilter(7))
    baseline = np.asarray(off, dtype=np.int16)
    direct = np.max(baseline - np.asarray(ambient, dtype=np.int16), axis=2)
    usable = (direct >= 12) & visible & (surface != "")
    usable[:round(off.height * 0.1)] = False
    Image.fromarray(np.uint8(expected & visible) * 255).save(folder / "expected-silhouette.png")

    result = {}
    witness = {"covered": usable & covered, "clear": usable & clear}
    for mode, (shadow, _) in zip(("stencil", "depth"), captures[1:]):
        delta = baseline - np.asarray(shadow, dtype=np.int16)
        blocked = np.max(delta, axis=2) >= direct * 0.5
        witness[mode] = blocked
        require(np.any(foreground), f"Missing foreground sprite in {mode} reference")
        foreground_error = int(np.max(np.abs(delta[foreground])))
        require(foreground_error <= 2, f"{mode} changed the foreground {texture} by {foreground_error} RGB levels")
        measured = {"foreground": {"samples": int(np.sum(foreground)), "max_channel_delta": foreground_error}}
        for kind in ("floor", "riser", "wall"):
            test = usable & (surface == kind)
            inside, outside = test & covered, test & clear
            hits, misses = int(np.sum(blocked & inside)), int(np.sum(~blocked & inside))
            false_hits = int(np.sum(blocked & outside))
            measured[kind] = {"opaque_samples": hits + misses, "missed": misses,
                              "transparent_samples": int(np.sum(outside)), "false_hits": false_hits}
            require(hits >= 12 and hits >= 0.90 * (hits + misses),
                    f"{mode} {kind} missed opaque {texture} projection: {measured[kind]}")
            require(false_hits <= 0.10 * hits,
                    f"{mode} {kind} blocked rays through transparent {texture} texels: {measured[kind]}")
        result[mode] = measured
    return result, witness


def verify_frame_change(first, second):
    # Restrict to lit map pixels that switch cleanly between opaque and clear in the source art.
    gained = first["clear"] & second["covered"]
    lost = first["covered"] & second["clear"]
    result = {}
    for mode in ("stencil", "depth"):
        counts = {}
        for name, expected, observed in (
                ("gained", gained, ~first[mode] & second[mode]),
                ("lost", lost, first[mode] & ~second[mode])):
            total, matching = int(np.sum(expected)), int(np.sum(expected & observed))
            require(total >= 60 and matching >= 0.9 * total,
                    f"{mode} failed fixed-position TROOA1 to TROOG1 shadow change: {name} {matching}/{total}")
            counts[name] = {"expected": total, "observed": matching}
        result[mode] = counts
    return result
