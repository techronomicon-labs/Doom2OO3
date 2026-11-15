"""Render the virtual-position lighting comparison in vkdoom."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from PIL import Image, ImageChops, ImageDraw, ImageStat

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "doom2_showcase"))
from gallery import Map, png, wad


SIZE = (640, 480)
DEPTHS = (0, 4, 8, 16)
SCENES = {
    "frontal": ("VPFRONT", (0, -112, 90), (0, 30, 66, 90, 17)),
    "grazing": ("VPGRAZE", (0, -112, 90), (-132, 108, 56, 7, 12)),
    "oblique": ("VPANGLE", (-55, -96, 76), (-132, 108, 56, 7, 12)),
}
MATERIALS = {"VPMETAL": "metal", "VPBRICK": "brick", "VPTILE": "tile"}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def material_images(kind):
    albedo = Image.new("RGB", (64, 64))
    height = Image.new("L", albedo.size)
    for y in range(64):
        for x in range(64):
            if kind == "metal":
                bolt = min((x-a)**2+(y-b)**2 for a in (8, 55) for b in (8, 55))
                inset = min(x, y, 63-x, 63-y)
                value = 245 if bolt < 22 else 189 if inset > 8 else 55
                color = (111, 125, 143) if inset > 6 else (80, 92, 106)
            elif kind == "brick":
                seam = y % 16 < 2 or (x + (y // 16 % 2)*16) % 32 < 3
                value = 30 if seam else 196
                color = (82, 76, 71) if seam else (139, 92, 70)
            else:
                edge = min(x % 32, y % 32, 31-x % 32, 31-y % 32)
                value = 44 if edge < 2 else 203
                color = (83, 83, 86) if edge < 2 else (119, 123, 130)
            grain = (x*13+y*17) % 7
            albedo.putpixel((x, y), tuple(channel+grain for channel in color))
            height.putpixel((x, y), value)
    return {
        "albedo": albedo, "height": height,
        "normal": Image.new("RGB", albedo.size, (128, 128, 255)),
        "metallic": Image.new("L", albedo.size, 167 if kind == "metal" else 8),
        "roughness": Image.new("L", albedo.size, 105 if kind == "metal" else 164),
        "ao": Image.new("L", albedo.size, 255),
    }


def prepare(out, mode):
    members = {}
    declarations = []
    for name, kind in MATERIALS.items():
        layers = []
        for channel, image in material_images(kind).items():
            if channel == "height" and mode == "missing":
                continue
            if channel == "height" and mode == "neutral":
                image = Image.new("L", image.size, 128)
            if channel == "albedo":
                namespace = "flats" if kind == "tile" else "textures"
                members[f"{namespace}/{name}.png"] = png(image)
            else:
                path = f"mapsamples/{name}/{channel}.png"
                members[path] = png(image)
                layers.append(f'{channel} "{path}" {{ filter linear }}')
                if channel == "height":
                    (out / f"{mode}-{name}-height.png").write_bytes(members[path])
        target = "flat" if kind == "tile" else "texture"
        declarations.append(f'material {target} {name} {{ {" ".join(layers)} }}')
    members["gldefs"] = "\n".join(declarations).encode()
    mapinfo = []
    for map_name, camera, light in SCENES.values():
        mapinfo.append(f'map {map_name} "{map_name}" {{ next = "{map_name}" }}')
        room = Map()
        sector = room.sector(ft="VPTILE", light=80)
        room.rows["sector"][sector].update(heightceiling=128, textureceiling="VPTILE")
        points = [(-160, -144), (-160, 128), (0, 128), (160, 128), (160, -144)]
        for (a, b), material in zip(zip(points, points[1:] + points[:1]),
                                   ("VPBRICK", "VPMETAL", "VPBRICK", "VPMETAL", "VPBRICK")):
            room.line(a, b, sector, texture=material)
            room.rows["sidedef"][-1]["scalex_mid"] = 1
            room.rows["sidedef"][-1]["scaley_mid"] = 1
        x, y, yaw = camera
        room.thing(1, x, y, angle=yaw)
        x, y, z, yaw, pitch = light
        room.thing(9840, x, y, z, angle=yaw, pitch=pitch, arg0=0xFFF0D8,
                   arg1=18, arg2=35, arg3=150, light_noshadowmap=True)
        members[f"maps/{map_name}.wad"] = wad(map_name, room.text())
    members["mapinfo"] = "\n".join(mapinfo).encode()
    package = out / f"{mode}.pk3"
    with ZipFile(package, "w") as archive:
        for name, data in sorted(members.items()):
            archive.writestr(ZipInfo(name), data, compress_type=ZIP_DEFLATED)
    return package, {name: hashlib.sha256(data).hexdigest() for name, data in members.items()}


def capture(args, folder, package, scene, depth, mode, commit):
    map_name = SCENES[scene][0]
    folder.mkdir()
    ini = folder / "fixture.ini"
    ini.write_text(
        "[GlobalSettings]\nvk_rayquery=false\nvid_fullscreen=false\n"
        "gl_ubershaders=false\ngl_multisample=0\n", encoding="ascii"
    )
    prefix = folder / "frame"
    command = [
        str(args.exe), "-iwad", str(args.iwad), "-file", str(package), "-stdout",
        "-nostartup", "-noautoload", "-noautoexec", "-nosound", "-nojoy", "-rngseed", "2002",
        "-config", str(ini), "-savedir", str(folder), "-window", "-width", "640", "-height", "480",
        "-sdvkobserve", str(prefix), "-sdvkobservemode", "state", "-sdvkobservewarmup", "12",
        "-sdvkobserveframes", "2", "-sdvkobservequit",
        "+vid_rendermode", "4", "+gl_levelmesh", "false", "+gl_light_shadows", "0",
        "+gl_lights", "true", "+gl_lightprobe", "false", "+gl_ubershaders", "false",
        "+r_drawplayersprites", "false", "+screenblocks", "12", "+crosshair", "0", "+fov", "90",
        "+gl_world_virtual_relief_depth", str(depth), "+map", map_name,
    ]
    with (folder / "engine.log").open("wb") as log:
        subprocess.run(command, cwd=folder, stdout=log, stderr=subprocess.STDOUT, timeout=90, check=True)
    raw = json.loads(prefix.with_suffix(".renderer.json").read_text(encoding="utf-8"))
    build = raw["build"]
    require(raw["status"] == "COLLECTED_PENDING_VALIDATION" and raw["observed_frames"] == 2
            and raw["dropped_records"] == 0 and build["backend"] == "vulkan"
            and build["commit"] == commit and build["working_tree"] == "clean"
            and not build["vulkan"]["ray_query_enabled"], f"Invalid native capture: {folder.name}")
    frames = [record["data"] for record in raw["records"] if record["kind"] == "frame"]
    require(len(frames) == 2 and all(frame["map"] == map_name and frame["hardware_renderer"]
            for frame in frames),
            "Unexpected map or renderer")
    require(all(frame["spot_lights"] == 1 and frame["settings"]["gl_light_shadows"] == 0
                and not frame["settings"]["gl_ubershaders"] for frame in frames),
            "Expected one live spotlight and the specialized shadow-off shader path")
    materials = {name: [] for name in MATERIALS}
    for record in raw["records"]:
        if record["kind"] != "material":
            continue
        data = record["data"]
        name = data["name"].upper()
        if name in materials:
            materials[name].append(data)
    for name, observations in materials.items():
        require(observations and all(row["world_virtual_relief_depth"] == depth
                and (row["height_texture_index"] >= 0) == (mode != "missing")
                for row in observations), f"Wrong height binding or depth for {name} in {folder.name}")
    path = prefix.with_suffix(".png")
    with Image.open(path) as image:
        require(image.size == SIZE and image.convert("RGB").getcolors(31) is None,
                f"Blank or wrong-size image: {path}")
    fixed = [{**{key: frame[key] for key in ("map", "settings", "walls", "flats", "spot_lights")},
              "camera": {k:v for k,v in frame["camera"].items() if k != "fraction"}} for frame in frames]
    return path, {"argv": command, "backend": build, "conditions": fixed,
                  "cpu_render_view_ms": statistics.mean(f["cpu_render_view_ms"] for f in frames),
                  "sha256": digest(path), "depth": depth, "profile": mode, "status": "PASS"}


def compare(out, name, shots):
    baseline = Image.open(shots[0][0]).convert("RGB")
    sheet = Image.new("RGB", (SIZE[0]*len(shots), SIZE[1]+26), "#171a20")
    labels = ImageDraw.Draw(sheet)
    baseline_info = shots[0][1]
    for i, (path, info) in enumerate(shots):
        require(info["conditions"] == baseline_info["conditions"] and info["backend"] == baseline_info["backend"],
                f"Capture conditions changed in {path.parent.name}")
        image = Image.open(path).convert("RGB")
        sheet.paste(image, (SIZE[0]*i, 26))
        label = "OFF (0)" if info["depth"] == 0 else str(info["depth"])
        labels.text((SIZE[0]*i+8, 7), f"{name} / {label}", fill="white")
        diff = ImageChops.difference(baseline, image)
        magnitude = ImageChops.lighter(ImageChops.lighter(*diff.split()[:2]), diff.split()[2])
        pixels = SIZE[0]*SIZE[1]-magnitude.histogram()[0]
        info["difference_vs_off"] = {"changed_pixels": pixels,
                                     "mean_rgb_delta": sum(ImageStat.Stat(diff).mean)/3,
                                     "max_rgb_delta": magnitude.getextrema()[1]}
        if i:
            require(pixels >= 32 if info["profile"] == "textured" else pixels == 0,
                    f"Unexpected difference ({pixels} pixels): {path.parent.name}")
            target = Image.new("RGB", (SIZE[0], SIZE[1]+26), "#171a20")
            target.paste(diff.point([min(255, x*8) for x in range(256)]*3), (0, 26))
            ImageDraw.Draw(target).text((8, 7), f"{name}: {label} vs OFF | absolute RGB x8, clipped", fill="white")
            target.save(out / f"{name}-{info['depth']}-difference.png")
    sheet.save(out / f"{name}-contact.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--iwad", type=Path, required=True, help="Freedoom Phase 2 IWAD")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.exe, args.iwad, args.out = (p.resolve() for p in (args.exe, args.iwad, args.out))
    args.out.mkdir()
    report = {"status": "FAIL", "size": SIZE, "seed": 2002, "warmup": 12,
              "retained_frames": 2, "fov": 90, "scenes": SCENES, "captures": {}}
    try:
        version = subprocess.check_output([args.exe, "--version"], cwd=args.out, text=True, timeout=20)
        commit = re.search(r"^Commit: ([0-9a-f]{40})$", version, re.M).group(1)
        report.update(source=commit, executable=digest(args.exe), iwad=digest(args.iwad),
                      engine_packages={p.name:digest(p) for p in args.exe.parent.glob("*.pk3")})
        for mode in ("textured", "neutral", "missing"):
            package, members = prepare(args.out, mode)
            report[f"{mode}_fixture"] = {"sha256": digest(package), "members": members}
            for scene in SCENES if mode == "textured" else ("frontal",):
                name = f"{scene}-{mode}"
                shots = []
                for depth in DEPTHS if mode == "textured" else (0, 16):
                    folder = args.out / f"{name}-{depth}"
                    report["captures"][folder.name] = {"status":"PENDING","depth":depth}
                    shot = capture(args, folder, package, scene, depth, mode, commit)
                    report["captures"][folder.name] = shot[1]
                    shots.append(shot)
                compare(args.out, name, shots)
        report["status"] = "PASS"
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        report["files"] = {p.relative_to(args.out).as_posix(): digest(p) for p in args.out.rglob("*") if p.is_file()}
        (args.out / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
