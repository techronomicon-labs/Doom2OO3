"""Capture matched Doom II Stage A relief images from the native Vulkan renderer."""

import argparse
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from PIL import Image, ImageChops, ImageDraw, ImageStat

from gallery import Map, png, wad


SIZE = (640, 480)
WARMUP = 32
FRAMES = 4
DIFF_GAIN = 8
INCIDENCES = (17, 26, 33)
PRIMARY_MATERIALS = {
    "BRICK7": ("Brick and mortar", "wall"),
    "CEMENT7": ("Concrete blocks", "wall"),
    "MARBFAC3": ("Carved stone", "wall"),
    "WOOD8": ("Wood plank seams", "wall"),
    "FLAT5_2": ("Wood plank floor", "flat"),
    "FLOOR5_4": ("Masonry floor", "flat"),
    "METAL2": ("Metal reference", "wall"),
    "RLCTRL": ("Featureless PBR control", "wall"),
}
EXTRA_PREVIEW_MATERIALS = {
    "BRICK4": ("Cracked masonry", "wall"),
    "WOOD9": ("Weathered planks", "wall"),
    "TEKWALL4": ("Circuit panel", "wall"),
    "SW1BRCOM": ("Wall switch", "wall"),
    "BIGDOOR2": ("Machinery door", "wall"),
    "GSTONE1": ("Rough stone blocks", "wall"),
    "FLOOR4_8": ("Bevelled floor tiles", "flat"),
    "FLAT18": ("Painted floor panels", "flat"),
    "RROCK14": ("Stone floor blocks", "flat"),
    "CEIL5_2": ("Pitted ceiling coating", "flat"),
    "BRONZE1": ("Bronze panels", "wall"),
    "FLOOR0_1": ("Entryway floor tiles", "flat"),
    "MODWALL1": ("Detailed machinery panel", "wall"),
}
MATERIALS = {
    **PRIMARY_MATERIALS,
    **EXTRA_PREVIEW_MATERIALS,
    "BRICK1": ("Thin brick courses", "wall"),
    "BRONZE2": ("Entryway wall panels", "wall"),
    "FLOOR3_3": ("Weathered floor grain", "flat"),
    "FLOOR7_1": ("Fine wood floor", "flat"),
    "NUKEDGE1": ("Painted slime edge without relief", "wall"),
    "RROCK18": ("Dense stone aggregate", "flat"),
    "SW1SKULL": ("Carved skull switch", "wall"),
    "ZIMMER2": ("Rough stone seams", "wall"),
}
UNBOUND_CONTROLS = {"NUKEDGE1"}
NEUTRAL_CONTROLS = UNBOUND_CONTROLS | {"RLCTRL"}
PREVIEW_MENU = "DoomIIReliefPreviewMenu"


@dataclass(frozen=True)
class Scene:
    material: str
    map_name: str
    incidence: int
    x: float
    y: float
    yaw: int
    pitch: int


def scenes(materials, incidences=INCIDENCES, *, metadata=MATERIALS):
    cases = []
    for name in materials:
        for incidence in incidences:
            reverse = incidence == 26
            if metadata[name][1] == "wall":
                yaw = 180 - incidence if reverse else incidence
                x = -100 * math.cos(math.radians(yaw))
                y = 128 - 100 * math.sin(math.radians(yaw))
                pitch = 0
            else:
                yaw = 140 if reverse else 65
                distance = 41 / math.tan(math.radians(incidence))
                x = -distance * math.cos(math.radians(yaw))
                y = 40 - distance * math.sin(math.radians(yaw))
                pitch = incidence
            cases.append(Scene(name, f"REL{len(cases) + 1:03}", incidence,
                               round(x, 6), round(y, 6), yaw, pitch))
    return cases


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def preview_scenes():
    order = ("CEMENT7", "FLAT5_2", "BRICK7", "MARBFAC3", "WOOD8", "FLOOR5_4", "METAL2", "RLCTRL",
             *EXTRA_PREVIEW_MATERIALS)
    views = scenes(order, (26,))
    return [replace(case, map_name=f"RPV{index:03}") for index, case in enumerate(views, 1)]


