"""Build the stock sprite relief preview or compare native animation captures."""

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import re
import struct
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import numpy as np
from PIL import Image, ImageDraw

from capture_relief import fixed_pose, require, sha256
from gallery import Map, png, wad
from sprite_materials import IWAD_SHA256, SpriteDecoder, read_wad, sha


SIZE = (640, 480)
WARMUP = 12
FRAMES = 84
MENU = "DoomIISpriteReliefMenu"


@dataclass(frozen=True)
class Case:
    key: str
    title: str
    actor: str
    sprite: str
    player_y: int
    pitch: int
    frames: str
    tics: int | tuple[int, ...]
    angle: int = 270
    z: int = 0
    walking: bool = False
    coverage_check: bool = False
    neutral: bool = False
    height_bound: bool = True
    bright_frames: str = ""
    map_id: str = ""
    spawn_tic: int = 2
    finite: bool = False


CASES = (
    Case("imp-front", "Imp idle front", "DoomImp", "TROO", -105, 7, "AB", 10,
         coverage_check=True),
    Case("imp-left", "Imp idle left", "DoomImp", "TROO", -105, 7, "AB", 10, angle=225),
    Case("imp-right", "Imp idle right", "DoomImp", "TROO", -105, 7, "AB", 10, angle=315),
    Case("imp-rear", "Imp idle back", "DoomImp", "TROO", -105, 7, "AB", 10, angle=90),
    Case("imp-walk", "Imp walking", "DoomImp", "TROO", -315, 4, "AABBCCDD", 3,
         walking=True, coverage_check=True),
    Case("armor", "Armor bonus animation", "ArmorBonus", "BON2", -67, 26, "ABCDCB", 6),
    Case("column", "Heart column animation", "HeartColumn", "COL5", -100, 10, "AB", 14),
    Case("fireball", "Imp fireball animation", "DoomImpBall", "BAL1", -80, 4, "AB", 4,
         z=32, neutral=True, height_bound=False),
    Case("rocket", "Fullbright rocket frame", "Rocket", "MISL", -85, 5, "A", 1,
         angle=225, z=32, bright_frames="A"),
    Case("lost-soul", "Lost Soul idle", "LostSoul", "SKUL", -92, -4, "AB", 10,
         z=21, coverage_check=True, bright_frames="AB"),
    # The stock torch brightmaps keep per-pixel emission and disable whole-frame BRIGHT.
    Case("blue-torch", "Blue torch animation", "BlueTorch", "TBLU", -128, -2, "ABCD", 4),
    Case("green-armor", "Green armor animation", "GreenArmor", "ARM1", -68, 27, "AB", (6, 7),
         bright_frames="B"),
)


def map_name(case):
    return case.map_id or f"RSP{CASES.index(case) + 1:03}"


