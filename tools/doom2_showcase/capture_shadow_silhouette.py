"""Trace independent flashlight rays through the stock sprite onto SHPDEMO's map surfaces."""

import struct

import numpy as np
from PIL import Image, ImageFilter

from capture_relief import require
from material_generator import Wad
from shadow_puppets import room_geometry


def reference_room(sloped):
    room = room_geometry()
    if sloped:
        # Bring the landing within reach of a close, elevated lamp. The first
        # tread rises from z=8 at y=32 to z=16 at y=48.
        boundaries = {132: 32, 164: 48, 196: 72, 232: 96}
        for vertex in room.rows["vertex"]:
            vertex["y"] = boundaries.get(vertex["y"], vertex["y"])
        normal = np.hypot(1, .5)
        room.rows["sector"][1].update(floorplane_a=0, floorplane_b=-.5 / normal,
                                      floorplane_c=1 / normal, floorplane_d=8 / normal)
    return room


def camera_rays(camera, size):
    width, height = size
    pixels_y, pixels_x = np.indices((height, width))
    focal = min(width * .5, height * (2 / 3)) / np.tan(np.deg2rad(camera["fov"] / 2))
    right = (pixels_x + .5 - width / 2) / focal
    up = (height / 2 - pixels_y - .5) / focal
    yaw = np.deg2rad(camera["angles"][0])
    pitch, roll = np.deg2rad(camera["hardware_angles"][1:])
    require(abs(roll) < 1e-6, "Capture camera roll must be zero")
    horizontal = np.cos(pitch) + up * np.sin(pitch)
    return (horizontal * np.cos(yaw) + right * np.sin(yaw),
            horizontal * np.sin(yaw) - right * np.cos(yaw),
            (up * np.cos(pitch) - np.sin(pitch)) / 1.2)


def receiver_hits(camera, size, sloped):
    """Intersect perspective rays with the same floor planes and vertical sides as the native map."""
    eye = camera["position"]
    dx, dy, dz = camera_rays(camera, size)
    distance = np.full(dx.shape, np.inf)
    surface = np.full(dx.shape, "", dtype="<U5")

    def submit(t, inside, kind):
        hit = inside & (t > 0) & (t < distance)
        np.copyto(distance, t, where=hit)
        surface[hit] = kind

    def ray_t(numerator, denominator):
        return np.divide(numerator, denominator, out=np.zeros(dx.shape), where=np.abs(denominator) > 1e-10)

    rows = reference_room(sloped).rows
    bounds = [[] for _ in rows["sector"]]
    planes = [(s.get("floorplane_a", 0), s.get("floorplane_b", 0), s.get("floorplane_c", 1),
               s.get("floorplane_d", -s["heightfloor"])) for s in rows["sector"]]
    for line in rows["linedef"]:
        a, b = [rows["vertex"][line[name]] for name in ("v1", "v2")]
        sectors = [rows["sidedef"][line[side]]["sector"] for side in ("sidefront", "sideback") if side in line]
        for index in sectors:
            bounds[index].extend([a, b])
        span_x, span_y = b["x"] - a["x"], b["y"] - a["y"]
        t = ray_t((a["x"] - eye[0]) * span_y - (a["y"] - eye[1]) * span_x, dx * span_y - dy * span_x)
        x, y, z = eye[0] + t * dx, eye[1] + t * dy, eye[2] + t * dz
        along = ((x - a["x"]) * span_x + (y - a["y"]) * span_y) / (span_x ** 2 + span_y ** 2)
        heights = [-(pa * x + pb * y + pd) / pc for pa, pb, pc, pd in (planes[i] for i in sectors)]
        if len(sectors) == 2:
            low, high = np.minimum(*heights), np.maximum(*heights)
        else:
            low, high = heights[0], rows["sector"][sectors[0]]["heightceiling"]
        submit(t, (along >= 0) & (along <= 1) & (z >= low) & (z <= high),
               "riser" if len(sectors) == 2 else "wall")
    for (a, b, c, d), vertices in zip(planes, bounds):
        t = ray_t(-(a * eye[0] + b * eye[1] + c * eye[2] + d), a * dx + b * dy + c * dz)
        x, y = eye[0] + t * dx, eye[1] + t * dy
        xs, ys = [v["x"] for v in vertices], [v["y"] for v in vertices]
        submit(t, (x >= min(xs)) & (x <= max(xs)) & (y >= min(ys)) & (y <= max(ys)),
               "slope" if a or b else "floor")
    distance[~np.isfinite(distance)] = 0
    return (eye[0] + distance * dx, eye[1] + distance * dy, eye[2] + distance * dz), surface


