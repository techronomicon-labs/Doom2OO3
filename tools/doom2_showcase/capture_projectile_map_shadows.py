"""Check stock projectile light against Entryway's pillar and a raised ledge in Vulkan."""

import argparse
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile

import numpy as np
from PIL import Image

from capture_flashlight_map_shadows import add_first_caster
from capture_relief import require
from capture_shadow_silhouette import camera_rays
from gallery import Map, wad


SIZE = (640, 480)
CASES = ("entryway", "ledge")


def fixture(path, case):
    entryway = case == "entryway"
    # Look down from the south steps at the BRONZE2 pillar and the corridor beyond.
    camera = (-101, 814, 118, 13) if entryway else (-78, -64, 47, 12)
    x, y, yaw, pitch = camera
    launch = ('Actor.Spawn("Rocket", (-108, 982, 46), NO_REPLACE)' if entryway else
              'Actor.Spawn("PlasmaBall", (0, -29, 56), NO_REPLACE)')
    second_light = "" if entryway else '''
            let rocket = Actor.Spawn("Rocket", (36, 30, 32), NO_REPLACE);
            if (rocket) rocket.target = pawn;
'''
    script = f'''version "4.10"
class ProjectileMapWitness : EventHandler
{{
    Actor subject;
    int phaseTics;
    override void WorldTick()
    {{
        if (level.time == 2)
        {{
            let pawn = players[0].mo;
            pawn.bNoRadiusDmg = true;
            let sector = level.PointInSector(({x}, {y}));
            pawn.SetOrigin(({x}, {y}, sector.floorplane.ZatPoint(({x}, {y}))), false);
            pawn.A_SetAngle({yaw});
            pawn.A_SetPitch({pitch});
            let torch = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
            torch.Enabled[0] = true;
            {second_light}
            subject = {launch};
            if (subject != null)
            {{
                subject.Vel = ({-12 if entryway else 0}, 0, 0);
                subject.target = pawn;
            }}
        }}
        if (subject && level.time > 3 && {"!subject.bMissile" if entryway else "subject.bMissile"})
        {{
            if (++phaseTics == 2)
            {{
                Console.Printf("PROJECTILE_SHADOW %s %.3f %.3f %.3f %d",
                    subject.GetClassName(), subject.Pos.X, subject.Pos.Y, subject.Pos.Z, int(subject.bMissile));
                level.SetFrozen(true);
            }}
        }}
    }}
}}
'''
    with ZipFile(path, "w") as archive:
        if entryway:
            # The stock MISLB attachment randomly chooses size 96 or 108 every tic.
            # Hold its brighter native sample for the four fixed-view exposures.
            archive.writestr("GLDEFS", "flickerlight ROCKET_X1 { color 1.0 0.7 0.5 size 108 "
                             "secondarySize 108 chance 0.3 attenuate 1 }\n")
        else:
            room = Map()
            sector = room.sector(0, "FLOOR5_4", 100)
            step = room.sector(26, "FLOOR5_4", 100)
            for row in room.rows["sector"]:
                row.update(heightceiling=120, textureceiling="CEIL3_5")
            # A low, narrow ledge leaves rays that cross both risers below the top.
            add_first_caster(room, -20, -4, 20, 0, sector, step)
            corners = [(-128, -128), (-128, 128), (128, 128), (128, -128)]
            for start, end in zip(corners, corners[1:] + corners[:1]):
                room.line(start, end, sector, texture="BRICK7")
            room.thing(1, x, y, angle=yaw)
            archive.writestr("maps/PRJLEDGE.wad", wad("PRJLEDGE", room.text()))
        archive.writestr("MAPINFO", 'GameInfo { AddEventHandlers = "ProjectileMapWitness" }\n')
        archive.writestr("ZSCRIPT", script)


