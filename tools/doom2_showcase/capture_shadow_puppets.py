"""Compare the shadow puppet modes on matched native Vulkan game views."""

import argparse
import json
from math import cos, isclose, radians, sin
from pathlib import Path
import re
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from PIL import Image, ImageChops, ImageDraw

from capture_relief import fixed_pose, require, sha256
from capture_stageb_lighting import differences, percentiles
from capture_shadow_silhouette import reference_room, verify_frame_change, verify_projection
from gallery import wad
from shadow_puppets import MAP_NAME, PACK_NAME


MODES = ("Off", "Stencil", "Depth")
# Eye pose, simulation tic for the moving Imp's pose, flashlight state.
VIEWS = {
    "spawn": ((-8, -66, 90, 0), 2, True),
    "stationary": ((42, -54, 132, 3), 2, True),
    "moving": ((-65, -57, 54, 1), 25, True),
    "contact": ((-5, 0, 135, 13), 2, True),
    "no-flashlight": ((42, -54, 132, 3), 2, False),
}
# Fixed actor frame, yaw, native sprite lump and expected horizontal flip.
SILHOUETTE_POSES = {
    "silhouette-a": ("A", 270, "TROOA1", False),
    "silhouette-g": ("G", 270, "TROOG1", False),
    "silhouette-mirror": ("G", 315, "TROOG2G8", True),
    "landing-raised": ("G", 263, "TROOG2G8", True),
}
VIEWS.update({name: ((-16, -94, 90, 0), 2, True) for name in SILHOUETTE_POSES})
VIEWS["landing-raised"] = ((-36, -37, 62, 12), 2, True)
DEFAULT_CASES = ("spawn", "stationary", "moving", "no-flashlight", *SILHOUETTE_POSES)
ADDONS = ("DoomII-NormalPBR.pk3", "DoomII-SpritePBR.pk3", "Local-Flashlight.pk3", PACK_NAME)


def write_view(path, case, ambient_only=False):
    (x, y, yaw, pitch), tic, flashlight = VIEWS[case]
    script = '''version "4.10"
class ShadowPuppetCaptureView : EventHandler
{
    override void WorldTick()
    {
        if (level.time == 2 && players[0].mo != null)
        {
            let sector = level.PointInSector((EYE_X, EYE_Y));
            players[0].mo.SetOrigin((EYE_X, EYE_Y, sector.floorplane.ZatPoint((EYE_X, EYE_Y))), false);
            players[0].mo.A_SetAngle(YAW);
            players[0].mo.A_SetPitch(PITCH);
            let lamp = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
            if (lamp != null) FLASHLIGHT;
        }
        if (level.time == SAMPLE_TIC)
        {
            let room = SDVKShadowLabHandler(EventHandler.Find("SDVKShadowLabHandler"));
            if (room == null || room.Walker == null) return;
            let actor = room.Walker;
            CAPTURE_ACTOR
            Console.Printf("PUPPET_CAPTURE walker %.4f %.4f %.4f yaw %.4f",
                actor.Pos.X, actor.Pos.Y, actor.Pos.Z, actor.Angle);
            room.Walker = null;
            level.SetFrozen(true);
        }
    }
}
'''
    if case in SILHOUETTE_POSES:
        frame, actor_yaw, _, _ = SILHOUETTE_POSES[case]
        script += f'''
class ShadowPuppetCaptureImp : DoomImp
{{
    States {{ CapturePose: TROO {frame} -1; Stop; }}
}}
'''
        replace_actors = f'''
            room.Walker = null;
            let actors = ThinkerIterator.Create("SDVKShadowLabImp");
            Actor original;
            while ((original = Actor(actors.Next())) != null) original.Destroy();
            actor = Actor.Spawn("ShadowPuppetCaptureImp", (0, 6, 0), NO_REPLACE);
            actor.A_SetAngle({actor_yaw});
            actor.SetStateLabel("CapturePose");'''
    else:
        replace_actors = ""
    beam_action = "lamp.Enabled[0] = true" if flashlight and not ambient_only else "lamp.ClearPlayer(0)"
    for name, value in {"EYE_X": x, "EYE_Y": y, "YAW": yaw, "PITCH": pitch,
                        "SAMPLE_TIC": tic, "FLASHLIGHT": beam_action, "CAPTURE_ACTOR": replace_actors}.items():
        script = script.replace(name, str(value))
    with ZipFile(path, "w") as archive:
        if case == "landing-raised":
            archive.writestr(ZipInfo(f"maps/{MAP_NAME}.wad"), wad(MAP_NAME, reference_room(True).text()),
                             compress_type=ZIP_DEFLATED)
        archive.writestr(ZipInfo("MAPINFO"), 'GameInfo { AddEventHandlers = "ShadowPuppetCaptureView" }\n',
                         compress_type=ZIP_DEFLATED)
        archive.writestr(ZipInfo("ZSCRIPT"), script, compress_type=ZIP_DEFLATED)