PREVIEW_OVERLAY = '''
    override void WorldTick()
    {
        if (RoomLabel != "" || level.time < 2 || players[0].mo == null) return;
        let lamp = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
        if (lamp == null) return;
        let pawn = players[0].mo;
{rooms}
        if (RoomLabel != "") lamp.Enabled[0] = true;
    }

    override void RenderOverlay(RenderEvent e)
    {
        if (RoomLabel == "" || e.Camera == null) return;
        let toggle = CVar.FindCVar('gl_world_relief');
        let lamp = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
        bool beam = lamp != null && lamp.Beams[0] != null;
        String state = String.Format("%s   |   Relief %s   |   Flashlight %s", RoomLabel,
            toggle != null && toggle.GetBool() ? "ON" : "OFF", beam ? "ON" : "OFF");
        Screen.DrawText(SmallFont, Font.CR_WHITE, 8, 8, state,
            DTA_VirtualWidth, 480, DTA_VirtualHeight, 360, DTA_Shadow, true);
        Screen.DrawText(SmallFont, Font.CR_WHITE, 8, 22,
            "R/Mid Compare   L Lamp   Wheel Rooms   F1 Pick",
            DTA_VirtualWidth, 480, DTA_VirtualHeight, 360, DTA_Shadow, true);
    }
'''


