#!/usr/bin/env python3
"""Prepare original SHADOW-001 assets and runnable maps; never launch a renderer.

Code: SPDX-License-Identifier: GPL-3.0-or-later
Generated sprite pixels, textures and map geometry: CC0-1.0, authored here.
No Doom, Freedoom, Doom 3 or other third-party image is copied into this package.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.renderer_oracle import prepare as author

EXTENT = (800, 600)
ACTOR_TID = 7101
LIGHT_TID = 7102
LIGHT = (-96, -64, 128)
SOURCE_SIZE = (48, 64)
ROTATIONS = ("1", "2A8", "3A7", "4A6", "5")
CASES = {
    "off": {"mode": 0},
    "legacy": {"mode": 1},
    "projected": {"mode": 2},
    "orbit-east": {"mode": 2, "camera": (240, 160, 112)},
    "orbit-north": {"mode": 2, "camera": (-176, 224, 112)},
    "orbit-west": {"mode": 2, "camera": (-240, -160, 112)},
    "actor-rotated": {"mode": 2, "actor_angle": 90},
    "actor-moved": {"mode": 2, "actor": (40, 24, 0)},
    "invalid-low-light": {"mode": 2, "light": (-96, -64, 32)},
    "cache-reset": {"mode": 2},
}
SETTINGS = {
    "vid_preferbackend": 1, "vid_rendermode": 4, "vid_fullscreen": False,
    "vid_vsync": False, "vid_maxfps": 60, "vk_rayquery": False,
    "gl_levelmesh": False, "gl_lightprobe": False, "gl_light_shadows": 0,
    "gl_texture_filter": 0, "gl_texture_filter_anisotropic": 1,
    "gl_multisample": 0, "gl_tonemap": 0,
    "gl_sprite_shadow_strength": 0.78, "gl_sprite_shadow_length": 192,
    "gl_sprite_shadow_quality": 1, "r_actorspriteshadow": 2,
    "r_actorspriteshadowalpha": 0.5, "r_drawplayersprites": False,
    "vid_brightness": 0, "vid_contrast": 1, "vid_gamma": 1,
}


def humanoid_pixels(view: int, walk: bool = False) -> bytes:
    """Small hand-authored pixel figure with meaningful arm/rifle and leg gaps.

    Five source views use Doom's paired/mirrored eight-rotation convention. The
    asymmetrical rifle and distinct back view expose wrong pose/mirror choices.
    This produces source sprite art only, never an alleged renderer screenshot.
    """
    if view not in range(5):
        raise ValueError("Expected five canonical source views")
    w, h = SOURCE_SIZE
    data = bytearray(w * h * 4)
    palette = {
        "boot": (34, 32, 31, 255), "dark": (44, 60, 53, 255),
        "cloth": (80, 106, 83, 255), "light": (126, 145, 108, 255),
        "skin": (200, 161, 117, 255), "skinshade": (138, 100, 78, 255),
        "metal": (45, 53, 61, 255), "edge": (153, 163, 167, 255),
        "red": (187, 64, 39, 255), "belt": (82, 65, 46, 255),
    }

    def rect(x0, y0, x1, y1, color):
        rgba = palette[color]
        for y in range(max(0, y0), min(h, y1)):
            for x in range(max(0, x0), min(w, x1)):
                data[(y*w+x)*4:(y*w+x+1)*4] = bytes(rgba)

    side = view == 2
    rear = view in (3, 4)
    # Helmet, neck and face. One-pixel steps retain authentic source resolution.
    rect(18, 1, 28, 3, "dark")
    rect(16, 3, 30, 9, "cloth")
    rect(17, 9, 29, 15, "cloth" if rear else "skin")
    rect(18, 15, 27, 17, "skinshade")
    rect(16, 8, 30, 10, "dark")
    if not rear:
        rect(26 if side else 19, 10, 30 if side else 28, 12, "dark")
    rect(20, 17, 26, 20, "skinshade")
    # Torso and vest; source views deliberately differ in silhouette width.
    x0, x1 = ((18, 29) if side else (14+int(view in (1, 3)), 31))
    rect(x0, 19, x1, 37, "cloth")
    rect(x0+2, 20, x1-2, 35, "dark" if rear else "light")
    rect(x0, 35, x1, 39, "belt")
    if rear:
        rect(17, 22, 29, 33, "dark")
        rect(18, 24, 28, 26, "belt")
    else:
        rect(x0+3, 24, x0+6, 29, "dark")
        rect(x1-6, 24, x1-3, 29, "dark")
        rect(x0+3, 21, x0+5, 23, "red")
    # Bent left arm leaves a 3+ source-pixel cutout next to the body.
    rect(9 if not side else 13, 21, x0, 25, "cloth")
    rect(8 if not side else 12, 25, 12 if not side else 16, 33, "cloth")
    rect(10 if not side else 14, 31, 19, 35, "skin")
    # Rifle and forward arm; weapon reaches beyond body and has a thin barrel.
    rect(x1-1, 21, x1+4, 27, "cloth")
    rect(x1+1, 26, x1+5, 31, "skin")
    rect(18, 30, 40 if side else 42, 34, "metal")
    rect(38 if side else 40, 29, 47, 31, "metal")
    rect(20, 30, 39, 31, "edge")
    rect(28, 34, 32, 38, "metal")
    # Separated legs and shoes, with an optional authored alternate stride.
    rect(15, 39, 22, 50, "cloth")
    rect(25, 39, 31, 50, "cloth")
    rect(14 if walk else 15, 49, 21, 59, "dark")
    rect(27 if walk else 26, 49, 33 if walk else 32, 59, "dark")
    rect(11 if walk else 13, 59, 21, 64, "boot")
    rect(27 if walk else 26, 59, 37 if walk else 35, 64, "boot")
    rect(16, 41, 18, 49, "light")
    rect(27, 41, 29, 48, "light")
    return bytes(data)


def zscript() -> bytes:
    return b'''version "4.15.1"
class SHDHumanoid : Actor
{
    int DemoTics;
    Vector3 DemoOrigin;
    Default { Radius 12; Height 64; +CASTSPRITESHADOW }
    States { Spawn: SHD1 A -1; Stop; }
    override void PostBeginPlay() { Super.PostBeginPlay(); DemoOrigin = Pos; }
    override void Tick()
    {
        Super.Tick();
        DemoTics++;
        if (Level.MapName == "SHDROT") Angle += 2;
        if (Level.MapName == "SHDMOVE")
        {
            SetOrigin(DemoOrigin + (40 * sin(DemoTics * 2), 24 * sin(DemoTics), 0), false);
            Angle = 90;
        }
    }
}
class SHDFixedCamera : Actor
{
    int DemoTics;
    Default { Radius 1; Height 1; CameraHeight 0; +NOGRAVITY +NOBLOCKMAP +NOSPRITESHADOW }
    States { Spawn: TNT1 A -1; Stop; }
    override void Tick()
    {
        Super.Tick();
        if (Level.MapName == "SHDORBIT")
        {
            double a = -52 + DemoTics * 0.5;
            SetOrigin((280 * cos(a), 280 * sin(a), 112), false);
            Angle = a + 180;
            Pitch = 18;
            DemoTics++;
        }
        if (playeringame[0] && players[0].mo != null)
        {
            players[0].camera = self;
            players[0].mo.bInvisible = true;
            players[0].mo.bNoSpriteShadow = true;
        }
    }
}
'''


def map_bytes(case: dict, mapname: str = "SHD001", *, interactive: bool = False) -> tuple[bytes, dict]:
    model = author._Map(floor=0, ceiling=192)
    model.records["sector"][0]["lightlevel"] = 176
    model.boundary([(-384, -288), (-384, 288), (384, 288), (384, -288)], ["SDVW"] * 4)
    actor = case.get("actor", (0, 0, 0))
    light = case.get("light", LIGHT)
    camera = case.get("camera", (192, -240, 112))
    yaw = int(round(math.degrees(math.atan2(20-camera[1], 24-camera[0])))) % 360
    distance = math.hypot(24-camera[0], 20-camera[1])
    pitch = round(math.degrees(math.atan2(camera[2]-24, distance)))
    model.thing(1, camera[0], camera[1], angle=yaw, tid=7100)
    model.thing(32701, *actor, angle=case.get("actor_angle", 0), tid=ACTOR_TID)
    model.thing(9800, *light, tid=LIGHT_TID, arg0=255, arg1=220, arg2=178, arg3=256)
    if not interactive:
        model.thing(32702, *camera, angle=yaw, pitch=pitch, tid=7103)
    raw = author.pf_indexed.wad([(mapname, b""), ("TEXTMAP", model.text().encode()), ("ENDMAP", b"")])
    return raw, {"actor_position": actor, "actor_angle": case.get("actor_angle", 0),
                 "light_position": light, "camera_position": camera, "camera_yaw": yaw,
                 "camera_pitch": pitch, "actor_tid": ACTOR_TID, "light_tid": LIGHT_TID,
                 "receiver": {"sector": 0, "floor_z": 0, "ceiling_z": 192},
                 "counts": {key: len(value) for key, value in model.records.items()}}


def members(case: dict) -> tuple[dict[str, bytes], dict]:
    def texture(colour, seam):
        return author.png_rgba(64, 64, bytes(channel for y in range(64) for x in range(64)
            for channel in (seam if x % 32 == 0 or y % 32 == 0 else colour)))
    files = {
        "ZSCRIPT": zscript(),
        "textures/SDVW.png": texture((68, 73, 80, 255), (52, 56, 61, 255)),
        "flats/SDVFL.png": texture((154, 153, 142, 255), (139, 138, 128, 255)),
        "LICENSE-SYNTHETIC.txt": b"Generated pixels and geometry are original CC0-1.0 assets. No third-party game assets are included.\n",
    }
    for view, rotation in enumerate(ROTATIONS):
        files["sprites/SHD1A"+rotation+".png"] = author.png_rgba(*SOURCE_SIZE, humanoid_pixels(view), offset=(24, 64))
    info = 'DoomEdNums { 32701 = SHDHumanoid\n32702 = SHDFixedCamera\n}\n'
    metadata = {}
    for name, interactive in (("SHD001", False), ("SHDPLAY", True), ("SHDORBIT", False),
                              ("SHDROT", False), ("SHDMOVE", False)):
        raw, record = map_bytes(case, name, interactive=interactive)
        files[f"maps/{name}.wad"] = raw
        info += f'map {name} "SHADOW-001 original humanoid laboratory" {{ nointermission }}\n'
        metadata[name] = record
    files["MAPINFO"] = info.encode()
    return files, metadata


def settings(case: dict) -> dict:
    return dict(SETTINGS, gl_sprite_shadow_mode=case["mode"])


def prepare(out: Path, cases: list[str] | None = None) -> dict:
    out = out.resolve()
    if out.exists():
        raise ValueError("Use a fresh output directory; preserve previous evidence")
    selected = cases or list(CASES)
    if len(set(selected)) != len(selected) or any(name not in CASES for name in selected):
        raise ValueError("Unknown or repeated case")
    out.mkdir(parents=True)
    manifest = {"schema": "shadedoomvk.shadow001-demo/v1", "status": "PREPARED",
                "native_executed": False, "visual_acceptance": "PENDING",
                "assets_license": "CC0-1.0", "extent": EXTENT,
                "physical_gpu_stop": "ACTIVE", "cases": {}}
    for name in selected:
        case = CASES[name]
        target = out / name
        target.mkdir()
        files, metadata = members(case)
        archive = author.archive_bytes(files)
        (target / "scene.pk3").write_bytes(archive)
        scene = {"native": {"settings": settings(case)}}
        (target / "fixture.ini").write_bytes(author.configuration(scene))
        commands = [f"{key} {author.setting_literal(value)}" for key, value in settings(case).items()]
        commands += ["screenblocks 12", "crosshair 0", f"vid_setsize {EXTENT[0]} {EXTENT[1]}"]
        commands += list(settings(case))
        raw = "; ".join(commands) + "\n"
        if len(raw.encode()) >= 4094:
            raise ValueError("Capture script exceeds inherited parser line bounds")
        (target / "capture.cfg").write_text(raw, encoding="utf-8")
        manifest["cases"][name] = {"settings": settings(case), "maps": metadata,
            "pk3_sha256": hashlib.sha256(archive).hexdigest(),
            "sprite_sources": {path: hashlib.sha256(value).hexdigest() for path, value in files.items()
                               if path.startswith("sprites/")}}
    (out / "prepared.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out / "README.txt").write_text(
        "SHADOW-001 SYNTHETIC DEMO — PREPARED, NOT VISUALLY ACCEPTED\n\n"
        "Physical GPU testing STOP remains active. These inputs do not authorize a hardware run.\n"
        "Use the exact reviewed candidate runtime, your licensed IWAD or a separately obtained Freedoom2 IWAD.\n"
        "No Doom or Freedoom artwork is redistributed here. scene.pk3 contains original CC0 sprites/maps.\n\n"
        "After separate owner authorization, the Windows console command is:\n"
        '  & "C:\\path\\to\\vkdoom.exe" -noautoload -noautoexec -nosound -iwad "C:\\path\\to\\freedoom2.wad" '
        '-file ".\\projected\\scene.pk3" -config ".\\projected\\fixture.ini" '
        '+vk_rayquery false +map SHDPLAY +exec ".\\projected\\capture.cfg"\n\n'
        "Console: gl_sprite_shadow_mode 0 (Off), 1 (Legacy/Contact), 2 (Projected).\n"
        "map SHDORBIT: orbit camera; map SHDROT: rotating actor; map SHDMOVE: moving actor.\n"
        "map SHDPLAY: player-controlled camera. Escape opens the menu; quit exits.\n",
        encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--case", action="append", choices=CASES)
    args = parser.parse_args(argv)
    result = prepare(args.out, args.case)
    print(json.dumps({"status": result["status"], "cases": list(result["cases"]), "native_executed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