def capture(args, case, mode, fixture, exe, iwad, addons, ambient_only=False):
    pose, tic, flashlight = VIEWS[case]
    flashlight = flashlight and not ambient_only
    folder = args.out / case / ("ambient" if ambient_only else MODES[mode].lower())
    folder.mkdir(parents=True)
    ini = folder / "clean.ini"
    ini.write_text("[GlobalSettings]\nvk_rayquery=false\nvid_fullscreen=false\n", encoding="ascii")
    prefix = folder / "frame"
    width, height = map(str, args.size)
    samples = args.samples if args.timing else 1
    argv = [str(exe), "-iwad", str(iwad), "-file", *map(str, addons), str(fixture),
            "-stdout", "-nostartup", "-noautoload", "-noautoexec", "-nosound", "-nojoy", "-rngseed", "2002",
            "-config", str(ini), "-savedir", str(folder), "-window", "-width", width, "-height", height,
            "-sdvkobserve", str(prefix), "-sdvkobservemode", "timing" if args.timing else "state",
            "-sdvkobservewarmup", "120" if args.timing else "42", "-sdvkobserveframes", str(samples),
            "-sdvkobservegpu", "-sdvkobservequit", "+vid_rendermode", "4", "+vid_setsize", width, height,
            "+gl_levelmesh", "false", "+gl_ubershaders", "false", "+gl_raytrace", "false", "+lm_dynlights", "false",
            "+gl_light_shadows", "0", "+gl_multisample", str(args.msaa), "+gl_lights", "true", "+gl_ssao", "0",
            "+gl_spritelight", "2", "+gl_light_sprites", "true", "+r_actorspriteshadow", "0",
            "+gl_bloom", "false", "+gl_emitter_lighting", "false", "+gl_world_relief", "true",
            "+gl_sprite_lighting_relief", "true", "+gl_shadow_puppets", str(mode),
            "+gl_shadow_puppet_softness", str(args.depth_softness),
            "+gl_precache", "true", "+r_drawplayersprites", "false", "+screenblocks", "12", "+fov", "90",
            "+crosshair", "0", "+con_notifylines", "0", "+show_messages", "false", "+use_mouse", "false",
            "+cl_capfps", str(not args.timing).lower(), "+vid_vsync", "false", "+vid_maxfps", "0",
            "+screenshot_type", "png", "+screenshot_quiet", "true", "+map", MAP_NAME]
    log = folder / "engine.log"
    if case in SILHOUETTE_POSES:
        argv += ["+sdvk_fl_offset_y", "16", "+sdvk_fl_range", "720", "+sdvk_fl_horizontal", "84",
                 "+sdvk_fl_vertical", "84", "+gl_spriteclip", "0", "+sdvk_fl_offset_x", "16",
                 "+sdvk_fl_offset_z", "12" if case == "landing-raised" else "-12"]
    with log.open("wb") as stream:
        subprocess.run(argv, cwd=exe.parent, stdout=stream, stderr=subprocess.STDOUT, timeout=60, check=True)
    messages = log.read_text(encoding="utf-8", errors="replace")
    require("Unknown command" not in messages, f"Unsupported setting in {log}")
    walker = re.findall(r"PUPPET_CAPTURE walker (-?[\d.]+) (-?[\d.]+) (-?[\d.]+) yaw (-?[\d.]+)", messages)
    require(len(walker) == 1, f"Missing or repeated moving Imp witness in {log}")
    walker_pose = [float(value) for value in walker[0]]
    if case == "moving":
        require(walker_pose[:2] != [37, 66], f"Moving Imp never left its spawn in {log}")

    raw = json.loads(prefix.with_suffix(".renderer.json").read_text(encoding="utf-8"))
    build = raw["build"]
    require(raw["status"] == "COLLECTED_PENDING_VALIDATION" and raw["dropped_records"] == 0
            and build["backend"] == "vulkan" and (args.timing or raw["screenshot"]["available"]),
            f"Incomplete Vulkan capture {folder}: {raw['error']}")
    frames = [row["data"] for row in raw["records"] if row["kind"] == "frame"]
    require(len(frames) == samples, f"Wrong renderer sample count in {folder}")
    x, y, yaw, pitch = pose
    camera = fixed_pose(frames[0])
    require(camera["position"][:2] == [x, y] and (camera["angles"][0] - yaw) % 360 == 0
            and camera["angles"][1] == pitch, f"Wrong camera pose in {folder}")
    active = mode if flashlight else 0
    require(all(
        frame["map"] == MAP_NAME and frame["hardware_renderer"] and frame["level_tic"] >= tic
        and frame["walls"] > 0 and frame["flats"] > 0 and fixed_pose(frame) == camera
        and (frame["width"], frame["height"]) == tuple(args.size)
        and frame["settings"]["gl_multisample"] == args.msaa
        and frame["shadow_puppets"]["requested"] == mode and frame["shadow_puppets"]["active"] == active
        and isclose(frame["shadow_puppets"]["depth_softness"], args.depth_softness, abs_tol=1e-6)
        and (args.timing or frame["relief_flashlight_lights"] == int(flashlight)) for frame in frames),
        f"Wrong receiver, beam, or shadow mode in {folder}")
    report = {"argv": argv, "build": build, "camera": camera, "walker_pose": walker_pose,
              "scene": frames[-1]["shadow_puppets"], "level_tic": frames[-1]["level_tic"],
              "cpu_render_view_ms": percentiles([frame["cpu_render_view_ms"] for frame in frames])}
    if case in SILHOUETTE_POSES:
        _, actor_yaw, texture, mirror = SILHOUETTE_POSES[case]
        sources = {(row["data"]["material"], row["data"]["surface"]["uv_mirror_x"])
                   for row in raw["records"] if row["kind"] == "sprite-basis"}
        require(sources == {(texture, mirror)} and walker_pose == [0, 6, 0, actor_yaw],
                f"Unexpected submitted actor or texture for {case}: {sources}, {walker_pose}")
        report["source_sprite"] = texture
        report["source_mirrored"] = mirror
        report["sloped_receiver"] = case == "landing-raised"
        report["light_sprite"] = "TROOG1" if case == "landing-raised" else texture
        report["light_sprite_mirrored"] = False if case == "landing-raised" else mirror
        if flashlight:
            sources = [row["data"]["light"] for row in raw["records"] if row["kind"] == "light-query"
                       and row["data"].get("light", {}).get("spot")]
            heading = radians(yaw)
            expected = (x + 16 * (cos(heading) + sin(heading)), y + 16 * (sin(heading) - cos(heading)),
                        camera["position"][2] + (12 if case == "landing-raised" else -12))
            require(sources and all(all(isclose(a, b, abs_tol=1e-4) for a, b in zip(light["position"], expected))
                                    for light in sources),
                    f"Unexpected flashlight position in {folder}")
            report["light_origin"] = sources[0]["position"]
    gpu = {}
    for row in raw["records"]:
        if row["kind"] == "timing" and row["data"].get("clock") == "gpu":
            data = row["data"]
            gpu.setdefault(data["name"], []).append(data["milliseconds"])
    report["gpu_named_group_ms"] = {name: percentiles(values) for name, values in gpu.items()}
    if args.timing:
        require("scene.immediate" in gpu, f"Missing named scene GPU timing in {folder}")
        puppet_groups = {name for name in gpu if name.startswith("puppet.")}
        expected = {f"puppet.{MODES[active].lower()}"} if active else set()
        require(puppet_groups == expected, f"Wrong shadow backend GPU timing in {folder}: {puppet_groups}")
        intervals = [1000 * frame["visual_time"]["delta_seconds"] for frame in frames
                     if frame["visual_time"]["delta_valid"] and not frame["visual_time"]["clamped"]]
        require(len(intervals) >= samples * 0.95, f"Too few uninterrupted frame intervals in {folder}")
        report["frame_interval_ms"] = percentiles(intervals)
        return None, report

    with Image.open(prefix.with_suffix(".png")) as source:
        require(source.size == tuple(args.size), f"Unexpected image dimensions in {folder}")
        image = source.convert("RGB")
    report["screenshot"] = prefix.with_suffix(".png").relative_to(args.out).as_posix()
    return image, report