def prepare(path, cases, playable=False, *, metadata=MATERIALS):
    members = {}
    mapinfo = []
    pitch = []
    for room_index, case in enumerate(cases):
        room = Map()
        title, kind = metadata[case.material]
        floor = case.material if kind == "flat" else "LABFLOOR"
        wall = case.material if kind == "wall" else "LABWALL"
        sector = room.sector(ft=floor, light=104)
        room.rows["sector"][sector]["heightceiling"] = 144
        points = [(-208, -208), (-208, 128), (208, 128), (208, -208)]
        for wall_index, (a, b) in enumerate(zip(points, points[1:] + points[:1])):
            room.line(a, b, sector, texture=wall if wall_index == 1 else "LABWALL")
            room.rows["sidedef"][-1].update(scalex_mid=1, scaley_mid=1)
        room.thing(1, case.x, case.y, angle=case.yaw)
        members[f"maps/{case.map_name}.wad"] = wad(case.map_name, room.text())
        if playable:
            next_room = cases[(room_index + 1) % len(cases)].map_name
            previous_room = cases[(room_index - 1) % len(cases)].map_name
            mapinfo.append(f'map {case.map_name} "{title}" {{ next = "{next_room}" '
                           f'secretnext = "{previous_room}" nointermission }}')
        else:
            mapinfo.append(f'map {case.map_name} "{case.material} {case.incidence} degrees" {{}}')
        pitch.append(f'        if (level.MapName == "{case.map_name}") pawn.A_SetPitch({case.pitch});')

    # Use the installed add-on's own light source and update path. This handler
    # exists only inside the fixture package and only runs once after spawn.
    members["ZSCRIPT"] = ('''version "4.10"
class StageAReliefFixture : EventHandler
{
    bool Started;
    bool Logged;
    override void WorldTick()
    {
        if (Logged || level.time < 2 || players[0].mo == null) return;
        let lamp = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
        if (lamp == null) return;
        if (Started)
        {
            let beam = lamp.Beams[0];
            if (beam == null) return;
            Console.Printf("STAGE_A_BEAM %.6f %.6f %.6f %.6f %.6f %d %d %d %d %.6f %.6f",
                beam.Pos.X, beam.Pos.Y, beam.Pos.Z, beam.Angle, beam.Pitch,
                beam.Args[0], beam.Args[1], beam.Args[2], beam.Args[3],
                beam.SpotInnerAngle, beam.SpotOuterAngle);
            Logged = true;
            return;
        }
        let pawn = players[0].mo;
''' + "\n".join(pitch) + '''
        lamp.Enabled[0] = true;
        Started = true;
    }
}
''').encode()
    handler = "StageAReliefFixture"
    if playable:
        handler = "StageAReliefPreview"
        rooms = []
        menu = [f'OptionMenu "{PREVIEW_MENU}"', '{', '  Title "Doom II Relief Preview"']
        for case in cases:
            title, _ = MATERIALS[case.material]
            rooms.append(f'        if (level.MapName == "{case.map_name}") {{ RoomLabel = "{title}"; '
                         f'pawn.A_SetPitch({case.pitch}); }}')
            menu.append(f'  Command "{case.material} - {title}", "map {case.map_name}"')
        members["MENUDEF"] = ("\n".join([*menu, "}"]) + "\n").encode()
        overlay = PREVIEW_OVERLAY.replace("{rooms}", "\n".join(rooms))
        members["ZSCRIPT"] = (f'version "4.10"\nclass {handler} : EventHandler\n'
                              '{\n    String RoomLabel;\n' + overlay + '}\n').encode()
    members["MAPINFO"] = (f'GameInfo {{ AddEventHandlers = "{handler}" }}\n'
                          + "\n".join(mapinfo)).encode()
    for name, value in (("LABWALL", 67), ("LABFLOOR", 57), ("LABCEIL", 47), ("RLCTRL", 105)):
        namespace = "flats" if name in ("LABFLOOR", "LABCEIL") else "textures"
        members[f"{namespace}/{name}.png"] = png(Image.new("RGB", (64, 64), (value,) * 3))

    # Match the relief material shader and descriptor path with uniform height.
    # 128 is the quantized midpoint used by the material pack's 8-bit images.
    layers = {"normal": ("RGB", (128, 128, 255)), "metallic": ("L", 0),
              "roughness": ("L", 192), "ao": ("L", 255), "height": ("L", 128)}
    declarations = []
    for channel, (mode, value) in layers.items():
        name = f"rlcontrol/{channel}.png"
        members[name] = png(Image.new(mode, (64, 64), value))
        declarations.append(f'{channel} "{name}" {{ filter linear }}')
    members["GLDEFS"] = f'material texture RLCTRL {{ {" ".join(declarations)} }}\n'.encode()

    with ZipFile(path, "w") as archive:
        for name, data in sorted(members.items()):
            archive.writestr(ZipInfo(name), data, compress_type=ZIP_DEFLATED)


def fixed_pose(frame):
    camera = frame["camera"]
    return {
        **{key: [round(value, 5) for value in camera[key]]
           for key in ("position", "angles", "hardware_angles")},
        "fov": round(camera["fov"], 5),
    }


