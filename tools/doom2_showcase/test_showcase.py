"""Copyright-free regression checks for the optional add-on builder."""

from pathlib import Path
import re
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from zipfile import ZipFile

import numpy as np
from PIL import Image

import build
from capture_relief import MATERIALS, NEUTRAL_CONTROLS, UNBOUND_CONTROLS, prepare, preview_scenes
from dbp50_effective import reconstruct_rows
import gallery
from material_generator import Wad, family_of
from material_profiles_v2 import build_channels, cpu_controls
from relief_flat_profiles import height_map as flat_height_map
from relief_wall_profiles import height_map as wall_height_map
from sprite_materials import maps_for
from sprite_structural_relief import SpriteRelief
from structural_relief import height_map
from wall_materials import context as wall_context


IWAD = Path(__file__).resolve().parents[2] / "assets" / "wads" / "doom2.wad"


def switch_fixture():
    palette = bytearray(768)
    palette[3:9] = bytes((64, 64, 64, 192, 20, 12))
    texture = struct.pack("<8sIhhIh", b"SW1TEST", 0, 2, 2, 0, 1)
    texture += struct.pack("<hhhhh", 0, 0, 0, 0, 0)
    original = {
        "PLAYPAL": bytes(palette),
        "PNAMES": struct.pack("<i8s", 1, b"SWPATCH"),
        "TEXTURE1": struct.pack("<ii", 1, 8) + texture,
        "SWPATCH": patch(1),
    }
    entries = [dict(name="SW1TEST", kind="wall", family="metal", id=1)]
    return original, entries


def patch(color):
    column = bytes((0, 2, 0, color, color, 0, 255))
    return struct.pack("<hhhhII", 2, 2, 0, 0, 16, 23) + column * 2


