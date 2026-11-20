"""Copyright-free checks for effective world geometry and animation controls."""

import struct
import unittest

import numpy as np

from dbp50_effective import reconstruct_rows
from dbp50_structural_relief import height_profiles


def texture_table(name):
    definition = struct.pack("<8sIhhIh", name, 0, 2, 2, 0, 1)
    return struct.pack("<ii", 1, 8) + definition + struct.pack("<hhhhh", 0, 0, 0, 0, 0)


def patch(index):
    post = bytes((0, 2, 0, index, index, 0, 255))
    return struct.pack("<hhhhII", 2, 2, 0, 0, 16, 23) + post * 2


def row(kind, name, rgb, family="painted panels"):
    pixels = np.full((*rgb.shape, 4), 255, np.uint8)
    pixels[:, :, :3] = rgb[:, :, None]
    return dict(kind=kind, name=name, family=family, pixels=pixels,
                pattern_changed=True, placeholder=False)


class DBP50StructuralReliefTests(unittest.TestCase):
    def test_full_namespace_uses_each_texture_tables_own_pnames(self):
        palette = bytes(range(256)) * 3
        original = {"PLAYPAL": palette, "PNAMES": struct.pack("<i8s", 1, b"A"),
                    "TEXTURE1": texture_table(b"INHERIT"), "A": patch(1)}
        replacement = {"PNAMES": struct.pack("<i8s", 1, b"B"),
                       "TEXTURE1": texture_table(b"CUSTOM"), "B": patch(2)}
        entries = [dict(kind="wall", name="INHERIT", family="metal", source_index=0, id=7)]
        inherited = reconstruct_rows(original, replacement, {}, entries)
        full = reconstruct_rows(original, replacement, {"NEWFLAT": bytes(4096)}, entries, include_custom=True)

        self.assertEqual([item["name"] for item in inherited], ["INHERIT"])
        by_name = {item["name"]: item for item in full}
        self.assertEqual(set(by_name), {"INHERIT", "CUSTOM", "NEWFLAT"})
        np.testing.assert_array_equal(by_name["INHERIT"]["pixels"][0, 0], (3, 4, 5, 255))
        np.testing.assert_array_equal(by_name["CUSTOM"]["pixels"][0, 0], (6, 7, 8, 255))
        self.assertEqual({item["id"] for item in full}, {7, 8, 9})
        self.assertTrue(by_name["NEWFLAT"]["pattern_changed"])
        self.assertEqual(by_name["NEWFLAT"]["pixels"].shape, (64, 64, 4))

    def test_dbp50_authored_floor_tracks_center_and_wrap(self):
        pixels = np.resize(np.array((45, 60), np.uint8), (64, 64))
        diamond = row("flat", "DIAMOND6", pixels)
        stone = row("flat", "DNOX", pixels)
        results = height_profiles([diamond, stone], {}, None)
        grout, _, _ = results["flat", "DIAMOND6"]
        square, _, _ = results["flat", "DNOX"]

        self.assertEqual(grout.shape, (128, 128))
        self.assertLess(grout[6, 11], 45)
        self.assertEqual(grout[6, 19], 128)
        np.testing.assert_array_equal(grout[:, :32], grout[:, 32:64])
        self.assertLess(square[63, 20], 45)
        self.assertEqual(square[50, 20], 128)
        np.testing.assert_array_equal(square[:, :64], square[:, 64:])

    def test_switch_phases_share_structure_and_water_frames_are_neutral(self):
        backing = np.full((48, 48), 120, np.uint8)
        backing[23:25] = 30
        second = backing.copy()
        second[9:12, 10:17] = 200
        rows = [row("wall", "SW1GRAY1", backing), row("wall", "SW2GRAY1", second)]
        rows.extend(row("wall", f"WFALL{phase}", np.roll(backing, phase, axis=0), "liquid / static sample")
                    for phase in range(1, 5))
        results = height_profiles(rows, {}, None)

        first = results["wall", "SW1GRAY1"][0]
        self.assertIsNotNone(first)
        np.testing.assert_array_equal(first, results["wall", "SW2GRAY1"][0])
        self.assertTrue(all(results["wall", f"WFALL{phase}"][0] is None for phase in range(1, 5)))
