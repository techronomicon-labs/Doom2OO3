from collections import Counter
from pathlib import Path
from unittest import TestCase, skipUnless

from material_generator import Wad
from stageb_layout import (FLAT_FIXTURES, MapGeometry, PlaneEmitter, Sector, infer_layout,
                           stock_map_lumps, visible_centres, wall_bands)
from stageb_lighting import actor_script


IWAD = Path(__file__).resolve().parents[2] / "assets" / "wads" / "doom2.wad"


class FixturePlacementTests(TestCase):
    def test_amber_lens_is_clipped_before_runtime_plane_clearance(self):
        front = Sector(0, 64, "FLOOR", "CEIL", 160)
        # TEKBRON2 only lights up at texel rows 4 and 5. The same texture
        # shifted down the sidedef can show a brown panel with its lens hidden.
        for offset, expected in ((0, [59]), (16, []), (-16, [43])):
            low, high, top = wall_bands(0, offset, front, None, 128, 2)
            self.assertEqual(list(visible_centres(low, high, top - 6, top - 4, 128)), expected)

    def test_sky_portal_uses_renderer_lower_texture_pegging(self):
        front = Sector(0, 128, "FLOOR", "F_SKY1", 192)
        back = Sector(32, 96, "FLOOR", "F_SKY1", 192)
        self.assertIsNone(wall_bands(0, 0, front, back, 128, 0))
        self.assertEqual(wall_bands(16, 0, front, back, 128, 1), (0, 32, 96))

    @skipUnless(IWAD.is_file(), "requires the local Doom II IWAD")
    def test_stock_flats_and_cropped_wall_strips(self):
        wad = Wad(IWAD)
        layouts = infer_layout(wad)
        for name, _, lumps in stock_map_lumps(wad):
            geometry = MapGeometry(lumps)
            for emitter in layouts[name][1]:
                with self.subTest(map=name, source=emitter):
                    self.assertTrue(geometry.contains(emitter.sector, emitter.x, emitter.y))
                    if isinstance(emitter, PlaneEmitter):
                        sector = geometry.sectors[emitter.sector]
                        surface = sector.ceiling_texture if emitter.ceiling else sector.floor_texture
                        self.assertEqual(emitter.texture, surface)
                        uv = emitter.x % 64, -emitter.y % 64
                        fixture = FLAT_FIXTURES[emitter.texture]
                        self.assertTrue(any(x0 <= uv[0] < x1 and y0 <= uv[1] < y1
                                            for x0, y0, x1, y1 in fixture.anchors or fixture.regions))
        # The Gantlet and Waste Tunnels crop the illuminated strip off their bronze panels.
        for name in ("MAP03", "MAP05"):
            self.assertFalse(any(e.texture == "TEKBRON2" for e in layouts[name][1]))
        base = layouts["MAP10"][1]
        self.assertTrue(any(e.texture == "TEKBRON2" for e in base))
        # Sector 62 repeats hundreds of footlights around the Refueling Base.
        counts = Counter(e.sector for e in base if e.texture == "BIGBRIK3")
        self.assertLessEqual(counts[62], 10)
        self.assertGreater(counts[62], 1)

    @skipUnless(IWAD.is_file(), "requires the local Doom II IWAD")
    def test_authored_light_cycles_registered_once_on_install_or_save_upgrade(self):
        campaign = infer_layout(Wad(IWAD))
        script = actor_script(False, campaign)
        for name, (_, sources) in campaign.items():
            function = script.split(f"    void Load{name}()", 1)[1].split("\n    }", 1)[0]
            registered = [line.strip() for line in function.splitlines() if "SetStageBLightPeak" in line]
            expected = {f"level.SetStageBLightPeak({e.sector}, {e.light_cycle[0]}, {e.light_cycle[1]});"
                        for e in sources if e.light_cycle is not None}
            self.assertCountEqual(registered, expected, name)
        samples = {name: {e.sector: e.light_cycle for e in campaign[name][1] if e.light_cycle}
                   for name in ("MAP01", "MAP02", "MAP08", "MAP11", "MAP30", "MAP31")}
        self.assertEqual(samples["MAP01"], {})
        self.assertEqual(samples["MAP02"], {60: (144, 128), 62: (144, 128)})
        self.assertEqual(samples["MAP08"][69], (208, 0))  # Random flicker, continuous power.
        self.assertEqual(samples["MAP11"], {79: (255, 0), 118: (255, 0)})
        self.assertEqual(samples["MAP30"], {})
        self.assertEqual(samples["MAP31"], {25: (192, 0), 28: (192, 0)})  # Fire flicker.
        self.assertIn("LoadCampaignLayout(RoomLabel != \"\");", script)
