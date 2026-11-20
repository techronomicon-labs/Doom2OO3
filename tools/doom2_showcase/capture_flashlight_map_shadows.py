"""Compare flashlight occlusion with ray-predicted shadows in a native Vulkan test room."""

import argparse
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile

import numpy as np
from PIL import Image

from build import build_flashlight
from capture_relief import require
from capture_shadow_silhouette import camera_rays
from gallery import Map, wad


SIZE = (640, 480)
MAP = "MAPSHADE"
CASES = ("closed", "lifting", "opened", "lowering", "offscreen", "far-room",
         "near-mount", "near-mount-decor", "near-mount-decor-pair", "near-mount-bars", "bars", "blocked-mount",
         "aperture-wall")
FAR_X, FAR_Y = 8192, -8192


def add_first_caster(room, x0, y0, x1, y1, sector, inner=None):
    # The two faces crossed by the test rays must own mesh triangles 0..3.
    # This exposes a renderer that mistakes the first map faces for dummy geometry.
    a, b, c, d = (x0, y0), (x1, y0), (x1, y1), (x0, y1)
    for start, end in ((a, b), (c, d), (b, c), (d, a)):
        room.line(start, end, sector, inner, "METAL2")


def fixture(path, case, torch, animate=False):
    room = Map()
    sector = room.sector(0, "FLOOR5_4", 100)
    room.rows["sector"][sector].update(heightceiling=120, textureceiling="CEIL3_5")
    if case == "offscreen":
        # The pillar is outside the camera's 90-degree frustum. The offset beam sees it.
        add_first_caster(room, 13, -76, 15, -72, sector)
    if case == "blocked-mount":
        # The player's collision box ends at x=16. The requested diagonal mount
        # reaches x=22.63 across this freestanding pillar.
        add_first_caster(room, 18, -86, 20, -77, sector)
    if case == "aperture-wall":
        # The eye can see past the north end. The mounted lamp touches the west
        # face, and the right tip of its aperture would sit beyond the east face.
        add_first_caster(room, 18, -126, 20, -46, sector)
    near_mount = case.startswith("near-mount")
    if near_mount:
        # The lamp is at (16, -82). This opaque sill fits entirely inside
        # the old depth camera's one-unit near plane and outside the eye's view.
        add_first_caster(room, 16, -81.5, 32, -81.25, sector)
        if case == "near-mount-decor":
            room.thing(30, 16, 16)  # A green pillar straddles the shadow boundary.
        elif case == "near-mount-decor-pair":
            for x in (-8, 40):
                room.thing(30, x, 16)  # One pillar is fully lit, the other fully occluded.
    if case in ("near-mount-bars", "bars"):
        beyond = room.sector(0, "FLOOR5_4", 100)
        room.rows["sector"][beyond].update(heightceiling=120, textureceiling="CEIL3_5")
        for cell, vertices in ((sector, [(128, -32), (128, -128), (-128, -128), (-128, -32)]),
                               (beyond, [(-128, -32), (-128, 164), (128, 164), (128, -32)])):
            for a, b in zip(vertices, vertices[1:]):
                room.line(a, b, cell, texture="BRICK7")
        room.line((-128, -32), (128, -32), sector, beyond)
        for side in room.rows["sidedef"][-2:]:
            side.update(texturemiddle="MIDBARS1", scalex_mid=1, scaley_mid=1)
    else:
        corners = [(-128, -128), (-128, 164), (128, 164), (128, -128)]
        for a, b in zip(corners, corners[1:] + corners[:1]):
            room.line(a, b, sector, texture="BRICK7")
    if not near_mount and case not in ("far-room", "offscreen", "bars", "blocked-mount", "aperture-wall"):
        door = room.sector(0, "FLOOR5_4", 100)
        room.rows["sector"][door].update(heightceiling=0, textureceiling="CEIL3_5", id=1)
        room.rect(-24, -28, 24, -20, sector, door, "BIGDOOR2")
    angled_mount = case in ("blocked-mount", "aperture-wall")
    room.thing(1, 0, -82, angle=45 if angled_mount else 90)
    room.thing(30121, -40, 76, z=32, arg0=40, arg1=75, arg2=180, arg3=60)
    # Let the real mover reach the open stop before activating the downward motion.
    moving = case in ("lifting", "opened", "lowering")
    height = {"closed": 0, "lifting": 32, "opened": 116, "lowering": 32}.get(case, 120)
    dx, dy = (FAR_X, FAR_Y) if case == "far-room" else (0, 0)
    if dx or dy:
        for row in room.rows["vertex"] + room.rows["thing"]:
            row["x"] += dx
            row["y"] += dy
    pose = "level.time >= 24 && z <= 32" if case == "lowering" else f"level.time >= 4 && z >= {height}"
    mount_probe = ""
    if angled_mount and torch:
        mount_probe = '''if (level.time == 10)
        {
            let it = ThinkerIterator.Create("SDVKLocalFlashlightBeam", Thinker.STAT_DLIGHT);
            let beam = Actor(it.Next());
            if (beam != null) Console.Printf("MOUNT_X %.4f", beam.Pos.X);
        }'''
    script = f'''version "4.10"
class MapShadowFixture : EventHandler
{{
    bool captured;
    override void WorldTick()
    {{
        {"if (level.time == 2) Door_Open(1, 64);" if moving else ""}
        {"if (level.time == 22) Door_Close(1, 64);" if case == "lowering" else ""}
        let sector = level.PointInSector(({dx}, {dy - 24}));
        double z = sector.ceilingplane.ZatPoint(({dx}, {dy - 24}));
        {mount_probe}
        if (!captured && {pose})
        {{
            captured = true;
            {"Ceiling_Stop(1);" if case in ("lifting", "lowering") else ""}
            {"players[0].mo.A_SetAngle(83); players[0].mo.A_SetPitch(6);" if case == "far-room" else ""}
            let lamp = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
            lamp.Enabled[0] = {str(torch).lower()};
            Console.Printf("MAP_SHADOW_CAPTURE ceiling %.2f", z);
            level.SetFrozen(true);
        }}
    }}
}}
'''
    if animate:
        # Hold each pose long enough to compare fully presented frames, with
        # the same light and depth target continuously active throughout.
        script = '''version "4.10"
class MapShadowFixture : EventHandler
{
    override void WorldTick()
    {
        if (level.time == 2)
        {
            let lamp = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
            lamp.Enabled[0] = true;
        }
        int phase = level.time % 48;
        if (phase == 4 || phase == 16) Door_Open(1, 64);
        if (phase == 8) Ceiling_Stop(1);
        if (phase == 34) Door_Close(1, 128);
    }
}
'''
    with ZipFile(path, "w") as archive:
        archive.writestr(f"maps/{MAP}.wad", wad(MAP, room.text()))
        archive.writestr("MAPINFO", 'GameInfo { AddEventHandlers = "MapShadowFixture" }\n'
                         'DoomEdNums { 30121 = PointLightAttenuated }\n')
        archive.writestr("ZSCRIPT", script)


