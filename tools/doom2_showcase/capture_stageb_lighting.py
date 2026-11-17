"""Capture matched native Vulkan views of the optional Stage B lighting mode."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from math import isclose
from pathlib import Path
import re
from statistics import median
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from PIL import Image, ImageChops, ImageDraw, ImageStat

from capture_relief import fixed_pose, require, sha256
from dbp50_effective import IWAD_SHA256
from stageb_lighting import ENTRYWAY, FIXTURE_EMITTERS, LABELS, build


SIZE = (640, 480)
WARMUP = 28
FRAMES = 6

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

TARGETS = {
    "SBINDR": {"CEMENT7", "FLOOR5_4", "BRICK7"},
    "SBOUT": {"BRICK7", "FLOOR3_3"},
    "SBDARK": {"CEMENT7", "FLOOR5_4"},
    "MAP01": {"FLOOR0_1"},
}


def view_input(path, flashlight):
    script = '''version "4.10"
class StageBViewInput : EventHandler
{
    override void WorldTick()
    {
        if (level.time != 2 || players[0].mo == null) return;
        players[0].mo.A_SetPitch(level.MapName == "MAP01" ? 18 : level.MapName == "SBOUT" ? -6 : 9);
        let lamp = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
        if (lamp != null) lamp.Enabled[0] = LAMP;
    }
}
'''.replace("LAMP", "true" if flashlight else "false")
    with ZipFile(path, "w") as archive:
        archive.writestr(ZipInfo("MAPINFO"), 'GameInfo { AddEventHandlers = "StageBViewInput" }\n',
                         compress_type=ZIP_DEFLATED)
        archive.writestr(ZipInfo("ZSCRIPT"), script, compress_type=ZIP_DEFLATED)


def capture(args, folder, map_name, controls, authoring, input_file, commit, relief=True):
    folder.mkdir(parents=True)
    ini = folder / "clean.ini"
    ini.write_text("[GlobalSettings]\nvk_rayquery=false\nvid_fullscreen=false\n", encoding="ascii")
    prefix = folder / "frame"
    enabled, ambient, intensity, flashlight = controls
    phase_capture = map_name == "MAP01"
    frames_requested = 18 if phase_capture else FRAMES
    png_sequence = ["-sdvkobservepngs"] if phase_capture else []
    width, height = map(str, SIZE)
    sources = [authoring] if authoring is not None else []
    argv = [str(args.exe), "-iwad", str(args.iwad), "-file", str(args.materials), str(args.flashlight),
            *map(str, sources), str(input_file), "-stdout", "-nostartup", "-noautoload", "-noautoexec",
            "-nosound", "-nojoy", "-nomonsters", "-rngseed", "2002", "-config", str(ini), "-savedir", str(folder),
            "-window", "-width", width, "-height", height, "-sdvkobserve", str(prefix),
            "-sdvkobservemode", "state", "-sdvkobservewarmup", str(WARMUP), "-sdvkobserveframes", str(frames_requested),
            *png_sequence,
            "-sdvkobservegpu", "-sdvkobservequit", "+vid_rendermode", "4", "+vid_setsize", width, height,
            "+gl_levelmesh", "false", "+gl_ubershaders", "false", "+lm_dynlights", "false", "+gl_light_shadows", "0",
            "+gl_lights", "true", "+gl_lightprobe", "true", "+gl_ssao", "0", "+gl_bloom", "false",
            "+gl_tonemap", "0", "+gl_multisample", "0", "+cl_capfps", "true", "+gl_precache", "true",
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
            and raw["screenshot"]["available"] and device["backend"] == "vulkan"
            and device["commit"] == commit and not device["vulkan"]["ray_query_enabled"],
            f"Incomplete native Vulkan capture in {folder}: {raw['error']}")
    frames = [row["data"] for row in raw["records"] if row["kind"] == "frame"]
    require(len(frames) == frames_requested and all(
        frame["map"] == map_name and frame["hardware_renderer"] and (frame["width"], frame["height"]) == SIZE
        and frame["walls"] > 0 and frame["flats"] > 0 and frame["relief_flashlight_lights"] == int(flashlight)
        and not frame["settings"]["gl_ubershaders"] and not frame["settings"]["gl_levelmesh"]
        and frame["stage_b"]["requested"] == enabled and isclose(frame["stage_b"]["ambient"], ambient, abs_tol=1e-5)
        and isclose(frame["stage_b"]["ambient_specular"], ambient, abs_tol=1e-5)
        and isclose(frame["stage_b"]["intensity"], intensity, abs_tol=1e-5)
        and frame["settings"]["gl_light_shadows"] == 0 for frame in frames),
        f"Wrong native view or flashlight state in {folder}")
    pose = fixed_pose(frames[0])
    require(all(fixed_pose(frame) == pose for frame in frames), f"Camera moved in {folder}")
    materials = [row["data"] for row in raw["records"] if row["kind"] == "material"
                 and row["data"].get("name") in TARGETS[map_name]]
    require(any(row["height_texture_index"] >= 0 and row["world_relief_exaggeration"] == (1.25 if relief else 0)
                and row["stage_b_receiver"] == enabled
                for row in materials), f"No target relief material was submitted in {folder}")
    light_records = [row["data"] for row in raw["records"] if row["kind"] == "shadow"]
    selected = {record["light"]["semantic_key"]: record["light"]["stage_b_kind"]
                for record in light_records if record.get("decision") == "selected"
                and record["light"].get("stage_b_kind", 0) > 0}
    authored = ENTRYWAY if map_name == "MAP01" else FIXTURE_EMITTERS[map_name]
    expected = Counter(2 if getattr(emitter, "direction", None) is not None else 1
                       for emitter in authored) if enabled else Counter()
    selected_counts = Counter(selected.values())
    matches = selected_counts == expected
    if map_name == "MAP01" and enabled:
        matches = (len(selected) == frames[-1]["shadow_selected"] == min(48, len(authored))
                   and all(0 < selected_counts[kind] <= count for kind, count in expected.items()))
    require(matches, f"Wrong native point/directional selection in {folder}: {dict(selected_counts)} vs {dict(expected)}")
    timing = {}
    for row in raw["records"]:
        data = row["data"]
        if row["kind"] == "timing" and data.get("clock") == "gpu":
            timing.setdefault(data["name"], []).append(data["milliseconds"])
    screenshot = prefix.with_suffix(".png")
    with Image.open(screenshot) as source:
        image = source.convert("RGB")
    sequence = {row["data"]["level_tic"]: (folder / row["data"]["image"]).relative_to(args.out).as_posix()
                for row in raw["records"] if row["kind"] == "frame-sequence"}
    require(not phase_capture or len(sequence) > 1, f"Missing phase sequence in {folder}")
    report = {"argv": argv, "camera": pose, "settings": frames[0]["settings"], "build": device,
              "lights": {key: frames[-1][key] for key in ("active_lights", "spot_lights", "relief_flashlight_lights")},
              "selected_emitters": {"point": selected_counts[1], "directional": selected_counts[2]},
              "materials": sorted({row["name"] for row in materials}),
              "mean_rgb": ImageStat.Stat(image).mean,
              "median_cpu_render_view_ms": median(frame["cpu_render_view_ms"] for frame in frames),
              "median_gpu_named_group_ms": {key: median(values) for key, values in timing.items()},
              "screenshot": screenshot.relative_to(args.out).as_posix(), "level_tic": frames[-1]["level_tic"],
              "sequence_by_level_tic": sequence}
    return image, report


def differences(first, second):
    red, green, blue = ImageChops.difference(first, second).split()
    magnitude = ImageChops.lighter(ImageChops.lighter(red, green), blue).histogram()
    return {"pixels_changed": SIZE[0] * SIZE[1] - magnitude[0], "pixels_over_2": sum(magnitude[3:]),
            "max_channel_delta": max(index for index, count in enumerate(magnitude) if count)}


def compare(out, map_name, captures):
    if map_name == "MAP01":
        # MAP01 has animated switches and props alongside the measured surfaces.
        sequences = [set(shot[1]["sequence_by_level_tic"]) for shot in captures.values()]
        shared_tics = set.intersection(*sequences)
        require(shared_tics, "No common MAP01 simulation tic for matched captures")
        tic = max(shared_tics)
        for name, (_, details) in captures.items():
            details["level_tic"] = tic
            details["screenshot"] = details["sequence_by_level_tic"][tic]
            with Image.open(out / details["screenshot"]) as source:
                image = source.convert("RGB")
            details["mean_rgb"] = ImageStat.Stat(image).mean
            captures[name] = (image, details)
    legacy = captures["legacy"][0]
    reference = captures["legacy"][1]
    require(all(all(shot[1][key] == reference[key] for key in ("camera", "settings", "build"))
                for shot in captures.values()), f"Hardware or camera conditions drifted in {map_name}")
    report = {name: differences(legacy, shot[0]) for name, shot in captures.items() if name != "legacy"}
    if map_name == "SBDARK":
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
        require(1000 < beam_delta["pixels_over_2"] < SIZE[0] * SIZE[1] * 0.90,
                "Independent flashlight did not produce a bounded spot in the sealed room")
        report["flashlight_vs_sealed"] = beam_delta
    else:
        require(report["emitters"]["pixels_over_2"] > 1000, f"Stage B did not change visible lighting in {map_name}")
        if "muted" in captures:
            active_delta = differences(captures["muted"][0], captures["emitters"][0])
            require(active_delta["pixels_over_2"] > 1000, f"Authored intensity had no visible effect in {map_name}")
            report["emitters_vs_muted"] = active_delta
        if map_name == "SBOUT":
            # The lower foreground is in the courtyard sector, which contains
            # the directional emitter. The point emitter sits in the raised alcove.
            box = (SIZE[0] // 4, SIZE[1] * 3 // 4, SIZE[0] * 3 // 4, SIZE[1])
            active = captures["emitters"][0].crop(box)
            muted = captures["muted"][0].crop(box)
            require(sum(ImageStat.Stat(active).mean) - sum(ImageStat.Stat(muted).mean) > 5,
                    "Directional lighting did not reach the foreground courtyard tiles")
        if map_name == "SBINDR":
            relief_delta = differences(captures["without-relief"][0], captures["emitters"][0])
            require(relief_delta["pixels_over_2"] > 1000, "Authored point lamps did not respond to wall and floor height")
            report["emitter_relief_vs_flat"] = relief_delta
        if "original" in captures:
            require(report["original"]["pixels_changed"] == 0,
                    "Installing the emitter addon changed MAP01 when Stage B was off")

    sheet = Image.new("RGB", (SIZE[0] * len(captures), SIZE[1] + 30), "#15191f")
    labels = ImageDraw.Draw(sheet)
    for index, (name, (image, _)) in enumerate(captures.items()):
        offset = index * SIZE[0]
        labels.text((offset + 8, 8), f"{LABELS[map_name]} / {name}", fill="white")
        sheet.paste(image, (offset, 30))
    sheet.save(out / f"{map_name}-comparison.png")
    return report


def run(args):
    require(all(path.is_file() for path in (args.exe, args.iwad, args.materials, args.flashlight)),
            "Missing Stage B capture input")
    require(sha256(args.iwad) == IWAD_SHA256, "Expected the supported Doom II IWAD")
    args.out.mkdir(parents=True)
    authoring = args.out / "emitters-without-overlay.pk3"
    build(authoring, playable=False)
    inputs = {beam: args.out / f"view-input-{int(beam)}.pk3" for beam in (False, True)}
    for beam, path in inputs.items():
        view_input(path, beam)
    version = subprocess.check_output([args.exe, "--version"], cwd=args.exe.parent, encoding="utf-8", timeout=20)
    identity = re.search(r"^Commit: ([0-9a-f]{40})$", version, re.M)
    require(identity is not None, "Missing native build identity")
    report = {"status": "incomplete", "version": version, "started_utc": datetime.now(timezone.utc).isoformat(),
              "size": SIZE, "warmup_frames": WARMUP, "retained_frames": FRAMES, "cases": {},
              "sources": {name: sha256(Path(__file__).with_name(name)) for name in
                          ("capture_stageb_lighting.py", "stageb_lighting.py", "capture_relief.py")},
              "inputs": {str(path): sha256(path) for path in (args.exe, args.iwad, args.materials, args.flashlight)},
              "runtime_pk3": {path.name: sha256(path) for path in sorted(args.exe.parent.glob("*.pk3"))}}
    try:
        for map_name in args.case or CASES:
            shots = {name: capture(args, args.out / map_name / name, map_name, controls,
                                   None if name == "original" else authoring,
                                   inputs[controls[-1]], identity.group(1), relief=not name.endswith("without-relief"))
                     for name, controls in CASES[map_name].items()}
            report["cases"][map_name] = {"comparisons": compare(args.out, map_name, shots),
                                         "captures": {name: shot[1] for name, shot in shots.items()}}
            print(f"{map_name}: {', '.join(shots)}", flush=True)
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
    args = parser.parse_args()
    try:
        run(args)
    except (KeyError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
