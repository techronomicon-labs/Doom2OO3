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


def lobe_regions(receiver, lamp, yaws):
    """Isolate the outside spotlight and the areas lit by multiple spots in the horizontal fixture."""
    x, y, z = (coord - start for coord, start in zip(receiver, lamp))
    length = np.sqrt(x * x + y * y + z * z)
    angles = np.deg2rad(yaws)[:, None, None]
    along = x * np.cos(angles) + y * np.sin(angles)
    # Leave a quarter-degree margin on both sides of the 14-degree outer cones.
    inside = along > length * np.cos(np.deg2rad(13.75))
    near = along > length * np.cos(np.deg2rad(14.25))
    return {"outer_only": inside[0] & ~np.any(near[1:], axis=0),
            "overlap": np.sum(inside, axis=0) >= 2}


def aperture_coverage(lamp, angles, radius, receiver, actor, patch, forward):
    """Trace the original artwork from a uniform disk at the flashlight mount."""
    yaw, pitch = np.deg2rad(angles)
    right = np.array([np.sin(yaw), -np.cos(yaw), 0.0])
    up = np.array([np.sin(pitch) * np.cos(yaw), np.sin(pitch) * np.sin(yaw), np.cos(pitch)])
    coverage = np.zeros(receiver[0].shape, dtype=float)
    samples = 32
    for i in range(samples):
        theta = i * np.pi * (3 - np.sqrt(5))
        offset = np.sqrt((i + .5) / samples) * radius * (np.cos(theta) * right + np.sin(theta) * up)
        coverage += sprite_hit(lamp + offset, receiver, actor, patch, forward)
    return coverage / samples


def verify_penumbra(baseline, fill, hard, stencil, soft, usable, expected, coverage, receiver, actor, lamp,
                    forward, softness):
    """Measure partial lighting against native full-light and ambient-only controls."""
    direct = np.max(baseline - fill, axis=2)

    def blocked_fraction(image):
        return np.max(baseline - np.asarray(image, dtype=np.int16), axis=2) / np.maximum(direct, 1)

    point = blocked_fraction(hard)
    stencil = blocked_fraction(stencil)
    filtered = blocked_fraction(soft)
    # Measure only pixels for which both independent hard backends agree with the source alpha.
    solid = (point >= .9) & (stencil >= .9) & expected
    lit = (point <= .1) & (stencil <= .1) & ~expected
    valid = usable & (direct >= 24) & (solid | lit)
    # Confirm the zero-radius capture agrees with the hard stencil on unambiguous outline samples.
    edge = filter_mask(expected, ImageFilter.MaxFilter(3)) & ~filter_mask(expected, ImageFilter.MinFilter(3))
    hard_area = usable & (direct >= 24) & ~edge & (((stencil >= .9) & expected) | ((stencil <= .1) & ~expected))
    hard_matches = int(np.sum(hard_area & (solid | lit)))
    hard_total = int(np.sum(hard_area))
    require(hard_total >= 100 and hard_matches >= .99 * hard_total, "Zero-softness Depth lost the hard silhouette")
    dx, dy, dz = (coord - origin for coord, origin in zip(receiver, lamp))
    axial = dx * forward[0] + dy * forward[1]
    caster_depth = np.dot(np.asarray(actor[:2]) - lamp[:2], forward)
    t = np.divide(caster_depth, axial, out=np.zeros_like(axial), where=axial > 1e-6)
    gap = (1.0 - t) * np.sqrt(dx * dx + dy * dy + dz * dz)
    valid &= (t > 0) & (t <= 1)
    # Sample the detached silhouette on both sides of its hard outline. Each witness
    # sees a mixture of transparent and opaque texels from points on the real aperture.
    mixed = valid & (gap >= 35) & (coverage >= .16) & (coverage <= .84)
    partial = (filtered > .08) & (filtered < .92)
    result = {"hard_depth": {"witnesses": hard_total, "matches": hard_matches}}
    for label, side in (("shadow_side", solid), ("light_side", lit)):
        region = mixed & side
        total, actual = int(np.sum(region)), int(np.sum(region & partial))
        if softness >= 1:
            require(total >= 32 and actual >= .60 * total,
                    f"Depth penumbra on {label} produced partial light at {actual}/{total} area-light witnesses")
        result[label] = {"witnesses": total, "partially_lit": actual}
    # At the feet, keep the same one-pixel screen-space border that covers a hard AA edge.
    contact = valid & (gap < 5) & solid & (coverage == 1) & ~edge
    total, dark = int(np.sum(contact)), int(np.sum(contact & (filtered >= .92)))
    require(total >= 32 and dark >= .98 * total, f"Depth blurred contact at the feet ({dark}/{total} fully dark)")
    result["contact"] = {"witnesses": total, "fully_dark": dark}
    return result


