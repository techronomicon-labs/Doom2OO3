#!/usr/bin/env python3
"""Stage a source-labelled Windows playtest archive without launching its engine.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.shadow001.prepare_demo import prepare


def package(runtime: Path, resource_root: Path, out: Path, expected_commit: str) -> dict:
    if re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None:
        raise ValueError("An exact source SHA is required")
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if actual != expected_commit:
        raise ValueError("Checked-out source differs from expected build source SHA")
    runtime, resource_root, out = runtime.resolve(), resource_root.resolve(), out.resolve()
    if out.exists() or out.with_suffix(".zip").exists():
        raise ValueError("Use fresh output paths; earlier packages are preserved")
    if not (runtime / "vkdoom.exe").is_file():
        raise ValueError("Source-built vkdoom.exe is missing")
    files: dict[str, Path] = {}
    # Never copy the optional support/brightmap/widescreen archives: they contain
    # game-derived artwork. Rebuild only the IWAD identification metadata below.
    for directory in (resource_root, runtime):
        for path in directory.iterdir():
            if path.is_file() and (path.suffix.lower() == ".dll" or path.name == "vkdoom.pk3"):
                files[path.name] = path
        for name in ("soundfonts/vkdoom.sf2", "fm_banks/GENMIDI.GS.wopl",
                     "fm_banks/gs-by-papiezak-and-sneakernets.wopn"):
            path = directory / name
            if path.is_file() and not path.is_symlink():
                files[name] = path
    files["vkdoom.exe"] = runtime / "vkdoom.exe"
    licenses = runtime / "licenses.zip"
    if not licenses.is_file():
        licenses = ROOT / "bin/licenses.zip"
    if licenses.is_file():
        files["licenses.zip"] = licenses
    required = {"vkdoom.pk3", "zmusic.dll", "libsndfile-1.dll", "openal32.dll", "licenses.zip", "soundfonts/vkdoom.sf2",
                "fm_banks/GENMIDI.GS.wopl", "fm_banks/gs-by-papiezak-and-sneakernets.wopn"}
    if not required <= files.keys():
        raise ValueError("Matching bundled Windows runtime payload missing: " + ", ".join(sorted(required-files.keys())))
    metadata_source = ROOT / "wadsrc_extra/static/iwadinfo.txt"
    metadata = metadata_source.read_bytes()
    out.mkdir(parents=True)
    for name, path in sorted(files.items()):
        target = out / "runtime" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    # FIWadManager loads IWADINFO from BASEWAD + OPTIONALWAD before identifying
    # the owner's IWAD. Preserve the exact source catalogue and recognition order
    # without any optional game graphics, sprites, fonts or narrative text.
    with zipfile.ZipFile(out / "runtime/game_support.pk3", "x", zipfile.ZIP_DEFLATED) as z:
        member = zipfile.ZipInfo("iwadinfo.txt", date_time=(1980, 1, 1, 0, 0, 0))
        member.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(member, metadata)
    for name in ("LICENSE", "LICENSE.txt", "COPYING", "COPYING.txt"):
        if (ROOT / name).is_file():
            shutil.copyfile(ROOT / name, out / name)
    prepare(out / "demo", ["off", "legacy", "projected"])
    documentation = ROOT / "docs/shadedoomvk/SHADOW-001-M1-PLAYTEST.md"
    if documentation.is_file():
        shutil.copyfile(documentation, out / documentation.name)
    (out / "Owner-Launch-Command.ps1").write_text(
        '# This script only prints a launch command. It does not start Vulkan.\n'
        '# Physical GPU STOP remains active until separate owner authorization.\n'
        'param([Parameter(Mandatory=$true)][string]$Iwad)\n'
        '$ErrorActionPreference = "Stop"\n'
        '$exe = Join-Path $PSScriptRoot "runtime\\vkdoom.exe"\n'
        '$scene = Join-Path $PSScriptRoot "demo\\projected\\scene.pk3"\n'
        '$config = Join-Path $PSScriptRoot "demo\\projected\\fixture.ini"\n'
        '$script = Join-Path $PSScriptRoot "demo\\projected\\capture.cfg"\n'
        'if (!(Test-Path -LiteralPath $Iwad -PathType Leaf)) { throw "IWAD not found" }\n'
        'Write-Output "Prepared only. Physical GPU STOP is ACTIVE."\n'
        'Write-Output "After separate authorization, paste this command:"\n'
        'Write-Output ("& \'{0}\' -noautoload -noautoexec -noextras -nosound -iwad \'{1}\' -file \'{2}\' -config \'{3}\' +vk_rayquery false +map SHDPLAY +exec \'{4}\'" -f '
        "$exe.Replace(\"'\",\"''\"), $Iwad.Replace(\"'\",\"''\"), $scene.Replace(\"'\",\"''\"), $config.Replace(\"'\",\"''\"), $script.Replace(\"'\",\"''\"))\n",
        encoding="utf-8")
    (out / "README-FIRST.txt").write_text(
        "SHADOW-001 M1 — OWNER PLAYTEST CANDIDATE, DRAFT/HOLD\n\n"
        "Physical GPU STOP is ACTIVE. Packaging and compilation are authorized; hardware execution is not.\n"
        "Owner-Launch-Command.ps1 prints the command only. Use it only after reviewing the playtest guide.\n"
        "No IWAD is included. Supply a legally owned Doom II IWAD or separately obtained Freedoom2.\n"
        "Optional game artwork archives are omitted; game_support.pk3 is rebuilt with IWADINFO metadata only.\n"
        "The synthetic humanoid/map pixels are original CC0 assets; the engine retains its repository licenses.\n"
        "Source: " + expected_commit + "\n"
        "This package is not a claim of physical GPU stability, performance or visual acceptance.\n",
        encoding="utf-8")
    inventory = {path.relative_to(out).as_posix(): {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                                 "bytes": path.stat().st_size}
                 for path in sorted(out.rglob("*")) if path.is_file()}
    manifest = {"schema": "shadedoomvk.shadow001-windows-package/v1", "source_commit": expected_commit,
                "status": "PACKAGED_NOT_EXECUTED", "physical_gpu_stop": "ACTIVE", "iwad_included": False,
                "runtime_pk3_allowlist": ["vkdoom.pk3", "game_support.pk3"], "optional_game_assets_included": False,
                "rebuilt_support_archive": {"members": ["iwadinfo.txt"],
                    "source": metadata_source.relative_to(ROOT).as_posix(),
                    "source_sha256": hashlib.sha256(metadata).hexdigest(), "scope": "IWAD identification metadata only"},
                "native_launches": 0, "binary_source_claim": "compiled by source-matched CI; see workflow receipt",
                "files": inventory}
    (out / "package.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    archive = out.with_suffix(".zip")
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=3) as z:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(out).as_posix())
    return {"status": manifest["status"], "source_commit": expected_commit, "archive": str(archive),
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "files": len(inventory)+1}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--resource-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(package(args.runtime, args.resource_root, args.out, args.expected_commit)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