def prepare(path, cases=CASES, *, playable=False, hidden=False, flashlight=True):
    """Package isolated preview rooms using stock classes, frames and state timing."""
    members = {}
    mapinfo = ['GameInfo { AddEventHandlers = "SpriteReliefFixture" }']
    menu = [f'OptionMenu "{MENU}"', "{", '  Title "Doom II Sprite Relief Preview"']
    setup = []
    for index, case in enumerate(cases):
        name = map_name(case)
        room = Map()
        sector = room.sector(light=109)
        points = ((-224, -400), (-224, 164), (224, 164), (224, -400))
        for a, b in zip(points, points[1:] + points[:1]):
            room.line(a, b, sector)
        room.thing(1, 0, case.player_y, angle=90)
        members[f"maps/{name}.wad"] = wad(name, room.text())
        previous_map = map_name(cases[index - 1])
        next_map = map_name(cases[(index + 1) % len(cases)])
        mapinfo.append(f'map {name} "{case.title}" {{ next = "{next_map}" '
                       f'secretnext = "{previous_map}" nointermission }}')
        menu.append(f'  Command "{case.title}", "map {name}"')
        setup.extend((f'        if (level.MapName == "{name}")', "        {"))
        if case.spawn_tic > 2:
            setup.extend((f"            if (level.time < {case.spawn_tic})",
                          "            {",
                          "                lamp.Enabled[0] = FIXTURE_FLASHLIGHT;",
                          "                return;",
                          "            }"))
        setup.extend((f'            Label = "{case.title}";',
                      f'            pawn.A_SetPitch({case.pitch});',
                      f'            Subject = Actor.Spawn("{case.actor}", (0, 0, {case.z}), NO_REPLACE);',
                      '            if (Subject == null) return;',
                      f'            Subject.A_SetAngle({case.angle});'))
        if case.walking:
            setup += ['            Subject.MeleeState = null;',
                      '            Subject.MissileState = null;',
                      '            Subject.target = pawn;',
                      '            Subject.SetState(Subject.SeeState);']
        elif case.actor in ("DoomImp", "LostSoul"):
            setup += ['            OwnedNotarget = (players[0].cheats & CF_NOTARGET) == 0;',
                      '            players[0].cheats |= CF_NOTARGET;']
        if hidden:
            setup.append('            Subject.bInvisible = true;')
        setup.append("        }")

    members["MAPINFO"] = ("\n".join(mapinfo) + "\n").encode()
    if playable:
        members["MENUDEF"] = ("\n".join([*menu, "}"]) + "\n").encode()
    base_script = '''version "4.10"
class SpriteReliefFixture : EventHandler
{
    Actor Subject;
    String Label;
    bool Started;
    bool OwnedNotarget;
    override void WorldUnloaded(WorldEvent e)
    {
        if (OwnedNotarget) players[0].cheats &= ~CF_NOTARGET;
    }

    override void WorldTick()
    {
        if (level.time < 2 || players[0].mo == null) return;
        if (Started)
        {
            LOG_TIMELINE
            return;
        }
        let lamp = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
        if (lamp == null) return;
        let pawn = players[0].mo;
SETUP_ACTOR
        lamp.Enabled[0] = Subject != null && FIXTURE_FLASHLIGHT;
        Started = true;
    }
RENDER_OVERLAY
}
'''
    log_timeline = '''if (Subject != null && Subject.CurState != null)
            {
                Console.Printf("SPRITE_RELIEF_TIC %d %d %d %d %.6f %.6f %.6f %.6f %.6f",
                    level.time, int(Subject.CurState.Frame), int(Subject.CurState.Tics), Subject.tics,
                    Subject.Pos.X, Subject.Pos.Y, Subject.Pos.Z, Subject.Angle, Subject.alpha);
            }'''
    overlay = '''
    override void RenderOverlay(RenderEvent e)
    {
        if (Label == "" || e.Camera == null) return;
        let toggle = CVar.FindCVar('gl_sprite_lighting_relief');
        let lamp = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
        bool beam = lamp != null && lamp.Beams[0] != null;
        String text = String.Format("%s   |   Sprite relief %s   |   Lamp %s", Label,
            toggle != null && toggle.GetBool() ? "ON" : "OFF", beam ? "ON" : "OFF");
        Screen.DrawText(SmallFont, Font.CR_WHITE, 8, 8, text,
            DTA_VirtualWidth, 480, DTA_VirtualHeight, 360, DTA_Shadow, true);
        Screen.DrawText(SmallFont, Font.CR_WHITE, 8, 22, "R/Mid Compare   L Lamp   F1 Pick room",
            DTA_VirtualWidth, 480, DTA_VirtualHeight, 360, DTA_Shadow, true);
    }
'''
    members["ZSCRIPT"] = (base_script.replace("SETUP_ACTOR", "\n".join(setup))
                          .replace("LOG_TIMELINE", "" if playable else log_timeline)
                          .replace("FIXTURE_FLASHLIGHT", str(flashlight).lower())
                          .replace("RENDER_OVERLAY", overlay if playable else "")).encode()
    for name, color in (("LABWALL", (75, 80, 97)), ("LABFLOOR", (50, 60, 68)),
                        ("LABCEIL", (40, 48, 57))):
        namespace = "textures" if name == "LABWALL" else "flats"
        members[f"{namespace}/{name}.png"] = png(Image.new("RGB", (64, 64), color))
    with ZipFile(path, "w") as archive:
        for name, data in sorted(members.items()):
            archive.writestr(ZipInfo(name), data, compress_type=ZIP_DEFLATED)


