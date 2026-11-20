"""Measure a stock Imp's shadow on a wall as its distance from the flashlight changes."""

import argparse
import json
from pathlib import Path
import struct
import subprocess
from zipfile import ZipFile

import numpy as np
from PIL import Image, ImageFilter

from capture_relief import fixed_pose, require
from capture_shadow_silhouette import aperture_coverage, camera_rays, filter_mask, sprite_hit
from gallery import Map, wad
from material_generator import Wad


MAP = "SHPSCALE"
WALL_Y = 96
SCALE = 0.125
ACTOR_Z = 37.5
SIZE = (640, 480)
# Eye XY, then forward and right mount offsets. The first pair shares a camera.
CASES = {"far": (-16, -32, -16, 16), "near": (-16, -32, 16, 16),
         "subunit": (0, -16.5, 16, 0), "eye-crossing": (0, 0, -16, 0)}
MODES = {"off": 0, "stencil": 1, "depth": 2, "ambient": 0, "soft": 2}


def fixture(path, case, beam):
    x, y, _, _ = CASES[case]
    room = Map()
    sec = room.sector(0, "FLOOR5_4", 80)
    room.rows["sector"][sec].update(textureceiling="CEIL3_5", heightceiling=128)
    corners = [(-192, -128), (-192, WALL_Y), (192, WALL_Y), (192, -128)]
    for start, end in zip(corners, corners[1:] + corners[:1]):
        room.line(start, end, sec, texture="CEMENT7")
    room.thing(1, x, y, angle=90)
    script = f'''version "4.10"
class ShadowScaleImp : DoomImp
{{
    Default {{ Scale {SCALE}; +NOGRAVITY }}
    States {{ Spawn: TROO A -1; Stop; }}
}}
class ShadowScaleView : EventHandler
{{
    override void WorldTick()
    {{
        if (level.time == 2)
        {{
            players[0].mo.SetOrigin(({x},{y},0),false);
            let actor = Actor.Spawn("ShadowScaleImp", (0,0,{ACTOR_Z}), NO_REPLACE);
            actor.A_SetAngle(270);
            {"actor.Vel.X = .001;" if case == "eye-crossing" else ""}
            let lamp = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
            lamp.Enabled[0] = {str(beam).lower()};
            level.SetFrozen(true);
        }}
    }}
}}
'''
    with ZipFile(path, "w") as archive:
        archive.writestr(f"maps/{MAP}.wad", wad(MAP, room.text()))
        archive.writestr("MAPINFO", 'GameInfo { AddEventHandlers = "ShadowScaleView" }\n')
        archive.writestr("ZSCRIPT", script)