def capture(pack, exe, root, case, label, enabled, power, rocket_flight_power=0):
    directory = root / case / label
    directory.mkdir(parents=True)
    cache = directory / "cache"
    cache.mkdir()
    config = directory / "capture.ini"
    config.write_text("[GlobalSettings]\nvk_rayquery=false\nvid_fullscreen=false\n")
    entryway = case == "entryway"
    files = [pack / "addons" / name for name in (
        "DoomII-NormalPBR.pk3", "DoomII-SpritePBR.pk3", "Local-Flashlight.pk3", "DoomII-Emitter-Lighting.pk3")]
    files.append(root / (case + ".pk3"))
    width, height = map(str, SIZE)
    prefix = directory / "frame"
    args = [exe, "-iwad", pack / "doom2.wad", "-file", *files, "-stdout", "-nostartup", "-noautoload",
            "-noautoexec", "-nosound", "-nojoy", "-nomonsters", "-rngseed", "2002", "-config", config,
            "-savedir", directory, "-window", "-width", width, "-height", height, "-sdvkobserve", prefix,
            "-sdvkobservecache", cache, "-sdvkobservewarmup", "30", "-sdvkobserveframes", "1", "-sdvkobservequit",
            "+vid_rendermode", "4", "+vid_setsize", width, height, "+gl_lights", "true", "+gl_ubershaders", "false",
            "+gl_raytrace", "false", "+gl_levelmesh", "false", "+lm_dynlights", "false", "+gl_light_shadows", "0",
            "+gl_bloom", "false", "+gl_ssao", "0", "+gl_world_relief", "true", "+gl_sprite_lighting_relief", "true",
            "+gl_multisample", "4", "+gl_emitter_lighting", str(entryway).lower(), "+gl_emitter_ambient", ".115625",
            "+gl_emitter_ambient_specular", ".5", "+gl_emitter_intensity", "1.225",
            "+gl_rocket_impact_light" if entryway else "+gl_plasma_flight_light", str(power),
            "+r_drawplayersprites", "false", "+screenblocks", "12", "+fov", "90", "+crosshair", "0",
            "+cl_capfps", "true", "+vid_vsync", "false", "+use_mouse", "false", "+con_notifylines", "0",
            "+map", "MAP01" if entryway else "PRJLEDGE"]
    if entryway:
        args.extend(("+sdvk_fl_power", "100", "+sdvk_fl_offset_x", ".9", "+sdvk_fl_offset_y", "0",
                     "+sdvk_fl_offset_z", "9.5",
                     "+sdvk_fl_aim_pitch", "-7.875", "+sdvk_fl_horizontal", "64.05",
                     "+sdvk_fl_vertical", "71.75", "+sdvk_fl_range", "768"))
    else:
        args.extend(("+gl_rocket_flight_light", str(rocket_flight_power)))
    if enabled is not None:
        args.extend(("+gl_projectile_map_shadows", str(enabled).lower()))
    log = directory / "engine.log"
    with log.open("wb") as output:
        subprocess.run(list(map(str, args)), cwd=exe.parent, stdout=output, stderr=subprocess.STDOUT,
                       check=True, timeout=75)
    messages = log.read_text(errors="replace")
    require("Unknown command" not in messages, f"Unsupported setting in {log}")
    match = re.search(r"PROJECTILE_SHADOW (Rocket|PlasmaBall) ([-.\d]+) ([-.\d]+) ([-.\d]+) ([01])", messages)
    require(match is not None and match[1] == ("Rocket" if entryway else "PlasmaBall") and
            match[5] == ("0" if entryway else "1"), f"Missing stock projectile phase in {log}")
    report = json.loads(prefix.with_suffix(".renderer.json").read_text())
    require(report["status"] == "COLLECTED_PENDING_VALIDATION" and report["build"]["backend"] == "vulkan"
            and not report["dropped_records"] and report["screenshot"]["available"], f"Incomplete run in {directory}")
    frame, = [r["data"] for r in report["records"] if r["kind"] == "frame"]
    if enabled is not None:
        links = sum(r["data"]["light_links"] for r in report["records"] if r["kind"] == "projectile-map-shadows")
        require(bool(links) == bool(enabled and (power or rocket_flight_power)),
                f"Unexpected projectile receiver links in {directory}")
    require(frame["relief_flashlight_lights"] >= 1 and frame["settings"]["gl_light_shadows"] == 0
            and frame["stage_b"]["requested"] == entryway, f"Wrong lighting in {directory}")
    source = tuple(map(float, match.groups()[1:4]))
    if entryway:
        lights = [r["data"]["light"] for r in report["records"] if r["kind"] == "shadow" and "light" in r["data"]]
        require(any(tuple(light["position"]) == source and light["radius"] == 216 for light in lights),
                f"Unmatched rocket light in {directory}")
    with Image.open(prefix.with_suffix(".png")) as image:
        return np.asarray(image.convert("RGB"), dtype=np.int16), frame["camera"], source


def box_hit(origin, target, low, high):
    """Intersect finite source-to-receiver segments with an axis-aligned solid."""
    enter, leave = 0., 1.
    for a, b, start, end in zip(low, high, origin, target):
        direction = np.where(abs(end - start) < 1e-9, 1e-9, end - start)
        t0, t1 = (a - start) / direction, (b - start) / direction
        enter, leave = np.maximum(enter, np.minimum(t0, t1)), np.minimum(leave, np.maximum(t0, t1))
    return enter < leave