class ShowcaseTests(unittest.TestCase):
    def test_dbp50_material_pack_accepts_mod_only_flat(self):
        entry = dict(kind="flat", name="DBTEST", id=579, placeholder=False)
        key = "flat", "DBTEST"
        with TemporaryDirectory() as scratch:
            out = Path(scratch)
            count = build.write_wall_pack(out, "DBP50", [entry], {}, {key: {"normal": b"mod"}}, {key: b"height"})
            self.assertEqual(count, 1)
            with ZipFile(out / "DBP50-NormalPBR.pk3") as archive:
                self.assertIn(b"material flat DBTEST", archive.read("GLDEFS"))
                self.assertEqual(archive.read("sdvkwallpbr/0579/normal.png"), b"mod")
                self.assertEqual(archive.read("sdvkwallpbr/0579/height.png"), b"height")

    def test_flashlight_package_contains_only_addon_sources(self):
        with TemporaryDirectory() as scratch:
            out = Path(scratch)
            build.build_flashlight(out)
            with ZipFile(out / "Local-Flashlight.pk3") as package:
                self.assertEqual(tuple(package.namelist()), build.FLASHLIGHT_FILES)
                self.assertIsNone(package.testzip())

    def test_wrong_iwad_leaves_no_output(self):
        with TemporaryDirectory() as scratch:
            source = Path(scratch) / "doom2.wad"
            source.write_bytes(b"not the supported WAD")
            out = Path(scratch) / "output"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    build.__file__,
                    "--doom2",
                    str(source),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unexpected WAD identity", result.stderr)
            self.assertFalse(out.exists())

    def test_material_semantics(self):
        self.assertEqual(cpu_controls()["status"], "PASS")
        pixels = np.full((16, 24, 4), (96, 96, 96, 255), dtype=np.uint8)
        pixels[:, :3, 3] = 0
        pixels[4:8, 8:16, :3] = 144
        gun = maps_for(pixels, "weapon", "PISGA0")
        flesh = maps_for(pixels, "flesh", "TROOA1")
        self.assertGreater(gun["metallic"][6, 10], 150)
        self.assertLess(flesh["metallic"][6, 10], 15)
        self.assertLess(gun["roughness"][6, 10], flesh["roughness"][6, 10])
        self.assertEqual(gun["normal"].shape, (16, 24, 3))
        length = np.linalg.norm(gun["normal"].astype(float) / 127.5 - 1, axis=2)
        self.assertTrue(np.all(np.abs(length - 1) < 0.015))

    def test_structural_height_uses_authored_joints_and_wraps(self):
        art = np.full((128, 64, 4), 255, dtype=np.uint8)
        art[8:12, 14:18, :3] = 0  # a painted spot in a brick face
        data, _ = height_map("wall", "BRICK7", art)
        self.assertEqual(data.shape, (256, 128))
        self.assertEqual(data[20, 32], 128)
        self.assertLess(data[20, 64], 50)  # staggered joint in first course
        self.assertGreater(data[20, 60], data[20, 64])  # bevel meets that joint
        self.assertTrue(np.array_equal(data[:, 0], data[:, -1]))
        self.assertTrue(np.array_equal(data[0], data[-1]))
        self.assertIsNone(height_map("wall", "BRICK2", art))
        art[0, 0, 3] = 0
        self.assertIsNone(height_map("wall", "BRICK7", art))

    def test_stock_relief_profiles_match_their_surface_features(self):
        art = np.full((128, 64, 4), 255, dtype=np.uint8)
        thin_brick, _ = height_map("wall", "BRICK1", art)
        self.assertLess(thin_brick[16, 40], thin_brick[8, 40])
        fracture, _ = height_map("wall", "BRICK4", art)
        self.assertLess(fracture[18, 90], fracture[24, 84])
        self.assertEqual(fracture[9, 45], 128)
        wood8, _ = height_map("wall", "WOOD8", art)
        wood9, _ = height_map("wall", "WOOD9", art)
        self.assertTrue(np.array_equal(wood8, wood9))
        self.assertIsNone(height_map("flat", "FLAT5_5", art[:64]))

    def test_entryway_wall_relief_follows_trim_and_fasteners(self):
        art = np.full((128, 64, 4), 255, dtype=np.uint8)
        trim, _ = wall_height_map({"name": "BROWNGRN", "pixels": art}, "painted panels", {})
        self.assertLess(trim[64, 40], trim[76, 40])
        self.assertGreater(trim[32, 16], trim[32, 30])
        self.assertEqual(trim[120, 40], 128)

        plates, _ = wall_height_map({"name": "SPACEW4", "pixels": art}, "painted technology", {})
        self.assertLess(plates[38, 64], plates[38, 40])
        self.assertLess(plates[23, 9], plates[23, 20])
        np.testing.assert_array_equal(plates[:, 0], plates[:, -1])

    def test_switch_phase_keeps_relief_on_the_same_backing(self):
        red = np.full((128, 64, 4), (110, 100, 95, 255), dtype=np.uint8)
        green = red.copy()
        red[74:82, 24:32, :3] = (180, 45, 25)
        green[74:82, 24:32, :3] = (45, 180, 25)
        first, _ = wall_height_map({"name": "SW1BRNGN", "pixels": red}, "painted panels", {"paired_pixels": green})
        second, _ = wall_height_map({"name": "SW2BRNGN", "pixels": green}, "painted panels", {"paired_pixels": red})
        np.testing.assert_array_equal(first, second)
        self.assertLess(first[31, 40], first[39, 40])
        self.assertGreater(first[77, 28], first[77, 50])

    def test_switch_plate_replaces_the_wall_seam_in_both_states(self):
        first = np.full((128, 128, 4), (110, 100, 95, 255), dtype=np.uint8)
        second = first.copy()
        first[77:85, 54:64, :3] = (180, 40, 20)
        second[77:85, 54:64, :3] = (80, 10, 10)
        mask = np.zeros(first.shape[:2], dtype=np.float32)
        mask[72:104, 48:80] = 1.0
        fields, normals = [], []
        for name, art, other, patch in (
            ("SW1BRCOM", first, second, "SW1S0"), ("SW2BRCOM", second, first, "SW1S1"),
        ):
            context = {"paired_pixels": other, "switch_mask": mask, "switch_patch": (48, 72, patch)}
            fields.append(wall_height_map({"name": name, "pixels": art}, "painted panels", context)[0])
            normals.append(np.asarray(build_channels(art, name, "wall", "painted panels", context)[0]["normal"]))

        np.testing.assert_array_equal(fields[0], fields[1])
        np.testing.assert_array_equal(normals[0], normals[1])
        # The brown wall still has a join at U=64 above the switch.
        self.assertLess(fields[0][120, 128], fields[0][120, 120])
        # The steel face crosses the same U=64 line without inheriting it.
        self.assertEqual(np.ptp(fields[0][176, 120:137]), 0)
        np.testing.assert_array_equal(normals[0][352, 241:269, :2], np.full((28, 2), 128))

    def test_carved_switch_states_use_their_own_patch_ownership(self):
        backing = np.full((128, 64, 4), (56, 47, 40, 255), dtype=np.uint8)
        device = np.full((128, 40, 4), (120, 100, 90, 255), dtype=np.uint8)
        lit = device.copy()
        lit[12:17, 13:27, :3] = (130, 15, 12)
        patches = {"WALL47_2": backing, "WALL42_6": device, "WALL47_5": lit}
        decoder = SimpleNamespace(patch=patches.__getitem__)
        rows, definitions = {}, {}
        for name, patch_name in (("SW1GARG", "WALL42_6"), ("SW2GARG", "WALL47_5")):
            art = backing.copy()
            art[62:, 12:52] = patches[patch_name][:66]
            rows["wall", name] = {"kind": "wall", "name": name, "pixels": art}
            definitions[name] = (64, 128, [(0, 0, "WALL47_2"), (12, 62, patch_name)])

        expected = np.zeros((128, 64), dtype=np.float32)
        expected[62:, 12:52] = 1
        fields = []
        for row in rows.values():
            context = wall_context(row, rows, definitions, decoder)
            np.testing.assert_array_equal(context["switch_mask"], expected)
            fields.append(wall_height_map(row, "carved stone", context)[0])
        np.testing.assert_array_equal(fields[0], fields[1])
        self.assertGreater(fields[0][82, 32], fields[0][82, 10])

    def test_painted_door_marks_do_not_warp_the_metal_normal(self):
        door = np.full((96, 128, 4), (100, 100, 100, 255), dtype=np.uint8)
        decorated = door.copy()
        decorated[30:61, 18:92, :3] = (173, 117, 53)
        decorated[34:55:4, 28:83:3, :3] = (54, 32, 16)
        plain, _ = build_channels(door, "BIGDOOR1", "wall", "metal")
        painted, _ = build_channels(decorated, "BIGDOOR1", "wall", "metal")
        np.testing.assert_array_equal(plain["normal"], painted["normal"])
        self.assertTrue(np.any(np.asarray(painted["normal"])[:, :, :2] != 128))
        self.assertLess(np.asarray(painted["metallic"]).max(), 128)
        self.assertGreaterEqual(np.asarray(painted["roughness"]).min(), 124)

    def test_tekgren_lamp_stripes_share_a_plane(self):
        wall = np.full((128, 64, 4), (61, 65, 48, 255), dtype=np.uint8)
        wall[4:12, 4:60, :3] = (238, 209, 44)
        wall[4:12, 5:60:2, :3] = (255, 255, 215)
        field, _ = wall_height_map({"name": "TEKGREN5", "pixels": wall}, "painted technology", {})
        self.assertEqual(np.ptp(field[15:17, 18:110]), 0)
        self.assertGreater(field[8, 35], field[16, 35])

    def test_relief_preview_cycles_and_links_all_rooms(self):
        rooms = preview_scenes()
        names = [room.map_name for room in rooms]
        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "preview.pk3"
            prepare(path, rooms, playable=True)
            with ZipFile(path) as archive:
                maps = archive.read("MAPINFO").decode()
                next_rooms = re.findall(r'\bnext = "(RPV\d+)"', maps)
                previous_rooms = re.findall(r'\bsecretnext = "(RPV\d+)"', maps)
                self.assertEqual(next_rooms, names[1:] + names[:1])
                self.assertEqual(previous_rooms, names[-1:] + names[:-1])
                menu = archive.read("MENUDEF").decode()
                for name in names:
                    self.assertIn(f'"map {name}"', menu)

    @unittest.skipUnless(IWAD.is_file(), "requires the local Doom II IWAD")
    def test_relief_capture_controls_match_stock_height_profiles(self):
        wad = Wad(IWAD)
        names = UNBOUND_CONTROLS | {"CEIL5_2"}
        rows = {row["name"]: row for row in wad.textures() + wad.flats()
                if row["name"] in names}
        for name in names:
            with self.subTest(material=name):
                row = rows[name]
                self.assertEqual(MATERIALS[name][1], row["kind"])
                self.assertTrue(np.all(row["pixels"][:, :, 3] == 255))
                data, _, _ = build.world_relief(row, family_of(name, row["kind"]), {})
                self.assertEqual(data is None, name in UNBOUND_CONTROLS)
                self.assertEqual(data is None, name in NEUTRAL_CONTROLS)

    def test_entryway_tile_relief_matches_authored_source_joints(self):
        art = np.full((64, 64, 4), 255, dtype=np.uint8)
        field, _ = flat_height_map("FLOOR0_1", art)
        for name in ("FLOOR0_2", "FLOOR0_3"):
            np.testing.assert_array_equal(field, flat_height_map(name, art)[0])

        # Coordinates are in the original 64×64 flat. The shared map is 2×.
        for x, y in ((35.5, 27), (0, 17), (63.5, 17), (24, 53.75), (22, 24.75)):
            self.assertLess(field[int(2 * y), int(2 * x)], 64, (x, y))
        for x, y in ((42, 27), (0, 38), (0, 53.75)):
            self.assertEqual(field[int(2 * y), int(2 * x)], 128, (x, y))

    def test_sprite_loop_retains_height_at_shared_origin_with_changing_bounds(self):
        class Decoder:
            def patch(self, name):
                return art[name]

        a, b = "BON2A0", "BON2B0"
        poses = {a: struct.pack("<hhhh", 14, 14, 7, 14),
                 b: struct.pack("<hhhh", 16, 16, 9, 16)}
        art = {a: np.full((14, 14, 4), 255, dtype=np.uint8),
               b: np.full((16, 16, 4), 255, dtype=np.uint8)}
        relief = SpriteRelief(poses, Decoder())
        first, _ = relief.height(a, art[a])
        second, _ = relief.height(b, art[b])
        np.testing.assert_array_equal(first, second[2:, 2:])
        self.assertGreater(int(first[7, 7]), 128)
        self.assertTrue(np.all(second[:2, :] == 128))
        self.assertTrue(np.all(second[:, :2] == 128))

    def test_palette_only_change_selects_override(self):
        original, entries = switch_fixture()
        palette = bytearray(original["PLAYPAL"])
        palette[3:6] = bytes((136, 25, 18))
        replacement = {"PLAYPAL": bytes(palette)}
        rows = reconstruct_rows(original, replacement, {}, entries)
        self.assertTrue(rows[0]["rgba_changed"])
        self.assertFalse(rows[0]["pattern_changed"])
        [(row, context)] = build.dbp50_material_inputs(rows, original, replacement)
        self.assertEqual(tuple(row["pixels"][0, 0]), (136, 25, 18, 255))
        self.assertTrue(np.all(context["switch_mask"] == 1))
        unchanged = reconstruct_rows(original, {}, {}, entries)
        self.assertEqual(list(build.dbp50_material_inputs(unchanged, original, {})), [])

    def test_switch_patch_uses_inherited_definition(self):
        original, entries = switch_fixture()
        replacement = {"SWPATCH": patch(2)}
        rows = reconstruct_rows(original, replacement, {}, entries)
        self.assertTrue(rows[0]["pattern_changed"])
        [(row, context)] = build.dbp50_material_inputs(rows, original, replacement)
        self.assertEqual(tuple(row["pixels"][0, 0]), (192, 20, 12, 255))
        self.assertTrue(np.all(context["switch_mask"] == 1))

    def test_gallery_archive_resources_and_navigation(self):
        with TemporaryDirectory() as scratch:
            out = Path(scratch)
            channels = ("albedo", "normal", "specular", "metallic", "roughness", "ao")
            files = {}
            for channel in channels:
                filename = f"{channel}.png"
                Image.new("RGBA", (16, 16), (120, 96, 48, 255)).save(out / filename)
                files[channel] = filename
            entry = dict(
                name="SW1TEST",
                kind="wall",
                family="metal",
                width=16,
                height=16,
                files=files,
                aliases={"legacy": "L0000001", "normal": "N0000001", "pbr": "P0000001"},
            )
            gallery.build(
                {"entries": [entry], "iwad": "synthetic", "iwad_sha256": "synthetic"},
                out,
                ["SW1TEST"],
                [("SGSWITCH", "Switches", ["SW1TEST"])],
            )
            with ZipFile(out / "DoomII-Material-Gallery.pk3") as package:
                self.assertIsNone(package.testzip())
                names = set(package.namelist())
                mapinfo = package.read("MAPINFO").decode()
                maps = re.findall(r"(?m)^map (\w+)", mapinfo)
                self.assertEqual(maps, ["SGSHOW", "SGSWITCH", "SG0002"])
                self.assertEqual(
                    re.findall(r'(?m)^  next = "(\w+)"', mapinfo), maps[1:] + maps[:1]
                )
                self.assertEqual(
                    re.findall(r'(?m)^  secretnext = "(\w+)"', mapinfo),
                    maps[-1:] + maps[:-1],
                )
                menu = package.read("MENUDEF").decode()
                for name in maps:
                    self.assertIn(f'"map {name}"', menu)
                    data = package.read(f"maps/{name}.wad")
                    self.assertEqual(data[:4], b"PWAD")
                    self.assertIn(b"TEXTMAP", data)
                    self.assertIn(b"ENDMAP", data)
                gldefs = package.read("GLDEFS").decode()
                self.assertTrue(set(re.findall(r'"([^"]+)"', gldefs)) <= names)
                for alias in entry["aliases"].values():
                    self.assertIn(f"textures/{alias}.png", names)
                self.assertIn("MaterialGalleryMenu", package.read("KEYCONF").decode())
            self.assertIn("SW1TEST", (out / "INDEX.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