def capture(exe, iwad, root, case, enabled, torch, mode, animate=False, sprite_lighting=2):
    label = "moving" if animate else f"{'torch' if torch else 'fill'}-{int(enabled)}-sprites-{mode}"
    if sprite_lighting != 2:
        label += f"-lighting-{sprite_lighting}"
    folder = root / case / label
    folder.mkdir(parents=True)
    package = folder / "fixture.pk3"
    fixture(package, case, torch, animate)
    cfg = folder / "profile.ini"
    cfg.write_text("[GlobalSettings]\nvk_rayquery=false\nvid_fullscreen=false\n", encoding="ascii")
    prefix = folder / "frame"
    cache = folder / "cache"
    cache.mkdir()
    width, height = map(str, SIZE)
    args = [exe, "-iwad", iwad, "-file", root / "Local-Flashlight.pk3", package, "-noautoload",
            "-noautoexec", "-stdout", "-nostartup", "-nosound", "-nojoy", "-rngseed", "2002",
            "-config", cfg, "-savedir", folder, "-window", "-width", width, "-height", height,
            "-sdvkobserve", prefix, "-sdvkobservecache", cache, "-sdvkobservewarmup", "50",
            "-sdvkobserveframes", "52" if animate else "1", "-sdvkobservequit",
            "+vid_rendermode", "4", "+vid_setsize", width, height,
            "+gl_levelmesh", "false", "+gl_raytrace", "false", "+lm_dynlights", "false",
            "+gl_ubershaders", "false", "+gl_lightprobe", "false", "+gl_world_relief", "true",
            "+gl_lights", "true", "+gl_light_shadows", "0", "+gl_light_sprites", "true", "+gl_spritelight", str(sprite_lighting),
            "+gl_ssao", "0", "+gl_multisample", "4", "+gl_precache", "false",
            "+gl_emitter_lighting", "false", "+gl_bloom", "false", "+gl_shadow_puppets", str(mode),
            "+gl_flashlight_map_shadows", str(enabled).lower(),
            "+gl_flashlight_map_shadow_radius", "12" if case == "aperture-wall" else "0",
            "+r_drawplayersprites", "false",
            "+screenblocks", "12", "+fov", "90", "+crosshair", "0", "+cl_capfps", "true",
            "+con_notifylines", "0", "+show_messages", "false", "+vid_vsync", "false", "+use_mouse", "false",
            "+i_pauseinbackground", "false", "+vid_activeinbackground", "true",
            "+sdvk_fl_offset_x", "16" if case in ("blocked-mount", "aperture-wall") else "0", "+sdvk_fl_offset_y", "16",
            "+sdvk_fl_offset_z", "16", "+sdvk_fl_aim_pitch", "0", "+sdvk_fl_horizontal", "84",
            "+sdvk_fl_vertical", "84", "+sdvk_fl_range", "640", "+map", MAP]
    if animate:
        args.extend(("-sdvkobservepngs", "+screenshot_quiet", "true", "+screenshot_type", "png"))
    log = folder / "engine.log"
    with log.open("wb") as output:
        subprocess.run(list(map(str, args)), cwd=exe.parent, stdout=output, stderr=subprocess.STDOUT,
                       timeout=75, check=True)
    messages = log.read_text(errors="replace")
    require("Unknown command" not in messages, f"Unsupported setting in {log}")
    match = re.search(r"MAP_SHADOW_CAPTURE ceiling ([\d.]+)", messages)
    require(animate or match is not None, f"Test pose did not freeze in {log}")
    if case in ("blocked-mount", "aperture-wall") and torch:
        mount = re.search(r"MOUNT_X ([-\d.]+)", messages)
        require(mount is not None and 17 <= float(mount[1]) < 18, f"Mount crossed the pillar in {log}")
    report = json.loads(prefix.with_suffix(".renderer.json").read_text())
    require(report["status"] == "COLLECTED_PENDING_VALIDATION" and report["dropped_records"] == 0
            and report["build"]["backend"] == "vulkan" and report["screenshot"]["available"],
            f"Missing Vulkan capture in {folder}")
    frames = [r["data"] for r in report["records"] if r["kind"] == "frame"]
    expected_xy = [FAR_X, FAR_Y - 82] if case == "far-room" else [0, -82]
    require(all(frame["map"] == MAP and frame["camera"]["position"][:2] == expected_xy
                and frame["relief_flashlight_lights"] == int(torch) for frame in frames),
            f"Unexpected light or view in {folder}")
    passes = [r["data"] for r in report["records"] if r["kind"] == "flashlight-map-shadows"]
    require((len(passes) == len(frames) and all(p["light_links"] > 0 for p in passes)) if enabled and torch else not passes,
            f"Unexpected geometry shadow pass in {folder}")
    if animate:
        sequence = [r["data"] for r in report["records"] if r["kind"] == "frame-sequence"]
        require(len(frames) == len(sequence) == 52, f"Missing moving-door frames in {folder}")
        return [(row["level_tic"], folder / row["image"]) for row in sequence]
    frame, = frames
    with Image.open(prefix.with_suffix(".png")) as image:
        require(image.size == SIZE, "Incorrect frame size")
        return np.asarray(image.convert("RGB"), dtype=np.int16), frame["camera"], float(match[1])


