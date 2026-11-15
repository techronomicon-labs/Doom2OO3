"""Focused asset/runner contracts. These are not native visual qualification."""
import copy
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.shadow001 import prepare_demo as demo
from tools.shadow001 import run_demo


class DemoTests(unittest.TestCase):
    def test_source_silhouette_has_leg_and_arm_gaps_and_rifle(self):
        data = demo.humanoid_pixels(0)
        alpha = lambda x, y: data[(y*48+x)*4+3]
        self.assertEqual(len(data), 48*64*4)
        self.assertTrue(all(a in (0, 255) for a in data[3::4]))
        self.assertTrue(all(alpha(23, y) == 0 for y in range(40, 64)))
        self.assertEqual(alpha(13, 28), 0)  # hole between arm and torso
        self.assertEqual(alpha(45, 30), 255)  # recognisable asymmetric rifle
        self.assertEqual(alpha(0, 30), 0)
        self.assertEqual(alpha(17, 63), 255)  # anchored boot/pivot

    def test_rotations_are_distinct_and_use_actual_mirror_names(self):
        files, _ = demo.members(demo.CASES["projected"])
        sprites = {name: data for name, data in files.items() if name.startswith("sprites/")}
        self.assertEqual(set(sprites), {"sprites/SHD1A"+r+".png" for r in demo.ROTATIONS})
        self.assertEqual(len(set(sprites.values())), 5)
        for image in sprites.values():
            self.assertEqual(struct.unpack_from(">II", image, 16), demo.SOURCE_SIZE)
            at = image.index(b"grAb")+4
            self.assertEqual(struct.unpack_from(">ii", image, at), (24, 64))

    def test_prepare_is_pure_and_pixels_survive_modes_and_camera(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = demo.prepare(root / "a")
            second = demo.prepare(root / "b")
            self.assertFalse(first["native_executed"])
            self.assertEqual(first, second)
            sprites = first["cases"]["projected"]["sprite_sources"]
            self.assertTrue(all(c["sprite_sources"] == sprites for c in first["cases"].values()))
            for name in demo.CASES:
                a, b = root / "a" / name / "scene.pk3", root / "b" / name / "scene.pk3"
                self.assertEqual(a.read_bytes(), b.read_bytes())
                with zipfile.ZipFile(a) as archive:
                    self.assertEqual(len([n for n in archive.namelist() if n.startswith("maps/")]), 5)
                    self.assertIn("CC0-1.0", archive.read("LICENSE-SYNTHETIC.txt").decode())
                    self.assertFalse(any(n.lower().endswith("doom2.wad") for n in archive.namelist()))
            with self.assertRaises(ValueError):
                demo.prepare(root / "a")

    def test_scene_camera_cannot_move_caster_or_light(self):
        _, baseline = demo.members(demo.CASES["projected"])
        for name in ("orbit-east", "orbit-north", "orbit-west"):
            _, candidate = demo.members(demo.CASES[name])
            for field in ("actor_position", "actor_angle", "light_position", "receiver"):
                self.assertEqual(candidate["SHD001"][field], baseline["SHD001"][field])
            self.assertNotEqual(candidate["SHD001"]["camera_position"], baseline["SHD001"]["camera_position"])
        self.assertLess(demo.CASES["invalid-low-light"]["light"][2], demo.SOURCE_SIZE[1])
        for case in demo.CASES.values():
            self.assertIs(demo.settings(case)["vk_rayquery"], False)
            self.assertEqual(demo.settings(case)["gl_texture_filter"], 0)

    def test_projection_receipt_rejects_wrong_receiver_and_unbounded_vertices(self):
        good = {"actor_tid": demo.ACTOR_TID, "mode": "projected", "source_texture": "SHD1A3A7",
                "flipped": False, "light_position": [-96,-64,128], "actor_position": [0,0,0],
                "floor_z": 0, "vertices": [[0,0,0], [80,40,0], [40,80,0]],
                "receiver_sector": 0, "mask_scale": 4, "light_tid": demo.LIGHT_TID,
                "vertex_count": 3, "geometry_hash": 123456789}
        self.assertEqual(run_demo.projection_signature(good)["mask_scale"], 4)
        for field, value in (("receiver_sector", 1), ("mask_scale", 1), ("vertices", [[0,0,5]]*3),
                             ("vertices", [[500,0,0]]*3), ("vertices", [[float("nan"),0,0]]*3)):
            bad = copy.deepcopy(good)
            bad[field] = value
            with self.assertRaises(ValueError):
                run_demo.projection_signature(bad)
        self.assertEqual(run_demo.projection_records({"records": []}), [])
        self.assertEqual(run_demo.projection_records({"records": [{"kind": "sprite-shadow", "data": good}]}), [good])


if __name__ == "__main__":
    unittest.main()
