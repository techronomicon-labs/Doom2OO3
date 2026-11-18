from pathlib import Path
import unittest

from material_generator import Wad
from stageb_layout import MapGeometry, PlaneEmitter, infer_layout, stock_map_lumps
from stageb_lighting import ENTRYWAY, ENTRYWAY_CHECKSUM, actor_script


IWAD = Path(__file__).resolve().parents[2] / "assets" / "wads" / "doom2.wad"


class StageBLayoutTests(unittest.TestCase):
    def test_fixture_script_without_iwad_retains_entryway(self):
        script = actor_script(playable=False)
        self.assertIn(f'level.GetChecksum() == "{ENTRYWAY_CHECKSUM}"', script)
        self.assertEqual(script.count('RoomLabel = "Entryway";'), 1)
        for fixture in ENTRYWAY:
            self.assertEqual(script.count(fixture.call()), 1)
        self.assertNotIn("RenderOverlay", script)
        self.assertNotIn("EnableStageBLayout", script)

    @unittest.skipUnless(IWAD.is_file(), "requires the local Doom II IWAD")
    def test_stock_campaign_infers_underhalls_fixtures_and_keeps_sewer_dark(self):
        wad = Wad(IWAD)
        campaign = infer_layout(wad)
        maps = {name: (checksum, lumps) for name, checksum, lumps in stock_map_lumps(wad)}
        self.assertEqual(maps["MAP01"][0], ENTRYWAY_CHECKSUM)
        self.assertEqual(set(campaign), set(maps) - {"MAP01"})
        self.assertEqual(campaign["MAP02"][0], "ab24ae6e2cb13cbdd04600a4d37f9189")
        self.assertEqual(campaign["MAP30"][1], [])

        script = actor_script(playable=True, campaign=campaign)
        for name, (checksum, _) in campaign.items():
            self.assertIn(f'level.MapName == "{name}" && level.GetChecksum() == "{checksum}"', script)
        self.assertEqual(script.count("level.EnableStageBLayout();"), len(campaign))
        self.assertIn("if (!CheckedCampaignLayout) LoadCampaignLayout();", script)
        self.assertNotIn("AddThingEmitters", script)
        self.assertEqual(script.count("if (replaceSavedEmitters) ClearSavedCampaignEmitters();"), len(campaign))

        fixtures = campaign["MAP02"][1]
        geometry = MapGeometry(maps["MAP02"][1])
        self.assertEqual({light.sector for light in fixtures}, {17, 60, 61, 62, 73})
        for light in fixtures:
            self.assertTrue(geometry.contains(light.sector, light.x, light.y), light)
            if light.sector in (60, 62):
                self.assertIsInstance(light, PlaneEmitter)
                self.assertEqual(light.texture, "FLAT2")


if __name__ == "__main__":
    unittest.main()