def run_render(args, case, fixture, folder, enabled, source, *, extra_files=(), unbound=UNBOUND_CONTROLS):
    folder.mkdir()
    ini = folder / "fixture.ini"
    ini.write_text("[GlobalSettings]\nvk_rayquery=false\nvid_fullscreen=false\n", encoding="ascii")
    prefix = folder / "frame"
    width, height = map(str, SIZE)
    command = [
        str(args.exe), "-iwad", str(args.iwad), "-file", *map(str, extra_files), str(args.materials),
        str(args.flashlight), str(fixture), "-stdout", "-nostartup", "-noautoload",
        "-noautoexec", "-nosound", "-nojoy", "-rngseed", "2002", "-config", str(ini),
        "-savedir", str(folder), "-window", "-width", width, "-height", height,
        "-sdvkobserve", str(prefix), "-sdvkobservemode", "state",
        "-sdvkobservewarmup", str(WARMUP), "-sdvkobserveframes", str(FRAMES),
        "-sdvkobservegpu", "-sdvkobservequit",
        "+vid_rendermode", "4", "+vid_setsize", width, height, "+gl_levelmesh", "false",
        "+gl_light_shadows", "0", "+gl_lights", "true", "+gl_ubershaders", "false",
        "+gl_multisample", "0", "+cl_capfps", "true", "+gl_precache", "true",
        "+r_drawplayersprites", "false", "+screenblocks", "12", "+crosshair", "0",
        "+fov", "90", "+con_notifytime", "0", "+show_messages", "false", "+use_mouse", "false",
        # The calibrated capture poses measure the beam from the camera eye.
        "+sdvk_fl_offset_x", "0", "+sdvk_fl_offset_y", "0", "+sdvk_fl_offset_z", "0", "+sdvk_fl_aim_pitch", "0",
        "+gl_world_relief", "true" if enabled else "false",
        "+gl_world_relief_depth", str(args.depth), "+gl_world_relief_orientation", str(args.orientation),
        "+gl_world_relief_exaggeration", str(args.exaggeration), "+map", case.map_name,
    ]
    with (folder / "engine.log").open("wb") as log:
        subprocess.run(command, cwd=args.exe.parent, stdout=log, stderr=subprocess.STDOUT,
                       timeout=90, check=True)
    log_text = (folder / "engine.log").read_text(encoding="utf-8", errors="replace")
    require("Unknown command" not in log_text, f"Unknown console command in {folder / 'engine.log'}")
    beam_records = re.findall(r"^STAGE_A_BEAM ([0-9. \-]+)$", log_text, re.M)
    require(len(beam_records) == 1, f"Missing live flashlight actor pose in {folder}")
    beam = list(map(float, beam_records[0].split()))
    require(len(beam) == 11 and math.dist(beam[:3], (case.x, case.y, 41)) < 0.02
            and abs((beam[3] - case.yaw + 180) % 360 - 180) < 0.02
            and abs(beam[4] - case.pitch) < 0.02
            and beam[5:] == [255, 240, 216, 180, 12, 28], f"Wrong flashlight pose or output in {folder}")
    raw = json.loads(prefix.with_suffix(".renderer.json").read_text(encoding="utf-8"))
    build = raw["build"]
    require(raw["status"] == "COLLECTED_PENDING_VALIDATION" and raw["screenshot"]["available"]
            and raw["observed_frames"] == FRAMES and raw["dropped_records"] == 0
            and build["backend"] == "vulkan" and build["commit"] == source
            and not build["vulkan"]["ray_query_enabled"], f"Incomplete native capture in {folder}")
    frames = [row["data"] for row in raw["records"] if row["kind"] == "frame"]
    require(len(frames) == FRAMES and all(
        frame["map"] == case.map_name and frame["hardware_renderer"]
        and (frame["width"], frame["height"]) == SIZE and frame["walls"] > 0 and frame["flats"] > 0
        and frame["active_lights"] == frame["spot_lights"] == frame["relief_flashlight_lights"] == 1
        and not frame["settings"]["gl_levelmesh"] and not frame["settings"]["gl_ubershaders"]
        and frame["settings"]["gl_light_shadows"] == 0 for frame in frames),
        f"Expected the requested Vulkan view with one live flashlight spotlight in {folder}")
    poses = [fixed_pose(frame) for frame in frames]
    require(all(pose == poses[0] for pose in poses), f"Camera moved during {folder.name}")
    pose = poses[-1]
    require(math.dist(pose["position"], (case.x, case.y, 41)) < 0.02
            and abs((pose["angles"][0] - case.yaw + 180) % 360 - 180) < 0.02
            and abs(pose["angles"][1] - case.pitch) < 0.02,
            f"Wrong camera pose {pose} for {case} in {folder}")
    materials = [row["data"] for row in raw["records"] if row["kind"] == "material"
                 and row["data"]["name"].upper() == case.material]
    has_height = case.material not in unbound
    require(len(materials) >= FRAMES and all((row["height_texture_index"] >= 0) == has_height
                                             for row in materials),
            f"Unexpected native material or height binding for {case.material} in {folder}")
    for knob in ("depth", "orientation", "exaggeration"):
        expected = getattr(args, knob) if enabled and has_height else 0
        require(all(math.isclose(row[f"world_relief_{knob}"], expected, abs_tol=1e-6) for row in materials),
                f"Wrong submitted relief {knob} for {case.material} in {folder}")
    path = prefix.with_suffix(".png")
    with Image.open(path) as image:
        require(image.size == SIZE and image.convert("RGB").getcolors(31) is None,
                f"Blank or wrong-size native screenshot in {folder}")
    gpu_times = {}
    for row in raw["records"]:
        data = row["data"]
        if row["kind"] == "timing" and data.get("clock") == "gpu":
            gpu_times.setdefault(data["name"], []).append(data["milliseconds"])
    return path, {"argv": command, "build": build,
                  "conditions": {**{key: frames[-1][key] for key in
                                    ("map", "settings", "walls", "flats", "active_lights", "spot_lights",
                                     "relief_flashlight_lights")},
                                 "camera": pose, "flashlight": dict(position=beam[:3], yaw=beam[3],
                                 pitch=beam[4], rgb=beam[5:8], radiusarg=beam[8], cone_angles=beam[9:])},
                  "cpu_render_view_ms": [frame["cpu_render_view_ms"] for frame in frames],
                  "gpu_named_group_ms": gpu_times,
                  "gpu_availability": raw["availability"]["gpu_timing"]}


