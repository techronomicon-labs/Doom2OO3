"""Capture native relief comparisons using the original DBP50 WAD."""

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import re
import subprocess

import capture_relief as world
import capture_sprite_relief as sprite
from dbp50_effective import IWAD_SHA256, PWAD_SHA256


SPRITES = (
    sprite.Case("lantern", "DBP50 lantern animation", "HeadCandles", "POL3", -179, -8, "AB", 6,
                bright_frames="AB", coverage_check=True, map_id="DBR001"),
    sprite.Case("column-front", "DBP50 prop front", "SkullColumn", "COL6", -104, 12, "A", -1,
                coverage_check=True, map_id="DBR002"),
    sprite.Case("column-rear", "DBP50 prop rear", "SkullColumn", "COL6", -104, 12, "A", -1,
                angle=90, map_id="DBR003"),
    replace(next(case for case in sprite.CASES if case.key == "imp-walk"),
            title="DBP50 imp walking", map_id="DBR004"),
    replace(next(case for case in sprite.CASES if case.key == "armor"),
            title="DBP50 armor bonus animation", map_id="DBR005"),
    sprite.Case("archfire", "DBP50 green flame animation", "ArchvileFire", "FIRE", -166, -4,
                "ABABCBCBCDCDCDEDEDEFEFEFGHGHGH", 2, neutral=True, height_bound=False,
                map_id="DBR006", spawn_tic=49, finite=True),
)
MATERIALS = {
    "DBLD10": ("DBP50 building wall", "wall"),
    "DNOX": ("DBP50 floor tile grout", "flat"),
    "DIAMOND6": ("DBP50 diamond tiles", "flat"),
    "0BLACK": ("DBP50 black control", "wall"),
}
UNBOUND = {"0BLACK"}


def world_run(args):
    args.out.mkdir(parents=True)
    inputs = (args.exe, args.iwad, args.dbp50, args.materials, args.flashlight)
    report = {"status": "incomplete", "cases": {}}
    try:
        version = subprocess.check_output([args.exe, "--version"], cwd=args.exe.parent,
                                          text=True, encoding="utf-8", timeout=20)
        commit = re.search(r"^Commit: ([0-9a-f]{40})$", version, re.M)
        world.require(commit is not None, "Expected vkdoom source identity")
        report.update(version=version, inputs={str(path): world.sha256(path) for path in inputs},
                      runtime_files={path.name: world.sha256(path) for path in sorted(args.exe.parent.glob("*.pk3"))})
        cases = world.scenes(dict.fromkeys(args.material or MATERIALS),
                             dict.fromkeys(args.incidence or (26,)), metadata=MATERIALS)
        fixture = args.out / "dbp50-world-fixture.pk3"
        world.prepare(fixture, cases, metadata=MATERIALS)
        for case in cases:
            shots = {mode: world.run_render(args, case, fixture, args.out / f"{case.map_name}-{mode}",
                                            mode == "on", commit.group(1), extra_files=(args.dbp50,), unbound=UNBOUND)
                     for mode in ("off", "on")}
            stats = world.compare(args.out, case, shots["off"], shots["on"], metadata=MATERIALS, neutral=UNBOUND)
            world.require(case.material in UNBOUND or stats["pixels_over_2"] > 20,
                          f"No visible Vulkan depth response for {case.material}")
            report["cases"][case.map_name] = {**asdict(case), "statistics": stats,
                                              "captures": {key: shot[1] for key, shot in shots.items()}}
            print(f"{case.material} at {case.incidence} degrees: {stats['changed_pixels']} changed pixels", flush=True)
        report["status"] = "captured_pending_owner_review"
    except (KeyError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
        raise
    finally:
        report["files"] = {path.relative_to(args.out).as_posix(): world.sha256(path)
                           for path in sorted(args.out.rglob("*")) if path.is_file()}
        manifest = args.out / "manifest.json"
        manifest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (args.out / "manifest.sha256").write_text(f"{world.sha256(manifest)}  manifest.json\n", encoding="ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="task", required=True)
    sprites = modes.add_parser("sprites", help="compare DBP50 actor animation and rotation")
    surfaces = modes.add_parser("world", help="compare DBP50 walls and floors")
    for mode, names, defaults in ((sprites, ("sprites",), (3.5, 4, 1)),
                                  (surfaces, ("materials",), (5, 5, 1.25))):
        for name in ("exe", "iwad", "dbp50", "flashlight", "out", *names):
            mode.add_argument(f"--{name}", type=Path, required=True)
        for knob, default in zip(("depth", "orientation", "exaggeration"), defaults, strict=True):
            mode.add_argument(f"--{knob}", type=float, default=default)
    sprites.add_argument("--case", action="append", choices=[case.key for case in SPRITES])
    sprites.add_argument("--lamp-off", action="store_true")
    surfaces.add_argument("--material", action="append", choices=MATERIALS)
    surfaces.add_argument("--incidence", action="append", type=int, choices=world.INCIDENCES)
    args = parser.parse_args()
    for name, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
            if name == "out" and value.exists():
                parser.error("--out must name a new directory")
            if name != "out" and not value.is_file():
                parser.error(f"Missing input {value}")
    try:
        world.require(world.sha256(args.iwad) == IWAD_SHA256 and world.sha256(args.dbp50) == PWAD_SHA256,
                      "Expected the supported Doom II and DBP50 WADs")
        if args.task == "sprites":
            sprite.run(args, available=SPRITES, pwad=args.dbp50)
        else:
            world_run(args)
    except (KeyError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
