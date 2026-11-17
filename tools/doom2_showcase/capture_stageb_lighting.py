"""Capture matched native Vulkan views of the optional Stage B lighting mode."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from math import isclose
from pathlib import Path
import re
from statistics import median, quantiles
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from PIL import Image, ImageChops, ImageDraw, ImageStat

from capture_relief import fixed_pose, require, sha256
from dbp50_effective import IWAD_SHA256
from stageb_lighting import ENTRYWAY, FIXTURE_EMITTERS, LABELS, build


SIZE = (640, 480)
WARMUP = 28
FRAMES = 6
TIMING_SIZE = (1280, 960)
TIMING_WARMUP = 120
TIMING_FRAMES = 120

# Each setting is (mode enabled, legacy ambient fraction, emitter intensity, flashlight on).
LEGACY = (False, 0, 1, False)
EMITTERS = (True, 0, 1, False)
MUTED = (True, 0, 0, False)
FILL = (True, 0.35, 1, False)
BEAM = (True, 0, 1, True)

CASES = {
    "SBINDR": {"legacy": LEGACY, "emitters": EMITTERS, "without-relief": EMITTERS, "muted": MUTED},
    "SBOUT": {"legacy": LEGACY, "emitters": EMITTERS, "muted": MUTED},
    "SBDARK": {"legacy": LEGACY, "sealed": EMITTERS, "sealed-without-relief": EMITTERS,
               "legacy-fill": FILL, "fill-without-relief": FILL, "flashlight": BEAM},
    "MAP01": {"legacy": LEGACY, "emitters": EMITTERS, "legacy-fill": FILL, "original": LEGACY},
}
DEFAULT_CASES = tuple(CASES)

# Pose (x, y, yaw, pitch), selected anchor (kind, x, y), and visible material.
STOCK_VIEWS = {
    "MAP01-corridor": ((381, 1110, 90, -14), (1, 328, 1183), "TEKGREN5", "Entryway corridor"),
    "MAP02-lamp": ((1817, 1082, 180, -12), (1, 1760, 1056), "FLAT2", "Underhalls lamps"),
    "MAP02-yard": ((1312, 664, 0, 11), (2, 1248, 700), "GRASS2", "Underhalls courtyard"),
}
for case in STOCK_VIEWS:
    CASES[case] = {"legacy": LEGACY, "emitters": EMITTERS, "muted": MUTED}

TARGETS = {
    "SBINDR": {"CEMENT7", "FLOOR5_4", "BRICK7"},
    "SBOUT": {"BRICK7", "FLOOR3_3"},
    "SBDARK": {"CEMENT7", "FLOOR5_4"},
    "MAP01": {"FLOOR0_1"},
}


def view_input(path, flashlight, stock_view=None, freeze=False):
    pose = 'players[0].mo.A_SetPitch(level.MapName == "MAP01" ? 18 : level.MapName == "SBOUT" ? -6 : 9);'
    if stock_view is not None:
        x, y, yaw, pitch = stock_view[0]
        pose = f'''let sector = level.PointInSector(({x}, {y}));
        players[0].mo.SetOrigin(({x}, {y}, sector.floorplane.ZatPoint(({x}, {y}))), false);
        players[0].mo.A_SetAngle({yaw});
        players[0].mo.A_SetPitch({pitch});'''
    script = '''version "4.10"
class StageBViewInput : EventHandler
{
    override void WorldTick()
    {
        if (level.time != 2 || players[0].mo == null) return;
        POSE
        let lamp = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
        if (lamp != null) lamp.Enabled[0] = LAMP;
        FREEZE
    }
}
'''.replace("POSE", pose).replace("LAMP", "true" if flashlight else "false").replace(
        "FREEZE", "level.SetFrozen(true);" if freeze else "")
    with ZipFile(path, "w") as archive:
        archive.writestr(ZipInfo("MAPINFO"), 'GameInfo { AddEventHandlers = "StageBViewInput" }\n',
                         compress_type=ZIP_DEFLATED)
        archive.writestr(ZipInfo("ZSCRIPT"), script, compress_type=ZIP_DEFLATED)


def capture(args, folder, case, controls, authoring, input_file, commit, relief=True):
    folder.mkdir(parents=True)
    ini = folder / "clean.ini"
    ini.write_text("[GlobalSettings]\nvk_rayquery=false\nvid_fullscreen=false\n", encoding="ascii")
    prefix = folder / "frame"
    enabled, ambient, intensity, flashlight = controls
    stock_view = STOCK_VIEWS.get(case)
    map_name = case.split("-", 1)[0]
    frames_requested = args.frames if args.timing else FRAMES
    width, height = map(str, args.size)
    sources = [authoring] if authoring is not None else []
    argv = [str(args.exe), "-iwad", str(args.iwad), "-file", str(args.materials), str(args.flashlight),
            *map(str, sources), str(input_file), "-stdout", "-nostartup", "-noautoload", "-noautoexec",
            "-nosound", "-nojoy", "-nomonsters", "-rngseed", "2002", "-config", str(ini), "-savedir", str(folder),
            "-window", "-width", width, "-height", height, "-sdvkobserve", str(prefix),
            "-sdvkobservemode", "timing" if args.timing else "state",
            "-sdvkobservewarmup", str(TIMING_WARMUP if args.timing else WARMUP), "-sdvkobserveframes", str(frames_requested),
            "-sdvkobservegpu", "-sdvkobservequit", "+vid_rendermode", "4", "+vid_setsize", width, height,
            "+gl_levelmesh", "false", "+gl_ubershaders", "false", "+lm_dynlights", "false", "+gl_light_shadows", "0",
            "+gl_lights", "true", "+gl_lightprobe", "true", "+gl_ssao", "0", "+gl_bloom", "false",
            "+gl_tonemap", "0", "+gl_multisample", "0", "+cl_capfps", str(not args.timing).lower(),
            "+vid_vsync", "false", "+vid_maxfps", "0", "+gl_precache", "true",
            "+r_drawplayersprites", "false", "+screenblocks", "12", "+fov", "90", "+crosshair", "0",
            "+use_mouse", "false", "+con_notifylines", "0", "+show_messages", "false",
            "+screenshot_type", "png", "+screenshot_quiet", "true", "+gl_world_relief", str(relief).lower(),
            "+gl_world_relief_depth", "5", "+gl_world_relief_orientation", "5", "+gl_world_relief_exaggeration", "1.25",
            "+gl_emitter_lighting", str(enabled).lower(), "+gl_emitter_ambient", str(ambient),
            "+gl_emitter_ambient_specular", str(ambient),
            "+gl_emitter_intensity", str(intensity), "+map", map_name]
    with (folder / "engine.log").open("wb") as log:
        subprocess.run(argv, cwd=args.exe.parent, stdout=log, stderr=subprocess.STDOUT,
                       timeout=60, check=True)
    require("Unknown command" not in (folder / "engine.log").read_text(encoding="utf-8", errors="replace"),
            f"Unsupported native capture setting in {folder}")
    raw = json.loads(prefix.with_suffix(".renderer.json").read_text(encoding="utf-8"))
    device = raw["build"]
    require(raw["status"] == "COLLECTED_PENDING_VALIDATION" and raw["dropped_records"] == 0
            and (args.timing or raw["screenshot"]["available"]) and device["backend"] == "vulkan"
            and device["commit"] == commit and not device["vulkan"]["ray_query_enabled"],
            f"Incomplete native Vulkan capture in {folder}: {raw['error']}")
    frames = [row["data"] for row in raw["records"] if row["kind"] == "frame"]
    require(len(frames) == frames_requested and all(
        frame["map"] == map_name and frame["hardware_renderer"] and (frame["width"], frame["height"]) == tuple(args.size)
        and frame["walls"] > 0 and frame["flats"] > 0
        and (args.timing or frame["relief_flashlight_lights"] == int(flashlight))
        and not frame["settings"]["gl_ubershaders"] and not frame["settings"]["gl_levelmesh"]
        and frame["stage_b"]["requested"] == enabled and isclose(frame["stage_b"]["ambient"], ambient, abs_tol=1e-5)
        and isclose(frame["stage_b"]["ambient_specular"], ambient, abs_tol=1e-5)
        and isclose(frame["stage_b"]["intensity"], intensity, abs_tol=1e-5)
        and frame["settings"]["gl_light_shadows"] == 0 for frame in frames),
        f"Wrong native view or flashlight state in {folder}")
    pose = fixed_pose(frames[0])
    require(all(fixed_pose(frame) == pose for frame in frames), f"Camera moved in {folder}")
    if stock_view is not None:
        x, y, yaw, pitch = stock_view[0]
        require(pose["position"][:2] == [x, y] and (pose["angles"][0] - yaw) % 360 == 0
                and pose["angles"][1] == pitch, f"Wrong stock camera in {folder}")
    timing = {}
    for row in raw["records"]:
        data = row["data"]
        if row["kind"] == "timing" and data.get("clock") == "gpu":
            timing.setdefault(data["name"], []).append(data["milliseconds"])
    if args.timing:
        require(raw["availability"]["gpu_timing"]["available"] and "scene.immediate" in timing,
                f"Named GPU timing unavailable in {folder}")
        intervals = [frame["visual_time"]["delta_seconds"] * 1000 for frame in frames
                     if frame["visual_time"]["delta_valid"] and not frame["visual_time"]["clamped"]]
        require(len(intervals) >= len(frames) * 0.95, f"Too few uninterrupted main-frame intervals in {folder}")
        return None, {"argv": argv, "camera": pose, "settings": frames[0]["settings"], "build": device,
                      "frame_interval_ms": percentiles(intervals),
                      "cpu_render_view_ms": percentiles([frame["cpu_render_view_ms"] for frame in frames]),
                      "gpu_named_group_ms": {name: percentiles(samples) for name, samples in timing.items()},
                      "max_shadow_rows": max(frame["shadow_selected"] for frame in frames)}

    targets = {stock_view[2]} if stock_view is not None else TARGETS[case]
    materials = [row["data"] for row in raw["records"] if row["kind"] == "material"
                 and row["data"].get("name") in targets]
    require(any(row["height_texture_index"] >= 0 and row["world_relief_exaggeration"] == (1.25 if relief else 0)
                and row["stage_b_receiver"] == enabled
                for row in materials), f"No target relief material was submitted in {folder}")
    light_records = [row["data"] for row in raw["records"] if row["kind"] == "shadow"]
    selected = {record["light"]["semantic_key"]: record["light"]["stage_b_kind"]
                for record in light_records if record.get("decision") == "selected"
                and record["light"].get("stage_b_kind", 0) > 0}
    selected_counts = Counter(selected.values())
    if stock_view is not None:
        anchors = {(light["stage_b_kind"], *light["position"][:2]) for record in light_records
                   if record.get("decision") == "selected" and (light := record["light"])["stage_b_kind"] > 0}
        matches = stock_view[1] in anchors if enabled else not anchors
    else:
        authored = ENTRYWAY if map_name == "MAP01" else FIXTURE_EMITTERS[map_name]
        expected = Counter(2 if getattr(emitter, "direction", None) is not None else 1
                           for emitter in authored) if enabled else Counter()
        matches = selected_counts == expected
        if map_name == "MAP01" and enabled:
            matches = (len(selected) == frames[-1]["shadow_selected"] == min(48, len(authored))
                       and all(0 < selected_counts[kind] <= count for kind, count in expected.items()))
    require(matches, f"Wrong native point/directional selection in {folder}: {dict(selected_counts)}")
    screenshot = prefix.with_suffix(".png")
    with Image.open(screenshot) as source:
        image = source.convert("RGB")
    report = {"argv": argv, "camera": pose, "settings": frames[0]["settings"], "build": device,
              "lights": {key: frames[-1][key] for key in ("active_lights", "spot_lights", "relief_flashlight_lights")},
              "selected_emitters": {"point": selected_counts[1], "directional": selected_counts[2]},
              "materials": sorted({row["name"] for row in materials}),
              "mean_rgb": ImageStat.Stat(image).mean,
              "median_cpu_render_view_ms": median(frame["cpu_render_view_ms"] for frame in frames),
              "median_gpu_named_group_ms": {key: median(values) for key, values in timing.items()},
              "screenshot": screenshot.relative_to(args.out).as_posix(), "level_tic": frames[-1]["level_tic"],
              "simulation_frozen": case == "MAP01"}
    return image, report


def percentiles(samples):
    p95 = quantiles(samples, n=20, method="inclusive")[-1] if len(samples) > 1 else samples[0]
    return {"samples": len(samples), "median": median(samples), "p95": p95}


def differences(first, second):
    red, green, blue = ImageChops.difference(first, second).split()
    magnitude = ImageChops.lighter(ImageChops.lighter(red, green), blue).histogram()
    return {"pixels_changed": first.width * first.height - magnitude[0], "pixels_over_2": sum(magnitude[3:]),
            "max_channel_delta": max(index for index, count in enumerate(magnitude) if count)}


def compare(out, case, captures, *, timing=False):
    reference = captures["legacy"][1]
    require(all(all(shot[1][key] == reference[key] for key in ("camera", "settings", "build"))
                for shot in captures.values()), f"Hardware or camera conditions drifted in {case}")
    if timing:
        active_name = "sealed" if case == "SBDARK" else "emitters"
        require(reference["max_shadow_rows"] == 0 and captures[active_name][1]["max_shadow_rows"] > 0,
                f"Wrong Stage B shadow rows during {case} timing")
        return {}
    legacy = captures["legacy"][0]
    width, height = legacy.size
    report = {name: differences(legacy, shot[0]) for name, shot in captures.items() if name != "legacy"}
    if case == "SBDARK":
        sealed, fill, beam = (captures[name][0] for name in ("sealed", "legacy-fill", "flashlight"))
        require(sealed.getbbox() is None, "An emitter behind the wall or legacy ambient lit the sealed room")
        require(captures["sealed-without-relief"][0].getbbox() is None,
                "Zero fill must stay completely black across structural relief settings")
        require(0 < sum(ImageStat.Stat(fill).mean) < sum(ImageStat.Stat(legacy).mean),
                "Fractional ambient did not land between zero and legacy")
        fill_delta = differences(captures["fill-without-relief"][0], fill)
        require(fill_delta["pixels_over_2"] > 100,
                "Retained ambient fill did not reveal wall or floor relief in the sealed room")
        report["fill_relief_vs_flat"] = fill_delta
        beam_delta = differences(sealed, beam)
        require(1000 < beam_delta["pixels_over_2"] < width * height * 0.90,
                "Independent flashlight did not produce a bounded spot in the sealed room")
        report["flashlight_vs_sealed"] = beam_delta
    else:
        require(report["emitters"]["pixels_over_2"] > 1000, f"Stage B did not change visible lighting in {case}")
        if "muted" in captures:
            active_delta = differences(captures["muted"][0], captures["emitters"][0])
            require(active_delta["pixels_over_2"] > 1000, f"Authored intensity had no visible effect in {case}")
            report["emitters_vs_muted"] = active_delta
        if case in ("SBOUT", "MAP02-yard"):
            # The lower foreground is in the courtyard sector, which contains
            # the directional emitter. The point emitter sits in the raised alcove.
            box = (width // 4, height * 3 // 4, width * 3 // 4, height)
            active = captures["emitters"][0].crop(box)
            muted = captures["muted"][0].crop(box)
            require(sum(ImageStat.Stat(active).mean) - sum(ImageStat.Stat(muted).mean) > 5,
                    "Directional lighting did not reach the foreground courtyard tiles")
        if case == "SBINDR":
            relief_delta = differences(captures["without-relief"][0], captures["emitters"][0])
            require(relief_delta["pixels_over_2"] > 1000, "Authored point lamps did not respond to wall and floor height")
            report["emitter_relief_vs_flat"] = relief_delta
        if "original" in captures:
            # Legacy light animation can vary slightly between the two render runs.
            require(report["original"]["max_channel_delta"] <= 1,
                    "Installing the emitter addon changed MAP01 beyond one RGB code when Stage B was off")

    sheet = Image.new("RGB", (width * len(captures), height + 30), "#15191f")
    labels = ImageDraw.Draw(sheet)
    label = STOCK_VIEWS[case][3] if case in STOCK_VIEWS else LABELS[case]
    for index, (name, (image, _)) in enumerate(captures.items()):
        offset = index * width
        labels.text((offset + 8, 8), f"{label} / {name}", fill="white")
        sheet.paste(image, (offset, 30))
    sheet.save(out / f"{case}-comparison.png")
    return report


def run(args):
    require(all(path.is_file() for path in (args.exe, args.iwad, args.materials, args.flashlight)),
            "Missing Stage B capture input")
    require(sha256(args.iwad) == IWAD_SHA256, "Expected the supported Doom II IWAD")
    cases = args.case or DEFAULT_CASES
    args.out.mkdir(parents=True)
    authoring = args.out / "emitters-without-overlay.pk3"
    build(authoring, playable=False, iwad=args.iwad if set(cases) & STOCK_VIEWS.keys() else None)
    inputs = {}
    for case in cases:
        # Entryway's pickups animate next to the measured surfaces. Pin their
        # simulation phase for the pixel comparison, and leave timing live.
        freeze = case == "MAP01" and not args.timing
        for _, _, _, beam in CASES[case].values():
            key = case, beam
            if key not in inputs:
                path = args.out / f"view-input-{case}-{int(beam)}.pk3"
                view_input(path, beam, STOCK_VIEWS.get(case), freeze)
                inputs[key] = path
    version = subprocess.check_output([args.exe, "--version"], cwd=args.exe.parent, encoding="utf-8", timeout=20)
    identity = re.search(r"^Commit: ([0-9a-f]{40})$", version, re.M)
    require(identity is not None, "Missing native build identity")
    report = {"status": "incomplete", "version": version, "started_utc": datetime.now(timezone.utc).isoformat(),
              "mode": "timing" if args.timing else "state", "size": args.size,
              "warmup_frames": TIMING_WARMUP if args.timing else WARMUP,
              "retained_frames": args.frames if args.timing else FRAMES, "cases": {},
              "sources": {name: sha256(Path(__file__).with_name(name)) for name in
                          ("capture_stageb_lighting.py", "stageb_lighting.py", "stageb_layout.py", "capture_relief.py")},
              "inputs": {str(path): sha256(path) for path in (args.exe, args.iwad, args.materials, args.flashlight)},
              "runtime_pk3": {path.name: sha256(path) for path in sorted(args.exe.parent.glob("*.pk3"))}}
    try:
        for case in cases:
            shots = {name: capture(args, args.out / case / name, case, controls,
                                   None if name == "original" else authoring,
                                   inputs[case, controls[-1]], identity.group(1), relief=not name.endswith("without-relief"))
                     for name, controls in CASES[case].items()
                     if not args.timing or name in ("legacy", "emitters", "sealed")}
            report["cases"][case] = {"comparisons": compare(args.out, case, shots, timing=args.timing),
                                         "captures": {name: shot[1] for name, shot in shots.items()}}
            print(f"{case}: {', '.join(shots)}", flush=True)
        report["status"] = "captured_pending_owner_review"
    except (KeyError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
        raise
    finally:
        report["files"] = {path.relative_to(args.out).as_posix(): sha256(path)
                           for path in sorted(args.out.rglob("*")) if path.is_file()}
        manifest = args.out / "manifest.json"
        manifest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (args.out / "manifest.sha256").write_text(f"{sha256(manifest)}  manifest.json\n", encoding="ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("exe", "iwad", "materials", "flashlight", "out"):
        parser.add_argument(f"--{name}", type=lambda path: Path(path).resolve(), required=True)
    parser.add_argument("--case", choices=CASES, action="append", help="capture only the named maps")
    parser.add_argument("--timing", action="store_true", help="collect uncapped legacy and emitter timing instead of screenshots")
    parser.add_argument("--size", type=int, nargs=2, metavar=("WIDTH", "HEIGHT"),
                        help="render size, default 640x480 for screenshots or 1280x960 for timing")
    parser.add_argument("--frames", type=int, default=TIMING_FRAMES, help="retained frames for --timing (default 120)")
    args = parser.parse_args()
    args.size = args.size or (TIMING_SIZE if args.timing else SIZE)
    if min(args.size) < 1 or not 2 <= args.frames <= 4096:
        parser.error("expected positive dimensions and 2 to 4096 timing frames")
    try:
        run(args)
    except (KeyError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
