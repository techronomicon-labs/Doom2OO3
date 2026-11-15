#!/usr/bin/env python3
"""Collect a bounded, genuine SHADOW-001 demo on hosted CPU Vulkan only.

No physical GPU launch, timing campaign, automatic retry, or pixel-exact oracle.
The existing native observer supplies PNGs and source identity. This harness
requires an actual emitted projected-shadow record and meaningful image change;
an implementation that falls back everywhere cannot pass.
SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.shadow001 import prepare_demo
from tools.renderer_oracle import images, native_ci, run, sdvk010_sun_native, validate
from tools.renderer_oracle.sdvk153_probe_reset import SCHEDULE as RESET_SCHEDULE
from tools.renderer_oracle.common import pin, read_json, require, write_json

WARMUP = 12
FRAMES = 3
DEADLINE = 120
RESET_WARMUP = 32
RESET_FRAMES = 40
PROXY_MATERIAL = "SHADOW-001 proxy"
PROJECTION_FIELDS = ("source_texture", "flipped", "light_position", "actor_position", "light_tid",
                     "floor_z", "vertices", "vertex_count", "geometry_hash", "receiver_sector", "mask_scale")


def projection_records(raw: dict) -> list[dict]:
    return [row["data"] for row in raw.get("records", [])
            if row.get("kind") == "sprite-shadow" and row.get("data", {}).get("mode") == "projected"
            and row["data"].get("actor_tid") == prepare_demo.ACTOR_TID]


def _rounded(value):
    if isinstance(value, float):
        require(math.isfinite(value), "Nonfinite projected geometry")
        return round(value, 5)
    if isinstance(value, (list, tuple)):
        return [_rounded(v) for v in value]
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    return value


def projection_signature(record: dict) -> dict:
    require(all(name in record for name in PROJECTION_FIELDS), "Incomplete actual shadow projection record")
    vertices = record["vertices"]
    require(isinstance(vertices, list) and 3 <= len(vertices) <= 256,
            "Projected polygon is absent or unbounded")
    require(record["vertex_count"] == len(vertices) and len(vertices) % 3 == 0,
            "Recorded emitted triangle count differs from emitted vertex payload")
    require(record["light_tid"] == prepare_demo.LIGHT_TID,
            "Shadow selected an unintended light")
    floor = record["floor_z"]
    require(record["receiver_sector"] == 0, "Shadow escaped its eligible receiver sector")
    require(record["mask_scale"] == 4, "Default edge quality did not produce a separate 4x proxy")
    for vertex in vertices:
        require(isinstance(vertex, list) and len(vertex) == 3 and
                all(isinstance(x, (int, float)) and math.isfinite(x) for x in vertex),
                "Malformed/nonfinite shadow vertex")
        require(-384.01 <= vertex[0] <= 384.01 and -288.01 <= vertex[1] <= 288.01,
                "Projected geometry escaped room boundaries")
        require(abs(vertex[2]-floor) <= 0.1, "Shadow is floating above the floor receiver")
    return _rounded({name: record[name] for name in PROJECTION_FIELDS})


def compare_appearance(off: Path, candidate: Path) -> dict:
    left_extent, left = images.decode(off)
    right_extent, right = images.decode(candidate)
    require(left_extent == right_extent == prepare_demo.EXTENT, "Capture extent differs")
    changed = darkened = 0
    for at in range(0, len(left), 3):
        before, after = left[at:at+3], right[at:at+3]
        changed += max(abs(a-b) for a, b in zip(before, after)) >= 8
        darkened += sum(before)-sum(after) >= 24
    require(changed >= 32 and darkened >= 32, "Shadow has no meaningful visible darkening")
    return {"changed_pixels_at_least_8": changed, "darkened_pixels_at_least_24_rgb_sum": darkened,
            "threshold_pixels": 32, "policy": "meaningful bounded effect, not pixel-exact repetition"}


def reset_settings(frame: int) -> tuple[int, dict]:
    settings = prepare_demo.settings(prepare_demo.CASES["cache-reset"])
    phase = 0
    for reset in RESET_SCHEDULE:
        if reset["after_main_views"] < RESET_WARMUP + frame:
            settings[reset["cvar"]] = reset["value"]
            phase += 1
    return phase, settings


def validate_cache_reset(raw: dict, stdout: str) -> dict:
    """Inspect real mask draws through four existing normal-console resets.

    No frame/RGB repeat oracle: live resources must be republished after reset,
    and the selected albedo sampler must reflect the actual frame CVAR readback.
    """
    require(raw.get("observed_frames") == RESET_FRAMES and raw.get("warmup_frames") == RESET_WARMUP,
            "Shadow cache-reset frame budget differs")
    markers = [f"SDVK153_SETTING {s['cvar']}={s['value']} after_main_views={s['after_main_views']}"
               for s in RESET_SCHEDULE]
    require([line for line in stdout.splitlines() if line.startswith("SDVK153_SETTING")] == markers,
            "Shadow cache-reset driver is missing, reordered or incomplete")
    phases = []
    retired = set()
    current_tokens = set()
    for frame in range(1, RESET_FRAMES+1):
        rows = [row for row in raw["records"] if row["frame"] == frame]
        states = [row["data"] for row in rows if row["kind"] == "frame"]
        require(len(states) == 1, "Shadow cache-reset is missing a unique main frame readback")
        phase, settings = reset_settings(frame)
        for key in ("gl_texture_filter", "gl_texture_filter_anisotropic", "vk_rayquery"):
            require(states[0].get("settings", {}).get(key) == settings[key],
                    "Shadow cache-reset actual frame setting differs: " + key)
        require(projection_records({"records": rows}), "Shadow cache-reset lost the emitted shadow")
        draws = [row["data"] for row in rows if row["kind"] == "material"
                 and row["data"].get("name") == PROXY_MATERIAL
                 and row["data"].get("context", {}).get("type") == "main"]
        require(draws, "Shadow cache-reset has no actual main-view mask material binding")
        tokens = set()
        for draw in draws:
            resource = draw.get("resource")
            validate._resource(resource, "shadow mask descriptor")
            require(resource["available"] is True and resource["index"] > 0,
                    "Shadow mask lacks a live descriptor identity")
            tokens.add(tuple(resource[key] for key in ("index", "generation", "epoch", "span")))
            albedo = [layer.get("sampler") for layer in draw.get("layers", [])
                      if layer.get("semantic") == "albedo" and layer.get("binding") == 0]
            require(len(albedo) == 1, "Shadow mask lacks its selected albedo sampler")
            sampler = albedo[0]
            validate._sampler(sampler)
            require(sampler["available"] is True, "Shadow mask sampler is unavailable")
            linear = settings["gl_texture_filter"] == 4
            require(sampler["min_filter"] == sampler["mag_filter"] == int(linear)
                    and sampler["mipmap_mode"] == int(linear),
                    "Shadow mask selected a stale filter policy after reset")
            anisotropy = linear and settings["gl_texture_filter_anisotropic"] == 2
            require(sampler["anisotropy"] is anisotropy and
                    sampler["max_anisotropy"] == (2 if anisotropy else 1),
                    "Shadow mask selected a stale anisotropy policy after reset")
        if len(phases) == phase:
            retired.update(current_tokens)
            current_tokens = set()
            phases.append({"phase": phase, "first_frame": frame,
                           "settings": {key: settings[key] for key in
                                        ("gl_texture_filter", "gl_texture_filter_anisotropic")}})
        require(tokens.isdisjoint(retired), "Shadow mask reused a stale descriptor token across reset")
        current_tokens.update(tokens)
        phases[-1].update(last_frame=frame, live_tokens=[list(token) for token in sorted(current_tokens)])
    require(len(phases) == len(RESET_SCHEDULE)+1, "Shadow cache-reset did not observe every reset phase")
    return {"status": "PASS", "frames": RESET_FRAMES, "settings_resets": len(RESET_SCHEDULE),
            "phases": phases, "scope": "live emitted mask descriptors and selected samplers through normal resets",
            "image_repeatability_required": False, "physical_gpu_qualified": False}


def capture(args, prepared: Path, name: str, output: Path) -> dict:
    output.mkdir()
    (output / "cache").mkdir()
    (output / "save").mkdir()
    (output / "input").mkdir()
    source = prepared / name
    for filename in ("fixture.ini", "capture.cfg", "scene.pk3"):
        shutil.copyfile(source / filename, output / filename)
    # Isolated IWAD location avoids sibling-package discovery. Remove from the
    # public output after execution; retain its exact identity and license.
    staged_iwad = output / "input" / args.iwad.name
    shutil.copyfile(args.iwad, staged_iwad)
    prefix = output / "native"
    frames, warmup = (RESET_FRAMES, RESET_WARMUP) if name == "cache-reset" else (FRAMES, WARMUP)
    argv = [str(args.exe), "-stdout", "-nostartup", "-noautoload", "-noautoexec", "-nosound", "-nojoy",
            "-iwad", str(staged_iwad), "-file", str(output / "scene.pk3"),
            "-config", str(output / "fixture.ini"), "-width", str(prepare_demo.EXTENT[0]),
            "-height", str(prepare_demo.EXTENT[1]), "-savedir", str(output / "save"),
            "-sdvkobserve", str(prefix), "-sdvkobserveframes", str(frames),
            "-sdvkobservewarmup", str(warmup), "-sdvkobservemode", "state",
            "-sdvkobservecache", str(output / "cache"), "-sdvkobservequit"]
    if name == "cache-reset":
        argv.append("-sdvk153samplerresetdriver")
    argv += ["+vk_rayquery", "false", "+map", "SHD001", "+exec", str(output / "capture.cfg")]
    expected = prepare_demo.settings(prepare_demo.CASES[name])
    write_json(output / "request.json", {"argv": argv, "expected_commit": args.expected_commit,
        "settings": expected, "iwad": pin(staged_iwad), "physical_gpu": False,
        "automatic_retries": 0, "timeout_seconds": DEADLINE})
    result = {"status": "FAIL", "case": name}
    started = time.monotonic()
    try:
        with (output / "stdout.log").open("xb") as stdout, (output / "stderr.log").open("xb") as stderr:
            process = subprocess.run(argv, cwd=output, stdout=stdout, stderr=stderr,
                                     check=False, timeout=DEADLINE)
        require(process.returncode == 0, f"Native renderer exit {process.returncode}")
        stdout = (output / "stdout.log").read_text(encoding="utf-8", errors="replace")
        stderr = (output / "stderr.log").read_text(encoding="utf-8", errors="replace")
        run.completion_log(stdout, stderr)
        readbacks = run.console_settings(stdout, expected)
        raw = read_json(output / "native.renderer.json")
        projected = name not in ("off", "legacy", "invalid-low-light")
        required = {"frame", "context", "resource", "material", "pipeline"}
        if projected:
            required.add("sprite-shadow")
        result["observation_integrity"] = validate.observation(
            raw, required_kinds=required, expected_map="SHD001", expected_frames=frames,
            expected_extent=prepare_demo.EXTENT)
        require(raw.get("status") == "COLLECTED_PENDING_VALIDATION" and raw.get("dropped_records") == 0,
                "Native observation failed or dropped required evidence")
        require(raw.get("build", {}).get("commit") == args.expected_commit and
                raw["build"].get("working_tree") == "clean", "Runtime source identity is wrong or dirty")
        require(raw["build"].get("backend") == "vulkan", "Capture did not run Vulkan")
        require("llvmpipe" in raw["build"].get("device", "").lower(), "Runtime device is not software llvmpipe")
        require(raw.get("observed_frames") == frames and raw.get("warmup_frames") == warmup,
                "Native frame budget differs from request")
        frame_records = [row["data"] for row in raw.get("records", []) if row.get("kind") == "frame"]
        require(frame_records and all(row.get("map") == "SHD001" for row in frame_records), "Wrong rendered map")
        require(raw.get("screenshot", {}).get("available") is True, "Observer did not capture its real framebuffer")
        extent, _ = images.decode(output / "native.png")
        require(extent == prepare_demo.EXTENT, "Native framebuffer extent differs")
        records = projection_records(raw)
        require(bool(records) == projected,
                "Actual projected draw is absent or projected an invalid/off receiver")
        if projected:
            signatures = [projection_signature(record) for record in records]
            require(all(row == signatures[0] for row in signatures), "Static shadow changed within bounded capture")
            result["projection_signature"] = signatures[0]
        if name == "cache-reset":
            result["cache_reset"] = validate_cache_reset(raw, stdout)
        result.update(status="COLLECTED", build=raw["build"], settings_readback=readbacks,
                      projected_draw_records=len(records), image=pin(output / "native.png"),
                      source_identity="native --version and observer agree with requested clean SHA")
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        result["error"] = str(error)
        raise
    finally:
        result["elapsed_seconds"] = round(time.monotonic()-started, 3)
        write_json(output / "capture.json", result)
        staged_iwad.unlink(missing_ok=True)
    return result


def qualify(args) -> dict:
    require(re.fullmatch(r"[0-9a-f]{40}", args.expected_commit) is not None, "Exact source SHA required")
    args.exe, args.iwad, args.out = args.exe.resolve(), args.iwad.resolve(), args.out.resolve()
    for path in (args.exe, args.iwad, args.out):
        run._console_path(path)
    require(not args.out.exists(), "Use a fresh output; previous failed observations must survive")
    args.out.mkdir(parents=True)
    result = {"schema": "shadedoomvk.shadow001-native-demo/v1", "status": "FAIL",
              "source_commit": args.expected_commit, "physical_gpu_stop": "ACTIVE",
              "physical_gpu_qualified": False, "performance_accepted": False,
              "visual_owner_acceptance": "PENDING", "automatic_retries": 0, "captures": {}}
    try:
        # Strict existing repository protection; never spoof hosted-runner env.
        result["host"] = sdvk010_sun_native.software_host_guard()
        result["preflight"] = native_ci.preflight(args, args.out)
        version = subprocess.run([str(args.exe), "--version"], capture_output=True, timeout=30, check=False)
        (args.out / "version.txt").write_bytes(version.stdout)
        require(version.returncode == 0 and run.version_identity(version.stdout) == (args.expected_commit, "clean"),
                "Native binary is not from the exact clean source revision")
        prepared = args.out / "prepared"
        manifest = prepare_demo.prepare(prepared)
        result["executable"] = pin(args.exe)
        result["iwad"] = pin(args.iwad)
        for name in prepare_demo.CASES:
            print(name + ": collecting", flush=True)
            result["captures"][name] = capture(args, prepared, name, args.out / name)
            print(name + ": collected", flush=True)
        captures = result["captures"]
        signature = captures["projected"]["projection_signature"]
        for name in ("orbit-east", "orbit-north", "orbit-west"):
            require(captures[name]["projection_signature"] == signature,
                    "Camera orbit changed the selected light-relative shadow pose or floor polygon")
        require(captures["actor-moved"]["projection_signature"]["actor_position"] != signature["actor_position"],
                "Actor movement did not reach the real projected representation")
        require(captures["actor-rotated"]["projection_signature"]["source_texture"] != signature["source_texture"] or
                captures["actor-rotated"]["projection_signature"]["flipped"] != signature["flipped"],
                "Actor rotation did not select its light-relative source pose")
        sprites = manifest["cases"]["projected"]["sprite_sources"]
        require(all(case["sprite_sources"] == sprites for case in manifest["cases"].values()),
                "Source sprite pixels changed between effect/camera cases")
        result["appearance"] = {
            "legacy_vs_off": compare_appearance(args.out / "off/native.png", args.out / "legacy/native.png"),
            "projected_vs_off": compare_appearance(args.out / "off/native.png", args.out / "projected/native.png"),
            "projected_vs_legacy": compare_appearance(args.out / "legacy/native.png", args.out / "projected/native.png"),
        }
        result.update(status="PASS", camera_independence="three orbit views retain the same real projected pose/polygon",
                      ray_queries="disabled in configuration and console readback for every capture",
                      qualification_scope="bounded hosted software Vulkan; owner still judges appearance")
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        result["error"] = str(error)
    finally:
        write_json(args.out / "qualification.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("exe", "iwad", "out"):
        parser.add_argument("--"+flag, type=Path, required=True)
    parser.add_argument("--iwad-license", type=Path)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args(argv)
    result = qualify(args)
    print(json.dumps({name: result.get(name) for name in ("status", "source_commit", "error")}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