def capture(pack, exe, out, case, mode):
    folder = out / case / mode
    folder.mkdir(parents=True)
    fixture(folder / "pose.pk3", case, mode != "ambient")
    cache = folder / "cache"
    cache.mkdir()
    x, y, fore, right = CASES[case]
    profile = folder / "test.ini"
    profile.write_text("[GlobalSettings]\nvk_rayquery=false\nvid_fullscreen=false\n\n[Doom.Player.Mod]\n"
                       f"sdvk_fl_offset_x={fore}\nsdvk_fl_offset_y={right}\nsdvk_fl_offset_z=0\nsdvk_fl_aim_pitch=0\n")
    idx = MODES[mode]
    prefix = folder / "frame"
    argv = [exe, "-iwad", pack / "doom2.wad", "-file", pack / "addons/Local-Flashlight.pk3", folder / "pose.pk3",
            "-config", profile, "-savedir", folder, "-stdout", "-nostartup", "-noautoexec", "-noautoload",
            "-nosound", "-nojoy", "-rngseed", "2002", "-window", "-width", "640", "-height", "480",
            "-sdvkobserve", prefix, "-sdvkobservecache", cache, "-sdvkobservewarmup", "40",
            "-sdvkobserveframes", "1", "-sdvkobservequit", "+vid_rendermode", "4", "+vid_setsize", *SIZE,
            "+gl_raytrace", "false", "+gl_ubershaders", "false", "+gl_levelmesh", "false", "+lm_dynlights", "false",
            "+gl_lights", "true", "+gl_world_relief", "true", "+gl_spritelight", "2", "+gl_ssao", "0",
            "+gl_precache", "false",
            "+gl_multisample", "4", "+gl_bloom", "false", "+gl_light_shadows", "0", "+gl_shadow_puppets", idx,
            "+gl_shadow_puppet_softness", int(mode == "soft"), "+gl_spriteclip", "0", "+r_actorspriteshadow", "0",
            "+sdvk_fl_horizontal", "84", "+sdvk_fl_vertical", "84", "+sdvk_fl_range", "768",
            "+r_drawplayersprites", "false", "+crosshair", "0", "+con_notifylines", "0", "+screenblocks", "12",
            "+fov", "90", "+use_mouse", "false", "+cl_capfps", "true", "+vid_vsync", "false",
            "+vid_activeinbackground", "true", "+i_pauseinbackground", "false", "+map", MAP]
    with (folder / "engine.log").open("wb") as log:
        subprocess.run(list(map(str, argv)), cwd=exe.parent, stdout=log, stderr=subprocess.STDOUT,
                       timeout=120, check=True)
    report = json.loads(prefix.with_suffix(".renderer.json").read_text())
    require(report["status"] == "COLLECTED_PENDING_VALIDATION" and not report["dropped_records"] and
            report["build"]["backend"] == "vulkan", f"Missing native capture in {folder}")
    frame, = [r["data"] for r in report["records"] if r["kind"] == "frame"]
    camera = fixed_pose(frame)
    require(camera["position"][:2] == [x, y] and camera["angles"][:2] == [90, 0] and
            frame["shadow_puppets"]["requested"] == idx and
            frame["map"] == MAP and frame["relief_flashlight_lights"] == int(mode != "ambient"),
            f"Unexpected light or camera in {folder}")
    if mode != "ambient" and case != "eye-crossing":
        origins = [r["data"]["presented_flashlight"]["position"] for r in report["records"]
                   if r["kind"] == "light-query" and "presented_flashlight" in r["data"]]
        require(origins and np.allclose(origins, np.array(camera["position"]) + [right, fore, 0],
                                        rtol=0, atol=1e-4), f"Wrong rendered lamp position in {folder}")
    saved = profile.read_text()
    mount = [fore, right, 0]
    require(all(f"sdvk_fl_offset_{axis}={v}\n" in saved for axis, v in zip("xyz", mount)),
            f"Wrong mount in {folder}")
    with Image.open(prefix.with_suffix(".png")) as img:
        return camera, np.asarray(img.convert("RGB"), dtype=np.int16)