def measure(case, camera, door_z, unshadowed, shadowed, fill):
    # Project pixel centres onto floor and back wall, then evaluate the obstruction
    # from both the camera (visible receiver) and flashlight (expected shadow).
    if case == "far-room":
        # The whole room is convex. Avoid texel footprints spanning two faces
        # at a join when checking for acne within each uninterrupted surface.
        dx, dy, dz = camera_rays(camera, SIZE)
        floor = np.divide(-41, dz, out=np.full_like(dz, np.inf), where=dz < 0)
        ceiling = np.divide(120 - 41, dz, out=np.full_like(dz, np.inf), where=dz > 0)
        sides = 128 / np.maximum(abs(dx), 1e-9)
        distances = np.sort(np.stack((floor, ceiling, sides, 246 / dy)), axis=0)
        interior = distances[1] - distances[0] > 2
        lit = np.max(unshadowed - fill, axis=2) >= 12
        good = np.max(abs(shadowed - unshadowed), axis=2) <= 3
        tested = lit & interior
        total, kept = int(np.sum(tested)), int(np.sum(tested & good))
        require(total > 10000 and kept >= total * .9999, f"Far-room interior self-shadow: {total - kept}/{total}")
        return {"convex room interior": [kept, total], "changed seam pixels": int(np.sum(lit & ~interior & ~good))}
    dx, dy, dz = camera_rays(camera, SIZE)
    eye = camera["position"]
    floor_t = np.divide(-eye[2], dz, out=np.full_like(dz, np.inf), where=dz < 0)
    wall_t = (164 - eye[1]) / dy
    t = np.minimum(floor_t, wall_t)
    x, y, z = (value + t * ray for value, ray in zip(eye, (dx, dy, dz)))
    interior = (abs(x) < 100) & (z < 108) & (y > 0)
    direct = np.max(unshadowed - fill, axis=2)
    usable = interior & (direct >= 16)
    restored_fill = np.max(np.abs(shadowed - fill), axis=2) <= 3
    retained_light = np.max(np.abs(shadowed - unshadowed), axis=2) <= 3
    shadow_witnesses = {}
    lit_witnesses = {}

    if case == "aperture-wall":
        # At yaw 45 the horizontal disk projects at most 12/sqrt(2) onto X
        # and Y. Even the northwestern extreme's ray must pass through the wall.
        extent = 12 / np.sqrt(2)
        west, north = 17.5 - extent, -82 + extent
        y_at_face = north + (18 - west) * (y - north) / np.maximum(x - west, 1e-4)
        eye_clear = eye[1] + 18 * (y - eye[1]) / np.maximum(x, 1e-4) > -45
        region = usable & (x > 50) & eye_clear & (y_at_face < -47)
        count = int(np.sum(region))
        correct = int(np.sum(region & restored_fill))
        require(count > 1000 and correct >= .99 * count, f"Aperture leaked across a solid wall: {correct}/{count}")
        return {"aperture against wall": [correct, count]}
    if case == "blocked-mount":
        # The camera sees beyond the pillar's north edge. A ray from the
        # clipped mount to any of these pixels immediately hits its west face.
        region = usable & (x > 50) & (y - eye[1] < 2 * (x - 18))
        count = int(np.sum(region))
        correct = int(np.sum(region & restored_fill))
        require(count > 1000 and correct >= .99 * count, f"Mount leaked through the pillar: {correct}/{count}")
        return {"blocked mount": [correct, count]}
    if case.startswith("near-mount"):
        if case.startswith("near-mount-decor"):
            # Intersect the camera-facing COL1 sprite with the view rays. Select
            # green interior texels to exclude transparent sprite corners and
            # the gray/brown room that shows through them.
            sprite_t = (16 - eye[1]) / dy
            x = eye[0] + sprite_t * dx
            y = np.full_like(x, 16)
            z = eye[2] + sprite_t * dz
            red, green, blue = unshadowed.transpose(2, 0, 1)
            interiors = abs(x - 16) < 12 if case == "near-mount-decor" else (abs(x + 8) < 12) | (abs(x - 40) < 12)
            usable = interiors & (z > 4) & (z < 51) & (green > red * 1.2) & (green > blue * 1.2) & (direct >= 12)
        if case == "near-mount-bars":
            grate_t = (-32 - eye[1]) / dy
            x = eye[0] + grate_t * dx
            y = np.full_like(x, -32)
            z = eye[2] + grate_t * dz
            column = (x + 128) % 16
            usable = (column > 7.15) & (column < 8.85) & (z > 24) & (z < 94) & (direct >= 12)
        # A ray to the right of x=16 hits the sill; one to its left clears it.
        # Leave a margin for the light bias and for sprite pixel footprints.
        x_at_sill = 16 + 0.5 * (x - 16) / (y - eye[1])
        lit = x_at_sill < 15.985
        dark = x_at_sill > 16.015
        if case == "near-mount":
            shadow_witnesses = {"near-mount sill onto floor": dark & (floor_t < wall_t),
                                 "near-mount sill onto wall": dark & (floor_t > wall_t)}
    elif case == "bars":
        # The source MIDBARS1 patch has five opaque columns at 6..10 of
        # each 16-texel repeat between its top and bottom rails. Ignore the
        # outer texels of each bar, the rails, and pixels hidden from the eye.
        at_grate = (-32 - eye[1]) / (y - eye[1])
        camera_column = (at_grate * x + 128) % 16
        beam_column = (16 + at_grate * (x - 16) + 128) % 16
        camera_z = eye[2] + at_grate * (z - eye[2])
        beam_z = eye[2] + 16 + at_grate * (z - eye[2] - 16)
        usable &= ((camera_column < 3) | (camera_column > 13)) & (camera_z > 24) & (camera_z < 94)
        usable &= (beam_z > 24) & (beam_z < 94)
        dark = (beam_column > 7.15) & (beam_column < 8.85)
        lit = (beam_column < 3) | (beam_column > 13)
        shadow_witnesses["opaque bars onto floor"] = dark & (floor_t < wall_t)
        lit_witnesses["open slots onto wall"] = lit & (floor_t > wall_t)
    elif case == "offscreen":
        def cross_x(at_y):
            return 16 + (at_y - eye[1]) / (y - eye[1]) * (x - 16)
        # Exclude a margin along the projected silhouette.
        lit = (cross_x(-76) < 12.4) | (cross_x(-72) > 15.6)
        dark = (cross_x(-76) > 13.35) & (cross_x(-72) < 14.65)
        shadow_witnesses = {"offscreen pillar onto floor": dark & (floor_t < wall_t),
                             "offscreen pillar onto wall": dark & (floor_t > wall_t)}
    else:
        front, back = ((edge - eye[1]) / (y - eye[1]) for edge in (-28, -20))

        def clearance(start_x, start_z):
            xf, xb = (start_x + t * (x - start_x) for t in (front, back))
            zf, zb = (start_z + t * (z - start_z) for t in (front, back))
            open_ray = (np.minimum(xf, xb) > 26) | (np.maximum(xf, xb) < -26) | (np.maximum(zf, zb) < door_z - 2)
            solid_ray = ((abs(xf) < 22) & (zf > door_z + 2)) | ((abs(xb) < 22) & (zb > door_z + 2))
            return open_ray, solid_ray

        visible, _ = clearance(eye[0], eye[2])
        usable &= visible
        lit, dark = clearance(16, eye[2] + 16)
        if case in ("lifting", "lowering"):
            # Both rays pass within the width of the door. Only its height
            # determines whether the beam can reach this visible floor.
            centre = (abs(front * x) < 22) & (abs(16 + front * (x - 16)) < 22)
            shadow_witnesses["under the lintel"] = centre & dark & (floor_t < wall_t)
    results = {}
    for label, region, matches in (("shadow", dark, restored_fill),
                                   ("lit", lit, retained_light)):
        mask = usable & region
        total, correct = int(np.sum(mask)), int(np.sum(mask & matches))
        results[label] = [correct, total]
        if label == "lit" or case != "opened":
            require(total >= 100 and correct >= total * .95, f"{case}: {label} {correct}/{total}")
    for witnesses, matches in ((shadow_witnesses, restored_fill), (lit_witnesses, retained_light)):
        for label, region in witnesses.items():
            count = int(np.sum(usable & region))
            correct = int(np.sum(usable & region & matches))
            require(count >= 100 and correct >= .95 * count, f"{case}: {label} {correct}/{count}")
            results[label] = [correct, count]
    return results


