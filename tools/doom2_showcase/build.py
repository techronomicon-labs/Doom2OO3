"""Build the optional flashlight and local Doom II/DBP50 material add-ons."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

FLASHLIGHT_FILES = ("ZSCRIPT", "CVARINFO", "DEFCVARS", "MAPINFO", "KEYCONF", "MENUDEF")
HEROES = [
    "DOOR3",
    "SW1METAL",
    "BIGDOOR6",
    "WOODMET2",
    "TEKBRON1",
    "BRWINDOW",
    "SW1WOOD",
    "BRICK7",
]
FEATURE_PAGES = [
    (
        "SGSWITCH",
        "SWITCHES - metal housing, dielectric actuator",
        ["SW1METAL", "SW2METAL", "SW1WOOD", "SW1MARB", "SW1COMP", "SW1SKULL"],
    ),
    (
        "SGDOORS",
        "DOORS - steel versus wood and iron hardware",
        ["DOOR3", "EXITDOOR", "ZELDOOR", "BIGDOOR6", "DOOR1", "WOODMET2"],
    ),
    (
        "SGMIXED",
        "MIXED SURFACES - brick, wood and paint",
        ["WOODMET2", "BRWINDOW", "CRATE1", "TEKBRON1", "GRAY1", "BRICK7"],
    ),
]
CHANNELS = ("normal", "metallic", "roughness", "ao")


def build_flashlight(out):
    source = Path(__file__).resolve().parent / "flashlight"
    with ZipFile(out / "Local-Flashlight.pk3", "w") as package:
        for name in FLASHLIGHT_FILES:
            member = ZipInfo(name)
            member.compress_type = ZIP_DEFLATED
            package.writestr(
                member, (source / name).read_text(encoding="utf-8").encode("utf-8")
            )


def fixture_brightmap(row):
    from material_generator import np
    from stageb_layout import FLAT_FIXTURES, WALL_FIXTURES

    fixtures = FLAT_FIXTURES if row["kind"] == "flat" else WALL_FIXTURES
    fixture = fixtures.get(row["name"])
    if fixture is None:
        return None
    pixels = row["pixels"]
    mask = np.zeros(pixels.shape[:2], dtype=np.uint8)
    for x0, y0, x1, y1 in fixture.regions:
        source = pixels[y0:y1, x0:x1]
        red, green, blue, alpha = source.astype(np.int32).transpose(2, 0, 1)
        if row["name"] == "TEKGREN5":
            value = 190 * ((red == 255) & (green == 255) & (blue < 224))
        elif row["name"] == "EXITSIGN":
            value = np.where((red >= 48) & (red > 2 * np.maximum(green, blue)), 72 + red // 4, 0)
        else:
            peak = np.maximum(np.maximum(red, green), blue)
            value = np.clip((peak - 104) * 1.12, 0, 154)
        mask[y0:y1, x0:x1] = np.where(alpha == 255, value, 0)
    return mask if mask.any() else None


def dbp50_material_inputs(effective_rows, original, replacement, include_unchanged=False):
    """Yield effective art and switch context for material and relief generation."""
    import dbp50_effective as dbp
    import wall_materials as walls

    rows = {(row["kind"], row["name"]): row for row in effective_rows}
    decoder = dbp._IndexedOverlay(original | replacement)
    tables = dbp.texture_overrides(original, replacement)
    definitions = walls.definitions(original)
    if tables:
        definitions.update(walls.definitions(tables))
    for row in effective_rows:
        if (include_unchanged or row["rgba_changed"]) and not row["placeholder"]:
            yield row, walls.context(row, rows, definitions, decoder)


def world_relief(row, family, context):
    from relief_flat_profiles import height_map as flat_height
    from relief_wall_profiles import height_map as wall_height
    from structural_relief import height_map as authored_height

    kind, name, pixels = row["kind"], row["name"], row["pixels"]
    hand_drawn = authored_height(kind, name, pixels)
    if hand_drawn is not None:
        data, profile = hand_drawn
        return data, profile, "hand-authored"
    profile = (
        flat_height(name, pixels) if kind == "flat" else wall_height(row, family, context)
    )
    if profile is None:
        return None, "No reliable structure identified", "neutral"
    data, label = profile
    return data, label, "material profile" if data is not None else "neutral"


def write_wall_pack(out, game, entries, shared, overrides, heights):
    definitions = []
    restriction = "iwad " if game == "DoomII" else ""
    with ZipFile(out / f"{game}-NormalPBR.pk3", "w", ZIP_DEFLATED) as package:
        for entry in entries:
            if entry["placeholder"]:
                continue
            key = entry["kind"], entry["name"]
            target = "texture" if key[0] == "wall" else "flat"
            data = overrides[key] if key in overrides else shared[key]
            if key in heights:
                data = dict(data, height=heights[key])
            paths = {
                channel: f"sdvkwallpbr/{entry['id']:04}/{channel}.png"
                for channel in data
            }
            for channel, path in paths.items():
                package.writestr(path, data[channel])
            layers = " ".join(
                f'{channel} "{path}" {{ filter {"nearest" if channel == "brightmap" else "linear"} }}'
                for channel, path in paths.items()
            )
            definitions.append(
                f"material {target} {key[1]} {{ {restriction}{layers} }}"
            )
        package.writestr("GLDEFS", "\n".join(definitions) + "\n")
    return len(definitions)


def build_materials(out, iwad, pwad, include_gallery, include_relief=False, include_sprite_relief=False,
                    include_emitters=False):
    from PIL import Image

    import dbp50_effective as dbp
    import material_generator as base
    import sprite_materials as sprites
    import wall_materials as walls
    from material_profiles_v2 import build_channels

    stock_sprites, palette = sprites.read_wad(iwad, dbp.IWAD_SHA256, b"IWAD")
    mod_sprites, mod_palette = ({}, None)
    if pwad:
        mod_sprites, mod_palette = sprites.read_wad(pwad, dbp.PWAD_SHA256, b"PWAD")

    def wall_maps(row, original_family, context):
        maps, info = build_channels(
            row["pixels"], row["name"], row["kind"], original_family, context
        )
        walls.validate_maps(maps, row["pixels"])
        return maps, info

    wad = base.Wad(iwad)
    rows = sorted(
        wad.textures() + wad.flats(), key=lambda row: (row["kind"], row["name"])
    )
    lookup = {name: wad.lump(name) for name in wad.by_name}
    definitions = walls.definitions(lookup)
    by_key = {(row["kind"], row["name"]): row for row in rows}
    shared = {}
    doomii_overrides = {}
    heights = {}
    relief_profiles = []
    relief_fallbacks = []
    entries = []
    gallery_entries = []
    for ordinal, row in enumerate(rows, 1):
        kind, name = row["kind"], row["name"]
        key = kind, name
        family = base.family_of(name, kind)
        entry = {k: row[k] for k in ("kind", "name", "source_index", "placeholder")}
        entry.update(id=ordinal, family=family)
        entries.append(entry)
        if not entry["placeholder"] or include_gallery:
            context = walls.context(row, by_key, definitions, wad)
            maps, info = wall_maps(row, family, context)
            shared[key] = {
                channel: sprites.png(base.np.asarray(maps[channel]))
                for channel in CHANNELS
            }
            if include_emitters:
                brightmap = fixture_brightmap(row)
                if brightmap is not None:
                    doomii_overrides[key] = dict(shared[key], brightmap=sprites.png(brightmap))
        if include_relief:
            if entry["placeholder"]:
                relief_fallbacks.append(
                    dict(kind=kind, name=name, reason="IWAD placeholder")
                )
            else:
                data, profile, method = world_relief(row, info["family"], context)
                if data is None:
                    relief_fallbacks.append(dict(kind=kind, name=name, reason=profile))
                else:
                    heights[key] = sprites.png(data)
                    relief_profiles.append(
                        dict(kind=kind, name=name, profile=profile, method=method)
                    )
        if include_gallery:
            folder = out / "gallery-art" / f"{ordinal:04}"
            folder.mkdir(parents=True)
            images = {"albedo": Image.fromarray(row["pixels"]), **maps}
            paths = {}
            for channel, image in images.items():
                path = folder / f"{channel}.png"
                image.save(path)
                paths[channel] = path.relative_to(out).as_posix()
            height, width = row["pixels"].shape[:2]
            gallery_entries.append(
                dict(
                    entry,
                    family=info["family"],
                    width=width,
                    height=height,
                    files=paths,
                    aliases={
                        "legacy": f"L{ordinal:07d}",
                        "normal": f"N{ordinal:07d}",
                        "pbr": f"P{ordinal:07d}",
                    },
                )
            )

    report = {}
    count = write_wall_pack(out, "DoomII", entries, shared, doomii_overrides, heights)
    manifest = sprites.build(out, "DoomII", stock_sprites, palette, set(), include_relief=include_sprite_relief)
    report["DoomII"] = {
        "world_bindings": count,
        "sprite_bindings": len(manifest["bindings"]),
    }
    if include_relief:
        from capture_relief import prepare, preview_scenes

        preview = out / "DoomII-Relief-Preview.pk3"
        prepare(preview, preview_scenes(), playable=True)
        report["DoomII"]["relief_profiles"] = relief_profiles
        report["DoomII"]["relief_fallbacks"] = relief_fallbacks
    if include_sprite_relief:
        from capture_sprite_relief import prepare as prepare_sprite_preview

        prepare_sprite_preview(out / "DoomII-Sprite-Relief-Preview.pk3", playable=True)
        report["DoomII"]["sprite_relief_bindings"] = len(manifest["relief_bindings"])
        report["DoomII"]["sprite_relief_fallbacks"] = len(manifest["relief_fallbacks"])

    if include_emitters:
        from stageb_lighting import build as build_emitter_layout

        build_emitter_layout(out / "DoomII-Emitter-Lighting.pk3", iwad=iwad)

    if pwad:
        effective_rows = dbp.effective_rows(iwad, pwad, entries, include_custom=include_relief)
        mod_lookup = dbp._lumps(pwad, dbp.PWAD_SHA256, b"PWAD")
        overrides = {}
        contexts = {}
        for row, context in dbp50_material_inputs(effective_rows, lookup, mod_lookup, include_relief):
            key = row["kind"], row["name"]
            contexts[key] = context
            if not row["rgba_changed"] and not row.get("custom", False):
                continue
            maps, _ = wall_maps(row, row["family"], context)
            overrides[key] = {
                channel: sprites.png(base.np.asarray(maps[channel]))
                for channel in CHANNELS
            }
        dbp_heights = {}
        dbp_profiles = []
        dbp_fallbacks = []
        if include_relief:
            from dbp50_structural_relief import height_profiles

            for key, (data, label, method) in height_profiles(effective_rows, contexts, world_relief).items():
                kind, name = key
                if data is None:
                    dbp_fallbacks.append(dict(kind=kind, name=name, reason=label))
                else:
                    dbp_heights[key] = sprites.png(data)
                    dbp_profiles.append(dict(kind=kind, name=name, profile=label, method=method))

        count = write_wall_pack(out, "DBP50", effective_rows, shared, overrides, dbp_heights)
        manifest = sprites.build(
            out,
            "DBP50",
            stock_sprites | mod_sprites,
            mod_palette or palette,
            set(mod_sprites),
            include_relief=include_sprite_relief,
        )
        report["DBP50"] = {
            "world_bindings": count,
            "sprite_bindings": len(manifest["bindings"]),
            "adapted_world_bindings": len(overrides),
        }
        if include_relief:
            report["DBP50"]["relief_profiles"] = dbp_profiles
            report["DBP50"]["relief_fallbacks"] = dbp_fallbacks
        if include_sprite_relief:
            report["DBP50"]["sprite_relief_bindings"] = len(manifest["relief_bindings"])
            report["DBP50"]["sprite_relief_fallbacks"] = len(manifest["relief_fallbacks"])

    if include_gallery:
        import gallery

        gallery.build(
            {
                "entries": gallery_entries,
                "iwad": iwad.name,
                "iwad_sha256": dbp.IWAD_SHA256,
            },
            out,
            HEROES,
            FEATURE_PAGES,
        )
    (out / "material-build.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    if include_relief:
        print(f"Built {len(relief_profiles)} Doom II height maps and recorded "
              f"{len(relief_fallbacks)} neutral entries in material-build.json.")
        if pwad:
            print(f"Built {len(dbp_profiles)} DBP50 height maps and recorded "
                  f"{len(dbp_fallbacks)} neutral entries in material-build.json.")
    else:
        print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new output directory")
    parser.add_argument("--doom2", type=Path, help="owner-supplied Doom II IWAD")
    parser.add_argument("--dbp50", type=Path, help="owner-supplied DBP50 PWAD")
    parser.add_argument(
        "--gallery",
        action="store_true",
        help="also build the wall and flat comparison gallery",
    )
    parser.add_argument(
        "--relief",
        action="store_true",
        help="build structural-height materials for Doom II and the supplied DBP50 WAD",
    )
    parser.add_argument(
        "--sprite-relief",
        action="store_true",
        help="build sprite lighting relief for Doom II and the supplied DBP50 WAD",
    )
    parser.add_argument("--emitter-lighting", action="store_true",
                        help="build emitter lighting for the Doom II campaign and comparison rooms")
    args = parser.parse_args()
    if (args.dbp50 or args.gallery or args.relief or args.sprite_relief or args.emitter_lighting) and not args.doom2:
        parser.error("--dbp50, --gallery, --relief, --sprite-relief and --emitter-lighting require --doom2")
    out = args.out.resolve()
    if out.exists():
        parser.error("--out must name a new directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with TemporaryDirectory(prefix=".doom2-showcase-", dir=out.parent) as staging:
            prepared = Path(staging) / "build"
            prepared.mkdir()
            build_flashlight(prepared)
            if args.doom2:
                build_materials(prepared, args.doom2, args.dbp50, args.gallery,
                                args.relief, args.sprite_relief, args.emitter_lighting)
            prepared.rename(out)
    except (OSError, ValueError, ImportError) as error:
        parser.exit(1, f"{error}\n")
    print(f"Built add-ons in {out}")


if __name__ == "__main__":
    main()
