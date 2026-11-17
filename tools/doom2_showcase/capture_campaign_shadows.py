"""Check both flashlight shadow backends against Doom II and DBP50 campaign actors."""

import argparse
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile

from PIL import Image, ImageChops

from capture_relief import fixed_pose, require
from capture_shadow_puppets import MODES
from capture_stageb_lighting import differences
from gallery import Map, wad


# Editor numbers go through each game's real actor and sprite replacements.
# All seven silhouettes fit the spotlight at once, including the fuzzy Spectre,
# an animated lantern, a shootable barrel and an unshootable solid column.
CROWD = [(3004, -78, 22), (66, 0, 42), (3005, 77, 40), (58, -51, 75),
         (2035, -29, -6), (37, 40, 8), (29, 15, 96)]
CONTROLS = [(2014, -29, 0), (10, 0, 24), (34, 29, 0)]
# Together with CROWD these cover every Doom II enemy family, including the
# Lost Soul's translucent style. DBP50 repurposes the SS and Keen slots as
# invisible ambient sound sources through DEHACKED.
ROSTER = [(9, -94, 14), (65, -57, 22), (3001, -14, 4), (3002, 37, 14), (3006, 85, 18),
          (64, -104, 87), (3003, -57, 76), (69, 5, 60), (68, 55, 80), (67, 110, 78), (71, 9, 110)]
BOSSES = [(7, -62, 60), (16, 57, 82), (88, -12, -18), (84, 43, 5), (72, 0, 116)]
GROUPS = {"crowd": CROWD, "roster": ROSTER, "bosses": BOSSES, "controls": CONTROLS,
          "spectre": [(58, 0, 0)], "decor": [(37, 0, 0)]}
# An 8-bit stencil accumulator would wrap here if all volumes were added at once.
OVERLAP = GROUPS["decor"] * 256
# The authored poses face the two Entryway guards and The Passage's COL2
# replacement at (941,-660). Each map supplies its normal walls and things.
MAP01_POSES = {"DoomII": (-103, 1050, 90, 6), "DBP50": (939, -746, 90, 6)}


def fixture(path, game, case):
    map_name = "MAP01" if case == "map01" else "SHCAST"
    x, y, yaw, pitch = MAP01_POSES[game] if case == "map01" else (0, -148, 90, 4)
    with ZipFile(path, "w") as archive:
        info = 'GameInfo { AddEventHandlers = "CampaignShadowCapture" }\n'
        if case != "map01":
            room = Map()
            sector = room.sector(0, "FLOOR5_4", 100)
            room.rows["sector"][sector].update(heightceiling=144, textureceiling="CEIL3_5")
            corners = [(-190, -200), (-190, 144), (190, 144), (190, -200)]
            for a, b in zip(corners, corners[1:] + corners[:1]):
                room.line(a, b, sector, texture="BRICK7")
            room.thing(1, x, y, angle=yaw)
            for index, (actor, ax, ay) in enumerate(OVERLAP if case == "overlap" else GROUPS[case]):
                room.thing(actor, ax, ay, angle=270, id=200 + index)
            archive.writestr(f"maps/{map_name}.wad", wad(map_name, room.text()))
            info += f'map {map_name} "Campaign shadow test" {{ }}\n'
        archive.writestr("MAPINFO", info)
        archive.writestr("ZSCRIPT", f'''version "4.10"
class CampaignShadowCapture : EventHandler
{{
    override void WorldTick()
    {{
        if (level.time != 2 || players[0].mo == null) return;
        let player = players[0].mo;
        let sector = level.PointInSector(({x}, {y}));
        player.SetOrigin(({x}, {y}, sector.floorplane.ZatPoint(({x}, {y}))), false);
        player.A_SetAngle({yaw});
        player.A_SetPitch({pitch});
        let lamp = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
        lamp.Enabled[0] = true;
        level.SetFrozen(true);
    }}
}}
''')
    return map_name