def verify_projection(iwad, captures, ambient, folder, hard=None):
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
    softness = captures[2][1]["scene"]["depth_softness"]
    coverage = (aperture_coverage(np.asarray(lamp), state["light_angles"], 3.0 * softness, receiver, actor,
                                  light_patch, light_forward) if softness > 0 else expected)
    actor_mask = sprite_hit(eye, receiver, actor, visible_patch, camera_forward)
    # Keep an explicit transition band for camera rasterization, MSAA and light-space filtering.
    covered = filter_mask(expected, ImageFilter.MinFilter(5))
    clear = ~filter_mask(expected, ImageFilter.MaxFilter(5))
    visible = ~filter_mask(actor_mask, ImageFilter.MaxFilter(7))
    foreground = filter_mask(actor_mask, ImageFilter.MinFilter(7))
    baseline = np.asarray(off, dtype=np.int16)
    fill = np.asarray(ambient, dtype=np.int16)
    direct = np.max(baseline - fill, axis=2)
    lobes = lobe_regions(receiver, lamp, state["lobe_yaws"]) if "lobe_yaws" in state else {}
    # A single peripheral beam carries a fifth of the configured lamp power.
    usable = (direct >= (8 if lobes else 12)) & visible & (surface != "")
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
        mode_covered, mode_clear = covered, clear
        if mode == "depth" and softness > 0:
            # For thresholded shape tests omit ambiguous rays near half visibility.
            mode_covered = covered & (coverage >= .625)
            mode_clear = clear & (coverage <= .25)
        delta = baseline - np.asarray(shadow, dtype=np.int16)
        blocked = np.max(delta, axis=2) >= direct * 0.5
        witness[mode] = blocked
        require(np.any(foreground), f"Missing foreground sprite in {mode} reference")
        foreground_error = int(np.max(np.abs(delta[foreground])))
        require(foreground_error <= 2, f"{mode} changed the foreground {texture} by {foreground_error} RGB levels")
        measured = {"foreground": {"samples": int(np.sum(foreground)), "max_channel_delta": foreground_error}}
        if lobes:
            shadow_pixels = np.asarray(shadow, dtype=np.int16)
            fill_matches = np.max(np.abs(shadow_pixels - fill), axis=2) <= 2
            lit_matches = np.max(np.abs(delta), axis=2) <= 2
            for name, region in lobes.items():
                opaque = usable & mode_covered & region
                transparent = usable & mode_clear & region
                if mode == "depth" and softness > 0:
                    # Exact RGB comparisons need fully covered and fully clear aperture rays.
                    opaque &= filter_mask(coverage == 1, ImageFilter.MinFilter(3))
                    transparent &= ~filter_mask(coverage > 0, ImageFilter.MaxFilter(3))
                blue = opaque & (fill[:, :, 2] > fill[:, :, 0] + 8)
                counts = {}
                for label, mask, matches in (("opaque", opaque, fill_matches), ("blue_fill", blue, fill_matches),
                                             ("transparent", transparent, lit_matches)):
                    total, correct = int(np.sum(mask)), int(np.sum(mask & matches))
                    require(total >= 24 and correct >= total * .99,
                            f"{mode} {name} {label} matched {correct}/{total} control pixels")
                    counts[label] = {"samples": total, "matched": correct}
                measured[name] = counts
        if sloped:
            distinctive = different & (mode_covered | mode_clear)
            total = int(np.sum(distinctive))
            correct = int(np.sum((blocked == expected) & distinctive))
            require(total >= 150, "Insufficient interior samples to test light perspective")
            require(correct >= .95 * total,
                    f"{mode} matched the raised light's perspective on {correct}/{total} distinguishing pixels")
            interior_seam = seam & mode_covered
            blocked_seam = int(np.sum(blocked & interior_seam))
            require(blocked_seam >= 4 and blocked_seam == np.sum(interior_seam), f"{mode} broke the shadow at a tread/riser seam")
            measured["perspective"] = {"distinguishing_pixels": total,
                                       "light_view_matches": correct, "blocked_stair_edge_pixels": blocked_seam}
        for kind in (("floor", "slope", "riser", "wall") if sloped else ("floor", "riser", "wall")):
            test = usable & (surface == kind)
            inside, outside = test & mode_covered, test & mode_clear
            hits, misses = int(np.sum(blocked & inside)), int(np.sum(~blocked & inside))
            false_hits = int(np.sum(blocked & outside))
            measured[kind] = {"opaque_samples": hits + misses, "missed": misses,
                              "transparent_samples": int(np.sum(outside)), "false_hits": false_hits}
            require(hits >= 12 and hits >= 0.90 * (hits + misses),
                    f"{mode} {kind} missed opaque {light_texture} projection: {measured[kind]}")
            require(false_hits <= 0.10 * hits,
                    f"{mode} {kind} blocked rays through transparent {light_texture} texels: {measured[kind]}")
        result[mode] = measured
    if hard is not None:
        result["penumbra"] = verify_penumbra(baseline, fill, hard, captures[1][0], captures[2][0], usable,
                                             expected, coverage, receiver, actor, lamp, light_forward, softness)
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
