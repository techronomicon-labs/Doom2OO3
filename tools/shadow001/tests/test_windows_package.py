"""CPU-only packaging controls with explicit placeholder files; no engine run."""
import json
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.shadow001 import package_windows


class WindowsPackageTests(unittest.TestCase):
    def fixture(self, root):
        runtime, resource = root / "runtime", root / "build"
        runtime.mkdir()
        resource.mkdir()
        required = ("vkdoom.exe", "zmusic.dll", "libsndfile-1.dll", "openal32.dll", "licenses.zip",
                    "soundfonts/vkdoom.sf2", "fm_banks/GENMIDI.GS.wopl",
                    "fm_banks/gs-by-papiezak-and-sneakernets.wopn")
        for name in required:
            path = runtime / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"SYNTHETIC UNIT TEST PLACEHOLDER - NOT AN EXECUTABLE OR NATIVE EVIDENCE")
        (resource / "vkdoom.pk3").write_bytes(b"synthetic core archive placeholder")
        return runtime, resource

    def test_only_core_and_rebuilt_metadata_are_packaged_when_optional_game_assets_exist(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime, resource = self.fixture(root)
            unwanted = ("brightmaps.pk3", "lights.pk3", "game_widescreen_gfx.pk3",
                        "doom2.wad", "vkdoom.pdb", "another-mod.pk3")
            for directory in (runtime, resource):
                for name in ("game_support.pk3",) + unwanted:
                    (directory / name).write_bytes(b"excluded synthetic unit-test placeholder")
            (runtime / "soundfonts" / "another-mod.pk3").write_bytes(b"excluded nested placeholder")
            out = root / "candidate"
            with mock.patch.object(package_windows.subprocess, "check_output", return_value="a"*40+"\n"):
                result = package_windows.package(runtime, resource, out, "a"*40)
            self.assertEqual(result["status"], "PACKAGED_NOT_EXECUTED")
            manifest = json.loads((out / "package.json").read_text())
            self.assertEqual(manifest["native_launches"], 0)
            self.assertFalse(manifest["optional_game_assets_included"])
            self.assertFalse(manifest["iwad_included"])
            with zipfile.ZipFile(result["archive"]) as archive:
                names = archive.namelist()
                self.assertEqual({name for name in names if name.startswith("runtime/") and name.endswith(".pk3")},
                                 {"runtime/vkdoom.pk3", "runtime/game_support.pk3"})
                rebuilt = archive.read("runtime/game_support.pk3")
                self.assertNotEqual(rebuilt, (runtime / "game_support.pk3").read_bytes())
                with zipfile.ZipFile(io.BytesIO(rebuilt)) as support:
                    self.assertEqual(support.namelist(), ["iwadinfo.txt"])
                    self.assertEqual(support.read("iwadinfo.txt"),
                                     (ROOT / "wadsrc_extra/static/iwadinfo.txt").read_bytes())
                self.assertFalse(any(Path(name).name in unwanted for name in names))
                self.assertIn("runtime/zmusic.dll", names)
                self.assertIn("runtime/soundfonts/vkdoom.sf2", names)
                self.assertIn("demo/projected/scene.pk3", names)
            self.assertIn("-noextras", (out / "Owner-Launch-Command.ps1").read_text())

    def test_absent_core_archive_is_rejected_before_any_package_is_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime, resource = self.fixture(root)
            (resource / "vkdoom.pk3").unlink()
            with mock.patch.object(package_windows.subprocess, "check_output", return_value="a"*40+"\n"):
                with self.assertRaisesRegex(ValueError, "vkdoom.pk3"):
                    package_windows.package(runtime, resource, root / "candidate", "a"*40)
            self.assertFalse((root / "candidate").exists())


if __name__ == "__main__":
    unittest.main()