def compare(out, case, off, on, *, metadata=MATERIALS, neutral=NEUTRAL_CONTROLS):
    require(off[1]["conditions"] == on[1]["conditions"] and off[1]["build"] == on[1]["build"],
            f"Capture conditions drifted for {case}")
    with Image.open(off[0]) as source:
        a = source.convert("RGB")
    with Image.open(on[0]) as source:
        b = source.convert("RGB")
    diff = ImageChops.difference(a, b)
    red, green, blue = diff.split()
    magnitude = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    histogram = magnitude.histogram()
    width, height = SIZE
    pixels = width * height
    amplified = diff.point([min(DIFF_GAIN * delta, 255) for delta in range(256)] * 3)
    diff.save(out / f"{case.map_name}-difference.png")
    sheet = Image.new("RGB", (width * 3, height + 54), "#15191f")
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 8), f"{metadata[case.material][0]} / {case.material} / "
              f"{case.incidence} degrees from the surface plane", fill="white")
    for column, (image, label) in enumerate(((a, "Relief OFF"), (b, "Relief ON"),
                                             (amplified, f"Absolute RGB difference x{DIFF_GAIN}"))):
        draw.text((width * column + 10, 32), label, fill="white")
        sheet.paste(image, (width * column, 54))
    sheet.save(out / f"{case.map_name}-comparison.png")
    require(case.material not in neutral or histogram[0] == pixels,
            f"Relief altered the neutral control in {case.map_name}")
    return {"changed_pixels": pixels - histogram[0], "changed_fraction": 1 - histogram[0] / pixels,
            "pixels_over_2": sum(histogram[3:]), "mean_absolute_rgb": ImageStat.Stat(diff).mean,
            "maximum_absolute_rgb": [high for _, high in diff.getextrema()],
            "max_channel_delta_histogram": histogram,
            "median_cpu_render_view_ms": {"off": statistics.median(off[1]["cpu_render_view_ms"]),
                                          "on": statistics.median(on[1]["cpu_render_view_ms"])},
            "median_gpu_named_group_ms": {
                mode: {name: statistics.median(values)
                       for name, values in shot[1]["gpu_named_group_ms"].items()}
                for mode, shot in (("off", off), ("on", on))}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("exe", "iwad", "materials", "flashlight", "out"):
        parser.add_argument(f"--{option}", type=Path, required=True)
    parser.add_argument("--depth", type=float, default=4)
    parser.add_argument("--orientation", type=float, default=2.5)
    parser.add_argument("--exaggeration", type=float, default=1)
    parser.add_argument("--material", action="append", choices=MATERIALS,
                        help="capture only the chosen material(s), repeat to select additional ones")
    parser.add_argument("--incidence", type=int, action="append", choices=INCIDENCES,
                        help="capture only the chosen angle(s), repeat to select additional ones")
    args = parser.parse_args()
    knobs = {name: getattr(args, name) for name in ("depth", "orientation", "exaggeration")}
    for name, maximum in (("depth", 16), ("orientation", 8), ("exaggeration", 2)):
        if not 0 <= knobs[name] <= maximum:
            parser.error(f"--{name} must be between 0 and {maximum}")
    for name in ("exe", "iwad", "materials", "flashlight", "out"):
        setattr(args, name, getattr(args, name).resolve())
    inputs = [args.exe, args.iwad, args.materials, args.flashlight]
    for path in inputs:
        if not path.is_file():
            parser.error(f"Missing input {path}")
    if args.out.exists():
        parser.error("--out must name a new directory")
    args.out.mkdir(parents=True)
    cases = scenes(dict.fromkeys(args.material or PRIMARY_MATERIALS),
                   dict.fromkeys(args.incidence or INCIDENCES))
    report = {"status": "incomplete", "started_utc": datetime.now(timezone.utc).isoformat(),
              "size": SIZE, "warmup_frames": WARMUP, "retained_frames": FRAMES,
              "controls": knobs, "captures": {}, "cases": {}}
    try:
        version = subprocess.check_output([args.exe, "--version"], cwd=args.exe.parent,
                                          text=True, encoding="utf-8", timeout=20)
        commit = re.search(r"^Commit: ([0-9a-f]{40})$", version, re.M)
        require(commit is not None, "Missing build commit from vkdoom --version")
        repo = Path(__file__).resolve().parents[2]
        source_diff = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=repo)
        (args.out / "source.diff").write_bytes(source_diff)
        report.update(version=version, build_commit=commit.group(1),
                      checkout_status=subprocess.check_output(["git", "status", "--short"], cwd=repo, text=True),
                      checkout_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
                      capture_sources={name: sha256(Path(__file__).with_name(name)) for name in
                                       ("capture_relief.py", "gallery.py", "build.py", "structural_relief.py",
                                        "relief_wall_profiles.py", "relief_flat_profiles.py")},
                      inputs={str(path): sha256(path) for path in inputs},
                      runtime_files={path.name: sha256(path) for path in sorted(args.exe.parent.iterdir())
                                     if path.is_file() and path.suffix.lower() in (".pk3", ".dll", ".so")})
        fixture = args.out / "relief-fixture.pk3"
        prepare(fixture, cases)
        for case in cases:
            shots = []
            for enabled in (False, True):
                key = f"{case.map_name}-{'on' if enabled else 'off'}"
                shot = run_render(args, case, fixture, args.out / key, enabled, commit.group(1))
                report["captures"][key] = shot[1]
                shots.append(shot)
            stats = compare(args.out, case, *shots)
            report["cases"][case.map_name] = {**asdict(case), "statistics": stats}
            print(f"{case.material} at {case.incidence} degrees: {stats['changed_pixels']} changed pixels", flush=True)
        report["status"] = "captured_pending_owner_review"
    except (KeyError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
        parser.exit(1, f"{error}\n")
    finally:
        report["files"] = {path.relative_to(args.out).as_posix(): sha256(path)
                           for path in sorted(args.out.rglob("*")) if path.is_file()}
        manifest = args.out / "manifest.json"
        manifest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (args.out / "manifest.sha256").write_text(f"{sha256(manifest)}  manifest.json\n", encoding="ascii")


if __name__ == "__main__":
    main()