def verify_motion(exe, iwad, root):
    def read(path):
        with Image.open(path) as image:
            return np.asarray(image.convert("RGB"), dtype=np.int16)

    # Restrict the comparison to receivers which remain visible and directly
    # lit in both unshadowed control views, but lose that light under the lintel.
    def fixed(case, enabled):
        return read(root / case / f"torch-{int(enabled)}-sprites-0/frame.png")

    lifted, opened = fixed("lifting", True), fixed("opened", True)
    direct = fixed("lifting", False)
    region = ((np.max(direct - lifted, axis=2) >= 16) & (np.max(abs(direct - opened), axis=2) <= 2)
              & (np.max(abs(direct - fixed("opened", False)), axis=2) <= 2))
    require(np.sum(region) > 1000, "No receiver shared by the lifting and open views")
    tested = set()
    for tic, path in capture(exe, iwad, root, "lifting", True, True, 0, animate=True):
        phase = tic % 48
        if 11 <= phase <= 14:
            label, expected = "lifting", lifted
        elif 30 <= phase <= 32:
            label, expected = "opened", opened
        else:
            continue
        correct = np.max(abs(read(path)[region] - expected[region]), axis=1) <= 3
        require(np.mean(correct) >= .99, f"Moving door {label}: {np.mean(correct):.3%} match at tic {tic}")
        tested.add(label)
    require(tested == {"lifting", "opened"}, "Continuous capture missed a door pose")
    print(f"Continuously lit door: {np.sum(region)} receivers tracked across both poses", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--iwad", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="new output directory")
    parser.add_argument("--case", choices=CASES, action="append")
    args = parser.parse_args()
    exe, iwad, root = (p.resolve() for p in (args.exe, args.iwad, args.out))
    root.mkdir(parents=True)
    build_flashlight(root)
    cases = args.case or CASES
    for case in cases:
        for lighting in ((0, 1) if case == "near-mount-decor-pair" else (2,)):
            off, camera, door_z = capture(exe, iwad, root, case, False, True, 0, sprite_lighting=lighting)
            on, _, _ = capture(exe, iwad, root, case, True, True, 0, sprite_lighting=lighting)
            fill, _, _ = capture(exe, iwad, root, case, True, False, 0, sprite_lighting=lighting)
            results = measure(case, camera, door_z, off, on, fill)
            print(f"{case}, ceiling {door_z:g}, sprite lighting {lighting}, {results}", flush=True)
        if case == "lifting":
            control, _, _ = capture(exe, iwad, root, case, False, False, 0)
            require(np.array_equal(control, fill), "Map shadows changed independent lighting with the torch off")
            for mode in (1, 2):
                same, _, _ = capture(exe, iwad, root, case, True, True, mode)
                require(np.array_equal(same, on), f"Map shadow changed with sprite shadow mode {mode}")
    if "lifting" in cases and "opened" in cases:
        verify_motion(exe, iwad, root)


if __name__ == "__main__":
    main()
