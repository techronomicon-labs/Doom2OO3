"""Check that the campaign flashlight exposes Entryway's pillar shadow during normal play."""

import argparse
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile

import numpy as np
from PIL import Image

from capture_projectile_map_shadows import SIZE, receivers
from capture_relief import require


# Each camera looks just past the western side of the BRONZE2 pillar at floor
# height 8. The ordinary camera sees the receivers behind its left edge.
POSES = {"corner": (-273, 928, 93, 8), "floor": (-280, 910, 88, 15)}


def capture(pack, exe, folder, pose, beam, shadows, centered):
    folder.mkdir(parents=True)
    x, y, yaw, pitch = pose
    fixture = folder / "pose.pk3"
    with ZipFile(fixture, "w") as archive:
        archive.writestr("MAPINFO", 'GameInfo { AddEventHandlers = "EntrywayLampPose" }\n')
        archive.writestr("ZSCRIPT", f'''version "4.10"
class EntrywayLampPose : EventHandler
{{
    override void WorldTick()
    {{
        let pawn = players[0].mo;
        if (level.time == 3)
        {{
            let sec = level.PointInSector(({x}, {y}));
            pawn.SetOrigin(({x}, {y}, sec.floorplane.ZatPoint(({x}, {y}))), false);
            pawn.A_SetAngle({yaw});
            pawn.A_SetPitch({pitch});
            let handler = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
            handler.Enabled[0] = {str(beam).lower()};
        }}
        if (level.time == 12)
        {{
            let it = ThinkerIterator.Create("SDVKLocalFlashlightBeam", Thinker.STAT_DLIGHT);
            let lamp = Actor(it.Next());
            if (lamp) Console.Printf("ENTRYWAY_MOUNT %.6f %.6f %.6f", lamp.Pos.X, lamp.Pos.Y, lamp.Pos.Z);
            level.SetFrozen(true);
        }}
    }}
}}
''')
    cfg = folder / "capture.ini"
    cfg.write_text("[GlobalSettings]\nvk_rayquery=false\nvid_fullscreen=false\n")
    files = [pack / "addons" / name for name in ("DoomII-NormalPBR.pk3", "DoomII-SpritePBR.pk3",
                                                 "Local-Flashlight.pk3", "DoomII-Emitter-Lighting.pk3")]
    prefix = folder / "frame"
    cache = folder / "cache"
    cache.mkdir()
    width, height = map(str, SIZE)
    args = [exe, "-iwad", pack / "doom2.wad", "-file", *files, fixture, "-noautoload", "-noautoexec",
            "-stdout", "-nostartup", "-nosound", "-nojoy", "-nomonsters", "-rngseed", "2002",
            "-window", "-width", width, "-height", height, "-config", cfg, "-savedir", folder,
            "-sdvkobserve", prefix, "-sdvkobservecache", cache, "-sdvkobservewarmup", "30",
            "-sdvkobserveframes", "1", "-sdvkobservequit",
            "+vid_setsize", width, height, "+vid_rendermode", "4", "+gl_raytrace", "false",
            "+gl_levelmesh", "false", "+lm_dynlights", "false", "+gl_lights", "true",
            "+gl_light_shadows", "0", "+gl_ubershaders", "false", "+gl_ssao", "0", "+gl_precache", "false",
            "+cl_capfps", "true", "+vid_activeinbackground", "true", "+i_pauseinbackground", "false",
            "+use_mouse", "false", "+vid_vsync", "false", "+gl_bloom", "false", "+screenblocks", "12",
            "+r_drawplayersprites", "false", "+crosshair", "0", "+con_notifylines", "0", "+gl_multisample", "4",
            "+fov", "90", "+gl_shadow_puppets", "0", "+gl_emitter_lighting", "true", "+gl_emitter_ambient", "0",
            "+gl_emitter_ambient_specular", ".5", "+gl_emitter_intensity", "1.225", "+gl_world_relief", "true",
            "+gl_sprite_lighting_relief", "true", "+sdvk_fl_offset_x", ".9", "+sdvk_fl_offset_z", "11.7",
            "+sdvk_fl_aim_pitch", "-7.875", "+sdvk_fl_range", "768", "+sdvk_fl_horizontal", "50.225",
            "+sdvk_fl_vertical", "45.325", "+gl_flashlight_map_shadows", str(shadows).lower(), "+map", "MAP01"]
    # Leave the side offset unset in a fresh profile to test the installed add-on's default.
    if centered:
        args.extend(["+sdvk_fl_offset_y", "0"])
    log = folder / "engine.log"
    with log.open("wb") as stream:
        subprocess.run(list(map(str, args)), cwd=exe.parent, stdout=stream, stderr=subprocess.STDOUT,
                       timeout=120, check=True)
    messages = log.read_text(errors="replace")
    require("Unknown command" not in messages, f"Unsupported setting in {log}")
    source = re.search(r"ENTRYWAY_MOUNT ([-.\d]+) ([-.\d]+) ([-.\d]+)", messages)
    report = json.loads(prefix.with_suffix(".renderer.json").read_text())
    frame, = [row["data"] for row in report["records"] if row["kind"] == "frame"]
    require(report["build"]["backend"] == "vulkan" and frame["map"] == "MAP01" and
            frame["camera"]["position"][:2] == [x, y] and frame["stage_b"]["requested"] and
            bool(frame["relief_flashlight_lights"]) == beam and bool(source) == beam, f"Wrong capture in {folder}")
    with Image.open(prefix.with_suffix(".png")) as image:
        return np.asarray(image.convert("RGB"), dtype=np.int16), frame["camera"], (
            tuple(map(float, source.groups())) if source else None)


def measure(pack, exe, root, pose):
    fill, _, _ = capture(pack, exe, root / "fill", pose, False, True, False)
    changed = {}
    for name in ("centered", "default"):
        centered = name == "centered"
        clear, camera, source = capture(pack, exe, root / f"{name}-off", pose, True, False, centered)
        shadowed, next_camera, next_source = capture(pack, exe, root / f"{name}-on", pose, True, True, centered)
        require(camera == next_camera and source == next_source, "Lamp or camera moved between exposures")
        delta = np.max(clear - shadowed, axis=2)
        changed[name] = int(np.sum(delta > 16))
        if centered:
            continue
        blocked, lit = receivers("entryway", camera, source, clear, fill)
        for label, mask, expected in (("blocked floor", blocked, fill), ("exposed floor", lit, clear)):
            correct = np.max(abs(shadowed - expected), axis=2) <= 3
            require(mask.sum() > 200 and correct[mask].mean() >= .99,
                    f"{root.name} {label}: {np.sum(mask & correct)}/{mask.sum()} correct")
    require(changed["default"] > 3000 and changed["default"] > 5 * changed["centered"],
            f"{root.name}: insufficient visible shadow with the installed mount: {changed}")
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="New capture directory")
    args = parser.parse_args()
    pack, out = args.pack.resolve(), args.out.resolve()
    exe = (args.exe or pack / "runtime/vkdoom.exe").resolve()
    for name, pose in POSES.items():
        print(name, measure(pack, exe, out / name, pose), flush=True)


if __name__ == "__main__":
    main()