def inspect_sprite_pack(args, pwad=None):
    originals, palette = read_wad(args.iwad, IWAD_SHA256, b"IWAD")
    shadowed = {}
    label = "DoomII"
    if pwad:
        from dbp50_effective import PWAD_SHA256

        replacements, mod_palette = read_wad(pwad, PWAD_SHA256, b"PWAD")
        originals.update(replacements)
        # DBP50 replaces this non-directional sprite with an eight-way set.
        shadowed["COL6A0"] = originals.pop("COL6A0")
        palette = mod_palette or palette
        label = "DBP50"
    decoder = SpriteDecoder(originals, palette)
    literal_sprite = re.compile(r'^material sprite "([^"]+)"\s+\{([^\n]+)\}', re.M)
    with ZipFile(args.sprites) as package:
        members = set(package.namelist())
        require(all(name == "GLDEFS" or name.startswith("sdvksprpbr/") for name in members),
                "Sprite pack contains resource types beyond material definitions and auxiliary images")
        definitions = literal_sprite.findall(package.read("GLDEFS").decode())
        names = [name for name, _ in definitions]
        require(len(set(names)) == len(names) and set(names) <= set(originals),
                "Unexpected effective sprite aliases or repeated binds")
        manifest_path = args.sprites.with_name(f"{label}-sprite-manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(manifest["package_sha256"] == sha256(args.sprites), "Sprite manifest names a different pack")
        legacy = {row["name"]: row for row in manifest["bindings"]}
        bound = {row["name"]: row for row in manifest["relief_bindings"]}
        fallbacks = {row["name"]: row for row in manifest["relief_fallbacks"]}
        excluded = {row["name"]: row["sprite_sha256"] for row in manifest.get("relief_shadowed", [])}
        require(excluded == {name: sha(data) for name, data in shadowed.items()},
                "Wrong original sprites recorded as superseded by replacement rotations")
        require(not bound.keys() & fallbacks.keys() and bound.keys() | fallbacks.keys() == originals.keys(),
                "Structural sprite inventory does not classify every stock sprite lump exactly once")
        require(set(names) == legacy.keys() | bound.keys(),
                "Stock sprite bindings disagree with the package manifest")
        frame_count = 0
        for name, row in (bound | fallbacks).items():
            width, height, left, top = struct.unpack_from("<hhhh", originals[name])
            aliases = [{"frame": name[index], "rotation": int(name[index + 1]), "mirrored": index == 6}
                       for index in range(4, len(name), 2)]
            require(row["sprite_sha256"] == sha(originals[name])
                    and row["size"] == [width, height] and row["offsets"] == [left, top]
                    and row["aliases"] == aliases, f"Incorrect original sprite identity, bounds or rotations for {name}")
            frame_count += len(aliases)
        height_names = []
        for name, layers in definitions:
            height_layer = re.search(r'\bheight "([^"]+)"', layers)
            require(bool(height_layer) == (name in bound), f"Wrong structural classification for binding {name}")
            if height_layer:
                pixels = decoder.patch(name)
                width, height = pixels.shape[1], pixels.shape[0]
                member = height_layer.group(1)
                data = package.read(member)
                require(bound[name]["height"] == member and bound[name]["height_sha256"] == sha(data),
                        f"Wrong height image or hash for {name}")
                with Image.open(BytesIO(data)) as image:
                    require(image.mode == "L" and image.size == (width, height),
                            f"Height image does not share the original sprite bounds for {name}")
                    require(not np.any(np.asarray(image)[pixels[..., 3] == 0] != 128),
                            f"Transparent source pixels have structural height for {name}")
                height_names.append(name)
    return {"original_lumps": len(originals), "material_bindings": len(names),
            "original_frame_rotation_slots": frame_count,
            "structural_height_bindings": len(height_names), "manifest_sha256": sha256(manifest_path),
            "classified_fallbacks": len(fallbacks)}


def capture(args, case, fixture, folder, mode, identity, extra_files=()):
    folder.mkdir(parents=True)
    config = folder / "clean.ini"
    config.write_text("[GlobalSettings]\nvk_rayquery=false\nvid_fullscreen=false\n", encoding="ascii")
    prefix = folder / "frame"
    width, height = map(str, SIZE)
    frames = 124 if case.finite else FRAMES
    argv = [str(args.exe), "-iwad", str(args.iwad), "-file", *map(str, extra_files), str(args.sprites), str(args.flashlight),
            str(fixture), "-stdout", "-nostartup", "-noautoload", "-noautoexec", "-nosound", "-nojoy",
            "-rngseed", "2027", "-config", str(config), "-savedir", str(folder), "-window", "-width", width,
            "-height", height, "-sdvkobserve", str(prefix), "-sdvkobservemode", "state", "-sdvkobservewarmup",
            str(WARMUP), "-sdvkobserveframes", str(frames), "-sdvkobservepngs", "-sdvkobservequit",
            "+vid_rendermode", "4", "+vid_setsize", width, height, "+gl_levelmesh", "false", "+gl_light_shadows",
            "0", "+gl_lights", "true", "+gl_ubershaders", "false", "+gl_multisample", "0", "+cl_capfps", "true",
            "+gl_spritelight", "2", "+gl_light_sprites", "true", "+r_drawplayersprites", "false", "+screenblocks",
            "12", "+crosshair", "0", "+fov", "65", "+con_notifylines", "0", "+show_messages", "false", "+use_mouse",
            "false", "+screenshot_quiet", "true", "+screenshot_type", "png", "+gl_world_relief", "false",
            "+gl_sprite_relief_depth", "0", "+gl_sprite_lighting_relief", "true" if mode == "on" else "false",
            "+gl_sprite_lighting_relief_depth", str(args.depth), "+gl_sprite_lighting_relief_orientation",
            str(args.orientation), "+gl_sprite_lighting_relief_exaggeration", str(args.exaggeration),
            "+map", map_name(case)]
    with (folder / "engine.log").open("wb") as log:
        subprocess.run(argv, cwd=args.exe.parent, stdout=log, stderr=subprocess.STDOUT, timeout=90, check=True)
    log_text = (folder / "engine.log").read_text(encoding="utf-8", errors="replace")
    require("Unknown command" not in log_text, f"Unknown console command in {folder}")
    timeline = {}
    for line in re.findall(r"^SPRITE_RELIEF_TIC ([0-9. \-]+)$", log_text, re.M):
        tic, frame, duration, tics, *coordinates = line.split()
        timeline[int(tic)] = (int(frame), int(duration), int(tics), *map(float, coordinates))
    require(timeline and (case.finite or len(timeline) >= frames),
            f"Missing contiguous actor tic evidence in {folder}")

    raw = json.loads(prefix.with_suffix(".renderer.json").read_text(encoding="utf-8"))
    build = raw["build"]
    require(raw["status"] == "COLLECTED_PENDING_VALIDATION" and raw["observed_frames"] == frames
            and raw["dropped_records"] == 0 and build["backend"] == "vulkan"
            and build["commit"] == identity and not build["vulkan"]["ray_query_enabled"],
            f"Incomplete Vulkan animation capture in {folder}")
    frame_rows = {row["frame"]: row["data"] for row in raw["records"] if row["kind"] == "frame"}
    png_rows = {row["frame"]: row["data"] for row in raw["records"] if row["kind"] == "frame-sequence"}
    require(len(frame_rows) == len(png_rows) == frames and frame_rows.keys() == png_rows.keys(),
            f"Missing native frame sequence in {folder}")
    draws = {}
    for row in raw["records"]:
        data = row["data"]
        if row["kind"] == "sprite-basis" and data["material"].upper().startswith(case.sprite):
            draws.setdefault(row["frame"], []).append(data)

    observed = {}
    for ordinal, frame in frame_rows.items():
        require((frame["width"], frame["height"]) == SIZE and frame["hardware_renderer"]
                and frame["map"] == map_name(case) and frame["relief_flashlight_lights"] == int(not args.lamp_off)
                and not frame["settings"]["gl_levelmesh"] and not frame["settings"]["gl_ubershaders"],
                f"Wrong device, camera view or flashlight in {folder}")
        shot = png_rows[ordinal]
        filename = shot["image"]
        require(filename == Path(filename).name and (folder / filename).is_file(),
                f"Missing native sequence image in {folder}")
        if mode == "background":
            require(ordinal not in draws, f"Background capture still drew {case.actor} in {folder}")
            draw = None
        else:
            matches = draws.get(ordinal, [])
            if case.finite and not matches:
                continue
            require(len(matches) == 1, f"Expected one actual {case.actor} draw at frame {ordinal} in {folder}")
            draw = matches[0]
            selected = draw["lighting_relief_mode"]
            enabled = selected != 0
            expected_enabled = mode == "on" and not case.neutral
            require(enabled == expected_enabled or (args.lamp_off and expected_enabled),
                    f"Unexpected submitted sprite lighting mode at {ordinal} in {folder}")
            if enabled:
                bright = chr(ord("A") + draw["surface"]["actor_frame"]) in case.bright_frames
                require(selected in ((5, 6) if bright else (1, 2)),
                        f"Wrong normal or fullbright structural route at {ordinal} in {folder}")
            require((draw["height_texture_index"] >= 0 and draw["structural_height"]) == case.height_bound,
                    f"Wrong original-frame height binding at {ordinal} in {folder}")
            for knob in ("depth", "orientation", "exaggeration"):
                expected = getattr(args, knob) if enabled else 0
                require(abs(draw[f"lighting_relief_{knob}"] - expected) < 1e-5,
                        f"Wrong submitted sprite relief {knob} at {ordinal} in {folder}")
        tic = frame.get("level_tic", shot.get("level_tic"))
        require(tic is not None, f"No stock simulation tic for native frame {ordinal} in {folder}")
        observed.setdefault(tic, {"image": filename, "camera": fixed_pose(frame), "draw": draw})
    return {"build": build, "argv": argv, "folder": folder, "timeline": timeline, "observed": observed}


def match_loop(case, timeline):
    durations = (case.tics,) * len(case.frames) if isinstance(case.tics, int) else case.tics
    if durations == (-1,):
        expect = (ord(case.frames) - ord("A"), -1, -1)
        require(all(state[:3] == expect for state in timeline.values()), f"Static pose changed for {case.title}")
        return 1
    repeat = [(ord(letter) - ord("A"), duration, remaining)
              for letter, duration in zip(case.frames, durations, strict=True)
              for remaining in range(duration, 0, -1)]
    start, end = min(timeline), max(timeline)
    minimum = len(repeat) - int(case.finite)
    require(end - start + 1 == len(timeline) and len(timeline) >= minimum,
            f"Incomplete consecutive gameplay tics for {case.title}")
    sequence = [timeline[tic][:3] for tic in range(start, end + 1)]
    if case.finite:
        # WorldTick observes an actor after its first tic and before its final Stop.
        require(sequence == repeat[1:] or sequence == repeat,
                f"Capture does not follow the original finite {len(repeat)}-tic sequence for {case.title}")
        return len(repeat)
    # The first map tick owns stock spawn tic randomization. Once a full
    # cycle starts, the observed state, declared tics and countdown must agree.
    match = next((index for index in range(len(sequence) - len(repeat) + 1)
                  if sequence[index:index + len(repeat)] == repeat), None)
    require(match is not None and all(state == repeat[delta % len(repeat)]
                                     for delta, state in enumerate(sequence[match:])),
            f"Capture does not follow the original {len(repeat)}-tic animation loop for {case.title}")
    return len(repeat)


def draw_identity(draw):
    return (draw["material"], draw["vertex_alpha"], draw["draw_count"],
            *(draw["surface"][key] for key in ("actor_sprite", "actor_frame", "frame_mirrored",
                                               "uv_mirror_x", "uv_mirror_y", "uv")))


def image_at(shot, tic):
    path = shot["folder"] / shot["observed"][tic]["image"]
    with Image.open(path) as source:
        require(source.size == SIZE, f"Unexpected native screenshot extent in {path}")
        return np.asarray(source.convert("RGB"), dtype=np.int16)


def compare(case, shots, output, lamp_off):
    off, on = shots["off"], shots["on"]
    common = sorted(set.intersection(*(set(shot["observed"]) & set(shot["timeline"])
                                       for shot in shots.values())))
    loop_tics = match_loop(case, off["timeline"])
    require(len(common) >= loop_tics - int(case.finite),
            f"Native images do not cover the original timing for {case.title}")
    require(all(shot["build"] == off["build"] for shot in shots.values()),
            f"Renderer or hardware changed for {case.title}")
    expected_frames = {ord(letter) - ord("A") for letter in case.frames}
    require({off["timeline"][tic][0] for tic in common} == expected_frames,
            f"Missing displayed animation positions for {case.title}")
    if case.walking:
        positions = {off["timeline"][tic][3:6] for tic in common}
        require(len(positions) >= 3, f"{case.title} never moved in captured stock ticks")

    stats = []
    examples = {}
    mirrors = set()
    for tic in common:
        a_state, b_state = off["observed"][tic], on["observed"][tic]
        actor_state = off["timeline"][tic]
        require(all(shot["timeline"][tic] == actor_state and shot["observed"][tic]["camera"] == a_state["camera"]
                    for shot in shots.values()), f"Game state or camera drift at {case.title} tic {tic}")
        require(draw_identity(a_state["draw"]) == draw_identity(b_state["draw"])
                and a_state["draw"]["surface"]["actor_frame"] == actor_state[0],
                f"Sprite material, rotation, animation state, UV or alpha drift for {case.title} tic {tic}")
        mirrors.add(a_state["draw"]["surface"]["frame_mirrored"])
        a, b = image_at(off, tic), image_at(on, tic)
        abs_delta = np.abs(a - b)
        magnitude = abs_delta.max(axis=2)
        changed = int(np.count_nonzero(magnitude))
        neutral = case.neutral or lamp_off
        require(not neutral or not changed, f"Neutral effect changed stock pixels at {case.title} tic {tic}")
        added = removed = None
        if case.coverage_check:
            bg = image_at(shots["background"], tic)
            coverage = np.any(a != bg, axis=2)
            require(np.count_nonzero(coverage) >= 30, f"Foreground coverage is absent at {case.title} tic {tic}")
            added = int(np.count_nonzero((magnitude > 2) & ~coverage))
            removed = int(np.count_nonzero((magnitude > 2) & ~np.any(b != bg, axis=2)))
            require(not added and not removed,
                    f"Sprite relief altered visible silhouette coverage for {case.title} tic {tic}")
        stats.append({"tic": tic, "material": a_state["draw"]["material"], "actor_frame": actor_state[0],
                      "state_tics": actor_state[1], "remaining": actor_state[2], "position": actor_state[3:6],
                      "lighting_relief_mode": b_state["draw"]["lighting_relief_mode"],
                      "changed_pixels": changed, "maximum_channel_delta": int(magnitude.max()),
                      "added_silhouette_pixels_over_2": added, "removed_silhouette_pixels_over_2": removed,
                      "off": a_state["image"], "on": b_state["image"]})
        if actor_state[0] not in examples or changed > examples[actor_state[0]][0]:
            examples[actor_state[0]] = (changed, tic, a, b, abs_delta)
    require(case.neutral or lamp_off or all(change > 0 for change, *_ in examples.values()),
            f"A stock animation frame had no native sprite RGB response for {case.title}")
    make_sheet(case, examples, output)
    timing_key = "original_sequence_tics" if case.finite else "stock_cycle_tics"
    return {timing_key: loop_tics, "matched_native_frames": len(common),
            "frames": stats, "mirrored_draws": sorted(mirrors)}


def make_sheet(case, examples, output):
    width, height = SIZE[0] // 2, SIZE[1] // 2
    row_size = height + 27
    sheet = Image.new("RGB", (width * 3, row_size * len(examples)), "#15191f")
    labels = ImageDraw.Draw(sheet)
    for row, (pose, (_, tic, off, on, delta)) in enumerate(sorted(examples.items())):
        panels = ((off, f"{case.title} {chr(ord('A') + pose)} / OFF"), (on, f"Tic {tic} / ON"),
                  (np.minimum(delta * 8, 255), "Absolute RGB difference x8"))
        for column, (array, label) in enumerate(panels):
            x, y = column * width, row * row_size
            labels.text((x + 6, y + 7), label, fill="white")
            card = Image.fromarray(array.astype(np.uint8)).resize((width, height), Image.Resampling.LANCZOS)
            sheet.paste(card, (x, y + 27))
    sheet.save(output / "comparison.png")


def run(args, *, available=CASES, pwad=None):
    for name in ("exe", "iwad", "sprites", "flashlight", "out"):
        setattr(args, name, getattr(args, name).resolve())
    inputs = [args.exe, args.iwad, args.sprites, args.flashlight]
    extra_files = (pwad.resolve(),) if pwad else ()
    inputs.extend(extra_files)
    require(all(path.is_file() for path in inputs), "Sprite capture input file missing")
    args.out.mkdir(parents=True)
    by_key = {case.key: case for case in available}
    cases = [by_key[key] for key in dict.fromkeys(args.case)] if args.case else available
    report = {"status": "incomplete", "started_utc": datetime.now(timezone.utc).isoformat(),
              "retained_frames": FRAMES, "warmup_frames": WARMUP, "size": SIZE,
              "flashlight": not args.lamp_off, "cases": {}}
    try:
        version = subprocess.check_output([args.exe, "--version"], cwd=args.exe.parent,
                                          text=True, encoding="utf-8", timeout=20)
        identity = re.search(r"^Commit: ([0-9a-f]{40})$", version, re.M)
        require(identity is not None, "Expected engine source identity in vkdoom --version")
        report.update(version=version, inputs={str(path): sha256(path) for path in inputs},
                      runtime_files={path.name: sha256(path) for path in sorted(args.exe.parent.glob("*.pk3"))},
                      source_files={name: sha256(Path(__file__).with_name(name)) for name in
                                    ("capture_sprite_relief.py", "capture_relief.py", "sprite_materials.py",
                                     "sprite_structural_relief.py", "gallery.py")},
                      sprite_inventory=inspect_sprite_pack(args, pwad))
        fixture = args.out / "sprite-fixture.pk3"
        prepare(fixture, cases, flashlight=not args.lamp_off)
        background_cases = [case for case in cases if case.coverage_check]
        hidden = args.out / "sprite-background.pk3"
        if background_cases:
            prepare(hidden, background_cases, hidden=True, flashlight=not args.lamp_off)
        for case in cases:
            folder = args.out / case.key
            shot_modes = {"off": fixture, "on": fixture}
            if case.coverage_check:
                shot_modes["background"] = hidden
            shots = {mode: capture(args, case, pack, folder / mode, mode, identity.group(1), extra_files)
                     for mode, pack in shot_modes.items()}
            comparison = compare(case, shots, folder, args.lamp_off)
            report["cases"][case.key] = {**asdict(case), **comparison,
                                         "build": shots["off"]["build"],
                                         "argv": {mode: shot["argv"] for mode, shot in shots.items()}}
            print(f'{case.title}: {comparison["matched_native_frames"]} matched simulation tics', flush=True)
        if "imp-left" in report["cases"] and "imp-right" in report["cases"]:
            a = report["cases"]["imp-left"]["mirrored_draws"]
            b = report["cases"]["imp-right"]["mirrored_draws"]
            require(len(a) == len(b) == 1 and a != b, "Opposite side angles did not exercise the stock mirror alias")
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
    modes = parser.add_subparsers(dest="task", required=True)
    preview = modes.add_parser("preview", help="write a playable PK3 with the stock stage rooms")
    preview.add_argument("--out", type=Path, required=True)
    native = modes.add_parser("capture", help="render native OFF/ON animation and coverage evidence")
    for name in ("exe", "iwad", "sprites", "flashlight", "out"):
        native.add_argument(f"--{name}", type=Path, required=True)
    native.add_argument("--case", action="append", choices=[case.key for case in CASES])
    native.add_argument("--lamp-off", action="store_true",
                        help="compare native OFF/ON control captures with the flashlight disabled")
    native.add_argument("--depth", type=float, default=3.5)
    native.add_argument("--orientation", type=float, default=4)
    native.add_argument("--exaggeration", type=float, default=1)
    args = parser.parse_args()
    try:
        if args.task == "preview":
            require(not args.out.exists(), "--out must name a new preview file")
            prepare(args.out, playable=True)
        else:
            run(args)
    except (KeyError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