def sprite_hit(origin, receiver, actor, patch, forward):
    x, y, z = receiver
    alpha, left, top, mirrored = patch
    nx, ny = forward
    denominator = (x - origin[0]) * nx + (y - origin[1]) * ny
    t = np.divide((actor[0] - origin[0]) * nx + (actor[1] - origin[1]) * ny, denominator,
                  out=np.zeros(x.shape), where=np.abs(denominator) > 1e-10)
    offset = (origin[0] + t * (x - origin[0]) - actor[0]) * ny - (origin[1] + t * (y - origin[1]) - actor[1]) * nx
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

    def patch(name, mirror):
        _, _, left, top = struct.unpack_from("<hhhh", wad.lump(name))
        return wad.patch(name)[:, :, 3] >= 128, left, top, mirror

    sloped = state["sloped_receiver"]
    visible_patch = patch(texture, state["source_mirrored"])
    light_texture = state["light_sprite"]
    light_patch = patch(light_texture, state["light_sprite_mirrored"])
    eye, lamp, actor = state["camera"]["position"], state["light_origin"], state["walker_pose"]
    receiver, surface = receiver_hits(state["camera"], off.size, sloped)
    azimuth = np.deg2rad(state["camera"]["angles"][0])
    camera_forward = (np.cos(azimuth), np.sin(azimuth))
    light_forward = np.asarray(actor[:2], dtype=float) - lamp[:2]
    light_forward /= np.linalg.norm(light_forward)
    expected = sprite_hit(lamp, receiver, actor, light_patch, light_forward)
    actor_mask = sprite_hit(eye, receiver, actor, visible_patch, camera_forward)
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
    if sloped:
        previous = sprite_hit(lamp, receiver, actor, visible_patch, camera_forward)
        # Only count samples that are unambiguous in both candidate silhouettes.
        different = usable & ((covered & ~filter_mask(previous, ImageFilter.MaxFilter(5))) |
                              (clear & filter_mask(previous, ImageFilter.MinFilter(5))))
        require(np.sum(different) >= 150, "The raised light must distinguish light and camera perspectives")
        # Each witness straddles a tread/riser or floor/riser seam inside the shadow.
        horizontal = usable & covered & np.isin(surface, ["floor", "slope"])
        seam = usable & covered & (surface == "riser") & filter_mask(horizontal, ImageFilter.MaxFilter(3))
        require(np.sum(seam) >= 4, "The projected silhouette must cross a visible stair edge")

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
        if sloped:
            total = int(np.sum(different))
            correct = int(np.sum((blocked == expected) & different))
            require(correct >= .95 * total,
                    f"{mode} matched the raised light's perspective on {correct}/{total} distinguishing pixels")
            blocked_seam = int(np.sum(blocked & seam))
            require(blocked_seam == np.sum(seam), f"{mode} broke the shadow at a tread/riser seam")
            measured["perspective"] = {"distinguishing_pixels": total,
                                       "light_view_matches": correct, "blocked_stair_edge_pixels": blocked_seam}
        for kind in (("floor", "slope", "riser", "wall") if sloped else ("floor", "riser", "wall")):
            test = usable & (surface == kind)
            inside, outside = test & covered, test & clear
            hits, misses = int(np.sum(blocked & inside)), int(np.sum(~blocked & inside))
            false_hits = int(np.sum(blocked & outside))
            measured[kind] = {"opaque_samples": hits + misses, "missed": misses,
                              "transparent_samples": int(np.sum(outside)), "false_hits": false_hits}
            require(hits >= 12 and hits >= 0.90 * (hits + misses),
                    f"{mode} {kind} missed opaque {light_texture} projection: {measured[kind]}")
            require(false_hits <= 0.10 * hits,
                    f"{mode} {kind} blocked rays through transparent {light_texture} texels: {measured[kind]}")
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