def capture(pack, game, map_name, fixture_path, folder, mode):
    folder.mkdir()
    exe = pack / "runtime/vkdoom.exe"
    base = pack / "addons"
    files = [base / f"{game}-NormalPBR.pk3", base / f"{game}-SpritePBR.pk3", base / "Local-Flashlight.pk3"]
    if game == "DBP50":
        files.insert(0, pack / "DBP50.wad")
    else:
        files.append(base / "DoomII-Emitter-Lighting.pk3")
    prefix = folder / "view"
    ini = folder / "test.ini"
    ini.write_text("[GlobalSettings]\nvk_rayquery=false\nvid_fullscreen=false\n")
    argv = [exe, "-iwad", pack / "doom2.wad", "-file", *files, fixture_path, "-config", ini, "-savedir", folder,
            "-stdout", "-nostartup", "-noautoload", "-noautoexec", "-nosound", "-nojoy", "-rngseed", "2002",
            "-window", "-width", "640", "-height", "480", "-sdvkobserve", prefix, "-sdvkobservemode", "state",
            "-sdvkobservewarmup", "30", "-sdvkobserveframes", "1", "-sdvkobservequit",
            "+vid_setsize", "640", "480",
            "+gl_levelmesh", "false", "+gl_ubershaders", "false", "+gl_raytrace", "false",
            "+gl_multisample", "4", "+gl_ssao", "0", "+gl_bloom", "false", "+r_actorspriteshadow", "0",
            "+gl_light_shadows", "0",
            "+gl_world_relief", "true", "+gl_sprite_lighting_relief", "true", "+gl_spritelight", "2",
            "+gl_shadow_puppets", str(mode), "+gl_shadow_puppet_softness", "1",
            "+sdvk_fl_horizontal", "84", "+sdvk_fl_vertical", "84", "+sdvk_fl_range", "700",
            "+sdvk_fl_offset_y", "16", "+sdvk_fl_offset_z", "14", "+sdvk_fl_aim_pitch", "0",
            "+cl_capfps", "true", "+vid_vsync", "false", "+r_drawplayersprites", "false",
            "+con_notifylines", "0", "+crosshair", "0", "+screenblocks", "12", "+map", map_name]
    with (folder / "engine.log").open("wb") as stream:
        subprocess.run(list(map(str, argv)), cwd=exe.parent, stdout=stream, stderr=subprocess.STDOUT,
                       timeout=60, check=True)
    data = json.loads(prefix.with_suffix(".renderer.json").read_text())
    require(data["status"] == "COLLECTED_PENDING_VALIDATION" and data["build"]["backend"] == "vulkan",
            f"Incomplete Vulkan capture at {folder}")
    frame = next(r["data"] for r in data["records"] if r["kind"] == "frame")
    require(frame["map"] == map_name and frame["relief_flashlight_lights"] == 1
            and frame["shadow_puppets"]["requested"] == mode, f"Incorrect map, light or setting at {folder}")
    submissions = [r["data"] for r in data["records"] if r["kind"] == "flashlight-shadow"]
    require(len(submissions) <= 1 and all(r["mode"] == mode for r in submissions), f"Wrong backend at {folder}")
    with Image.open(prefix.with_suffix(".png")) as image:
        require(image.size == (640, 480), f"Unexpected image size in {folder}")
        # Exclude the campaign overlays and optional status bar from world pixel checks.
        world = image.convert("RGB").crop((0, 80, 640, 414))
    return world, {"active": frame["shadow_puppets"]["active"], "casters": sum(r["casters"] for r in submissions),
                   "camera": fixed_pose(frame), "build": data["build"]["commit"],
                   "sprites": sorted({r["data"]["material"] for r in data["records"] if r["kind"] == "sprite-basis"})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doom2", required=True, type=Path, help="Doom II campaign playtest directory")
    parser.add_argument("--dbp50", required=True, type=Path, help="DBP50 campaign playtest directory")
    parser.add_argument("--out", required=True, type=Path, help="New output directory")
    parser.add_argument("--case", choices=("map01", *GROUPS, "overlap"), action="append")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True)
    result = {}
    cases = list(dict.fromkeys(args.case or ("map01", *GROUPS)))
    if "overlap" in cases:
        cases = ["decor", *(case for case in cases if case not in ("decor", "overlap")), "overlap"]
    for game, pack in (("DoomII", args.doom2.resolve()), ("DBP50", args.dbp50.resolve())):
        decor_masks = {}
        for case in cases:
            label = f"{game}-{case}"
            f = out / (label + ".pk3")
            map_name = fixture(f, game, case)
            results = [capture(pack, game, map_name, f, out / (label + "-" + name), mode)
                       for mode, name in enumerate(MODES)]
            images, states = zip(*results)
            expected = len(GROUPS[case]) if case in GROUPS else None
            if case == "controls":
                expected = 0
            if case == "bosses" and game == "DBP50":
                expected -= 2
            if case == "overlap":
                expected = len(OVERLAP)
            require(states[0]["casters"] == states[0]["active"] == 0, f"Off produced shadows in {label}")
            for mode in (1, 2):
                state = states[mode]
                require(state["camera"] == states[0]["camera"], f"Camera mismatch in {label}")
                require((state["casters"] == expected if expected is not None else state["casters"] > 0)
                        and state["active"] == (mode if state["casters"] else 0),
                        f"Wrong active backend or caster count in {label}/{MODES[mode]}: {state}")
                delta = ImageChops.subtract(images[0], images[mode])
                darkened = differences(Image.new("RGB", delta.size), delta)["pixels_over_2"]
                state["darkened_pixels_over_2"] = darkened
                if case == "decor":
                    decor_masks[mode] = delta
                elif case == "overlap":
                    require(differences(decor_masks[mode], delta)["max_channel_delta"] <= 1,
                            f"Overlapping identical silhouettes changed the flashlight shadow in {label}/{MODES[mode]}")
                if expected == 0:
                    # The pickup's own light can advance by a tic between launches.
                    # The backend never uploads a caster in this control.
                    change = differences(images[0], images[mode])["max_channel_delta"]
                    state["control_max_rgb_delta"] = change
                    require(change <= 1, f"Control changed by {change} RGB levels in {label}")
                else:
                    require(darkened > 20, f"No visible {MODES[mode]} shadow in {label}")
            result[label] = dict(zip(MODES, states))
            (out / "report.json").write_text(json.dumps(result, indent=2))
            print(label, [(s["casters"], s["darkened_pixels_over_2"]) for s in states[1:]], flush=True)


if __name__ == "__main__":
    main()