def receivers(case, camera, source, clear, fill):
    entryway = case == "entryway"
    floor = 8 if entryway else 0
    eye = camera["position"]
    dx, dy, dz = camera_rays(camera, SIZE)
    t = (floor - eye[2]) / np.minimum(dz, -1e-8)
    target = (eye[0] + t * dx, eye[1] + t * dy, floor + np.zeros_like(dx))
    x, y, _ = target
    if entryway:
        low, high = (-256, 960, 8), (-192, 1024, 264)
        region = (x > -308) & (x < -170) & (y > 918) & (y < 1140)
    else:
        low, high = (-20, -4, 0), (20, 0, 26)
        region = (abs(x) < 16) & (y > 3) & (y < 76)
    region &= ~box_hit(eye, target, np.subtract(low, 1), np.add(high, 1))
    region &= (dz < 0) & (np.max(clear - fill, axis=2) >= 12)
    inset = np.array((1, 1, 1))
    dark = region & box_hit(source, target, np.add(low, inset), np.subtract(high, inset))
    lit = region & ~box_hit(source, target, np.subtract(low, inset), np.add(high, inset))
    return dark, lit


def entryway_wall(camera, source, clear, fill):
    """Trace visible PIPE4 wall pixels on MAP01 linedef 10 behind the BRONZE2 pillar."""
    eye = camera["position"]
    dx, dy, dz = camera_rays(camera, SIZE)
    # The wall runs from (-384, 960) to (-320, 1280), with inward normal (5, -1).
    t = (5 * (-384 - eye[0]) - (960 - eye[1])) / (5 * dx - dy)
    target = (eye[0] + t * dx, eye[1] + t * dy, eye[2] + t * dz)
    y, z = target[1:]
    low, high = np.array((-256, 960, 8)), np.array((-192, 1024, 264))
    return ((t > 0) & (y > 970) & (y < 1270) & (z > 12) & (z < 110)
            & ~box_hit(eye, target, low - 1, high + 1) & box_hit(source, target, low + 1, high - 1)
            & (np.max(clear - fill, axis=2) >= 12))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True, help="Doom II campaign playtest directory")
    parser.add_argument("--exe", type=Path, help="override the packaged executable")
    parser.add_argument("--out", type=Path, required=True, help="new output directory")
    parser.add_argument("--case", choices=CASES, action="append")
    parser.add_argument("--baseline", action="store_true", help="measure unoccluded light on an older build")
    args = parser.parse_args()
    root, pack = args.out.resolve(), args.pack.resolve()
    exe = args.exe.resolve() if args.exe else pack / "runtime/vkdoom.exe"
    root.mkdir(parents=True)
    for case in args.case or CASES:
        fixture(root / (case + ".pk3"), case)
        power = 1200 if case == "entryway" else 300
        off = None if args.baseline else False
        clear, camera, source = capture(pack, exe, root, case, "unshadowed", off, power)
        fill, _, _ = capture(pack, exe, root, case, "fill", off, 0)
        dark, lit = receivers(case, camera, source, clear, fill)
        require(dark.sum() > 100 and lit.sum() > 100, f"{case}: insufficient witnesses {dark.sum()}/{lit.sum()}")
        print(case, source, "blocked / clear floor samples", int(dark.sum()), int(lit.sum()), flush=True)
        if not args.baseline:
            on, pose, light = capture(pack, exe, root, case, "shadowed", True, power)
            control, _, _ = capture(pack, exe, root, case, "fill-shadowed", True, 0)
            require(all(np.allclose(camera[k], pose[k], rtol=0, atol=1e-6)
                        for k in ("position", "angles", "hardware_angles", "fov")) and source == light,
                    "Camera or projectile moved between comparisons")
            require(np.max(abs(fill - control)) <= 2, f"{case}: shadow toggle changed independent light")
            checks = [("blocked floor", dark, fill), ("clear floor", lit, clear)]
            if case == "entryway":
                checks.append(("blocked wall", entryway_wall(camera, source, clear, fill), fill))
            for name, mask, expected in checks:
                require(mask.sum() > 100, f"{case}: insufficient {name} samples")
                correct = np.max(abs(on - expected), axis=2)[mask] <= 3
                print(case, name, f"{np.mean(correct):.2%} of {mask.sum()}", flush=True)
                require(np.mean(correct) >= .97, f"{case}: incorrect {name} projectile lighting")
            if case == "ledge":
                rocket, _, _ = capture(pack, exe, root, case, "rocket-only", True, 0, rocket_flight_power=100)
                both, _, _ = capture(pack, exe, root, case, "both-lights", True, power, rocket_flight_power=100)
                # These pixels receive orange rocket light and would also receive blue plasma through the ledge.
                overlap = dark & (rocket[:, :, 0] - fill[:, :, 0] >= 12)
                require(overlap.sum() > 100, "Too few shared receivers for the two projectiles")
                correct = np.max(abs(both - rocket), axis=2)[overlap] <= 3
                print(case, "only the visible light", f"{np.mean(correct):.2%} of {overlap.sum()}", flush=True)
                require(np.mean(correct) >= .97, "The occluded plasma changed the rocket-lit floor")
                require(np.sum(lit & (both[:, :, 2] - rocket[:, :, 2] >= 8)) > 100,
                        "Plasma failed to contribute beyond the ledge in the two-light scene")


if __name__ == "__main__":
    main()