def compare(out, case, captures):
    base_report = captures[0][1]
    require(all(all(report[key] == base_report[key] for key in ("camera", "walker_pose", "build"))
                for _, report in captures), f"Unmatched hardware or scene pose in {case}")
    if captures[0][0] is None:
        return {}

    images = [image for image, _ in captures]
    width, height = images[0].size
    # Omit the demo's mode overlay from pixel tests. Preserve it in the raw screenshots.
    crop_top = round(height * 0.10)
    matched = [image.crop((0, crop_top, width, height)) for image in images]
    sheet = Image.new("RGB", (width * len(MODES), height - crop_top + 30), "#15191f")
    labels = ImageDraw.Draw(sheet)
    for i, (mode, image) in enumerate(zip(MODES, matched)):
        labels.text((i * width + 8, 8), f"{case} / {mode}", fill="white")
        sheet.paste(image, (i * width, 30))
    sheet.save(out / f"{case}-comparison.png")

    report = {f"{first}-{second}": differences(matched[a], matched[b])
              for first, second, a, b in (("off", "stencil", 0, 1), ("off", "depth", 0, 2),
                                           ("stencil", "depth", 1, 2))}
    for i, mode in enumerate(MODES[1:], 1):
        native_difference = ImageChops.difference(matched[0], matched[i])
        native_difference.save(out / f"{case}-{mode.lower()}-difference.png")
        delta = report[f"off-{mode.lower()}"]
        if VIEWS[case][2]:
            black = Image.new("RGB", matched[0].size)
            darker = differences(black, ImageChops.subtract(matched[0], matched[i]))
            brighter = differences(black, ImageChops.subtract(matched[i], matched[0]))
            require(darker["pixels_over_2"] >= 24, f"{mode} did not visibly dim the {case} flashlight")
            require(brighter["pixels_over_2"] == 0, f"{mode} added light to the matched {case} view")
            delta["darkened_pixels_over_2"] = darker["pixels_over_2"]
            delta["brightened_pixels_over_2"] = brighter["pixels_over_2"]
        else:
            require(delta["max_channel_delta"] <= 1, f"{mode} changed the unlit control beyond one RGB code")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=lambda path: Path(path).resolve(), required=True)
    parser.add_argument("--out", type=lambda path: Path(path).resolve(), required=True)
    parser.add_argument("--case", action="append", choices=VIEWS)
    parser.add_argument("--timing", action="store_true", help="time the stationary view instead of taking screenshots")
    parser.add_argument("--size", type=int, nargs=2, metavar=("WIDTH", "HEIGHT"))
    parser.add_argument("--samples", type=int, default=120)
    parser.add_argument("--msaa", type=int, choices=(0, 2, 4, 8), default=0,
                        help="scene MSAA sample count, or 0 to disable it")
    parser.add_argument("--depth-softness", type=float, default=1.0,
                        help="Depth edge filter, from 0 for hard edges to 2 for the widest filter")
    args = parser.parse_args()
    args.size = args.size or ((1280, 960) if args.timing else (640, 480))
    cases = tuple(args.case) if args.case else (("stationary",) if args.timing else DEFAULT_CASES)
    if min(args.size) <= 0 or not 2 <= args.samples <= 4096 or (args.timing and cases != ("stationary",)):
        parser.error("expected positive dimensions, 2–4096 timing samples, and only the stationary timing case")
    if not 0.0 <= args.depth_softness <= 2.0:
        parser.error("expected depth softness between 0 and 2")
    exe = args.pack / "runtime" / "vkdoom.exe"
    iwad = args.pack / "doom2.wad"
    addons = [args.pack / "addons" / name for name in ADDONS]
    report = {"status": "incomplete", "size": args.size, "mode": "timing" if args.timing else "state",
              "msaa": args.msaa, "depth_softness": args.depth_softness, "cases": {}}
    try:
        require(all(path.is_file() for path in (exe, iwad, *addons)), f"Missing package inputs under {args.pack}")
        args.out.mkdir(parents=True)
    except (OSError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
    try:
        report["inputs"] = {str(path): sha256(path) for path in (exe, iwad, *addons)}
        report["runtime_pk3"] = {path.name: sha256(path) for path in sorted(exe.parent.glob("*.pk3"))}
        report["capture_source_sha256"] = sha256(Path(__file__))
        report["sprite_projection_source_sha256"] = sha256(Path(__file__).with_name("capture_shadow_silhouette.py"))
        witnesses = {}
        for case in cases:
            fixture = args.out / f"{case}-view.pk3"
            write_view(fixture, case)
            captures = [capture(args, case, mode, fixture, exe, iwad, addons) for mode in range(len(MODES))]
            report["cases"][case] = {"captures": {mode: shot[1] for mode, shot in zip(MODES, captures)},
                                     "comparison": compare(args.out, case, captures)}
            if case in SILHOUETTE_POSES:
                ambient_fixture = args.out / f"{case}-ambient-view.pk3"
                write_view(ambient_fixture, case, ambient_only=True)
                ambient, control = capture(args, case, 0, ambient_fixture, exe, iwad, addons, ambient_only=True)
                report["cases"][case]["ambient"] = control
                metrics, witnesses[case] = verify_projection(iwad, captures, ambient, args.out / case)
                report["cases"][case]["sprite_projection"] = metrics
            print(f"{case} passed", flush=True)
        if "silhouette-a" in witnesses and "silhouette-g" in witnesses:
            report["fixed_position_frame_change"] = verify_frame_change(witnesses["silhouette-a"],
                                                                        witnesses["silhouette-g"])
        report["status"] = "captured_pending_owner_review"
    except (KeyError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
        parser.exit(1, f"{error}\n")
    finally:
        if args.out.is_dir():
            report["files"] = {path.relative_to(args.out).as_posix(): sha256(path)
                               for path in sorted(args.out.rglob("*")) if path.is_file()}
            manifest = args.out / "manifest.json"
            manifest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            (args.out / "manifest.sha256").write_text(f"{sha256(manifest)}  manifest.json\n", encoding="ascii")


if __name__ == "__main__":
    main()