def measure(case, pack, shots):
    cam, full = shots["off"]
    eye = np.array(cam["position"])
    dx, dy, dz = camera_rays(cam, SIZE)
    t = (WALL_Y - eye[1]) / dy
    target = (eye[0] + dx * t, np.full_like(t, WALL_Y), eye[2] + dz * t)
    x, _, z = target
    _, _, fore, right = CASES[case]
    lamp = eye + [right, fore, 0]
    game = Wad(pack / "doom2.wad")
    alpha = game.patch("TROOA1")[:, :, 3] >= 128
    _, _, left, top = struct.unpack_from("<hhhh", game.lump("TROOA1"))
    patch = (alpha, left, top, False)
    # Express all rays in native IWAD texels, preserving the lamp-to-caster-to-wall ratios.
    receiver = tuple(coord / SCALE for coord in target)
    anchor = [0, 0, ACTOR_Z / SCALE]
    expected = sprite_hit(lamp / SCALE, receiver, anchor, patch, (0, 1))
    foreground = sprite_hit(eye / SCALE, receiver, anchor, patch, (0, 1))
    # At the oblique camera angle Doom can choose another rotation. Exclude
    # the entire foreground sprite rectangle before measuring the wall.
    if eye[0]:
        actor_t = -eye[1] / dy
        foreground |= ((np.abs(eye[0] + dx * actor_t) < 28 * SCALE) &
                       (np.abs(eye[2] + dz * actor_t - ACTOR_Z - 24 * SCALE) < 32 * SCALE))
    direct = np.max(full - shots["ambient"][1], axis=2)
    usable = (direct >= 16) & ~foreground & (z > 3) & (z < 125) & (np.abs(x) < 180)
    covered = usable & filter_mask(expected, ImageFilter.MinFilter(3))
    clear = usable & ~filter_mask(expected, ImageFilter.MaxFilter(3))
    magnification = (WALL_Y - lamp[1]) / -lamp[1]
    result = {"magnification": float(magnification), "lamp_distance": -float(lamp[1])}
    for mode in ("stencil", "depth"):
        camera, img = shots[mode]
        require(camera == cam, f"Camera moved in {case}/{mode}")
        blocked = np.max(full - img, axis=2) > .5 * direct
        stats = {}
        for label, mask, correct in (("shadow", covered, blocked), ("clear", clear, ~blocked)):
            if case == "subunit" and label == "clear":
                continue  # The foreground card covers the entire illuminated wall.
            total, matched = int(mask.sum()), int(correct[mask].sum())
            require(total > 100 and matched > .985 * total, f"{case}/{mode} {label}: {matched}/{total} match")
            stats[label] = {"matched": matched, "total": total}
        if case in ("near", "far"):
            # Both shadow edges are visible on this stripe through the forearms.
            center = lamp[2] + magnification * (ACTOR_Z + SCALE * (top - 24) - lamp[2])
            stripe = usable & (abs(z - center) < SCALE * magnification)

            def width(mask):
                return np.ptp(x[mask & stripe]) + (WALL_Y - eye[1]) / (SIZE[0] / 2)

            measured, reference = width(blocked), width(expected)
            require(abs(measured - reference) < 1.2, f"{mode} shadow is {measured} units, expected {reference}")
            stats["wall_width"] = round(float(measured), 3)
        result[mode] = stats
    if "soft" in shots:
        coverage = aperture_coverage(lamp / SCALE, (90, 0), 3 / SCALE, receiver, anchor, patch, (0, 1))
        partial = np.max(full - shots["soft"][1], axis=2) / np.maximum(direct, 1)
        # The larger penumbra reaches into areas that are fully lit by a point source.
        witnesses = clear & (coverage >= .20) & (coverage <= .80)
        total = int(witnesses.sum())
        matched = int((witnesses & (partial >= .06) & (partial <= .94)).sum())
        require(total > 100 and matched > .75 * total, f"{case} finite aperture: {matched}/{total} partial")
        result["penumbra"] = {"matched": matched, "total": total}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True, help="Doom II campaign playtest directory")
    parser.add_argument("--exe", type=Path, help="Native runtime override")
    parser.add_argument("--out", type=Path, required=True, help="New capture directory")
    parser.add_argument("--case", choices=CASES, action="append")
    args = parser.parse_args()
    pack, out = args.pack.resolve(), args.out.resolve()
    exe = args.exe.resolve() if args.exe else pack / "runtime/vkdoom.exe"
    results = {}
    for case in args.case or CASES:
        shots = {mode: capture(pack, exe, out, case, mode) for mode in MODES
                 if mode != "soft" or case in ("near", "far")}
        results[case] = measure(case, pack, shots)
        print(case, results[case], flush=True)
    if "far" in results and "near" in results:
        for mode in ("stencil", "depth"):
            ratio = results["near"][mode]["wall_width"] / results["far"][mode]["wall_width"]
            expected = results["near"]["magnification"] / results["far"]["magnification"]
            require(abs(ratio / expected - 1) < .05, f"{mode}: measured shadow growth {ratio}, expected {expected}")
    (out / "magnification.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
