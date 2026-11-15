"""Positive, negative and source-admission controls for risk-based CI routing."""
import json
import argparse
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import route
import routine_native

ROOT = Path(__file__).resolve().parents[2]


class PathRoutingTests(unittest.TestCase):
    def test_pure_documentation_needs_no_native_or_publication(self):
        result = route.classify(["AGENTS.md", "docs/shadedoomvk/rag/11-RENDERER-OBSERVABILITY.md"])
        self.assertFalse(result["native"])
        self.assertEqual(result["targeted"], [])
        self.assertFalse(result["deep"])

    def test_new_sprite_feature_does_not_inherit_publication(self):
        result = route.classify(["src/rendering/hwrenderer/scene/hw_sprites.cpp", "tools/shadow001/run_demo.py"])
        self.assertTrue(result["native"])
        self.assertEqual(result["targeted"], ["actors"])
        self.assertFalse(result["deep"])

    def test_hazardous_paths_keep_their_targeted_gate(self):
        cases = {
            "src/common/rendering/vulkan/descriptorsets/vk_descriptorpool.cpp": {"resources"},
            "src/common/rendering/hwrenderer/data/hw_levelmesh.cpp": {"resources", "lightmaps"},
            "src/rendering/hwrenderer/scene/hw_portal.cpp": {"portals", "actors"},
            "src/common/textures/material_layer_semantics.h": {"resources", "materials"},
            "wadsrc/static/shaders/scene/main.fp": {"resources", "materials"},
            "src/rendering/hwrenderer/scene/hw_spritelight.cpp": {"lighting", "actors"},
            "tools/renderer_oracle/sdvk161_special_surfaces.py": {"resources", "lightmaps"},
        }
        for path, required in cases.items():
            with self.subTest(path=path):
                result = route.classify([path])
                self.assertTrue(result["native"])
                self.assertTrue(required <= set(result["targeted"]))

    def test_source_markdown_is_not_silently_docs_only(self):
        self.assertTrue(route.classify(["src/new-renderer/README.md"])["native"])

    def test_overlapping_subsystems_accumulate_risk(self):
        self.assertTrue({"actors", "portals"} <= set(route.classify([
            "src/rendering/hwrenderer/scene/hw_sprite_portal.cpp"])["targeted"]))
        self.assertTrue({"resources", "materials", "lightmaps"} <= set(route.classify([
            "src/common/rendering/vulkan/textures/vk_lightmaptexture.cpp"])["targeted"]))

    def test_workflow_change_qualifies_executor_and_lifetime(self):
        self.assertEqual(route.classify([".github/workflows/continuous_integration.yml"])["targeted"],
                         ["actors", "resources"])

    def test_empty_unknown_and_shared_build_paths_fail_closed(self):
        for paths in ([], ["src/new/subsystem.cpp"], ["CMakeLists.txt"], ["tools/renderer_oracle/run.py"]):
            with self.subTest(paths=paths):
                result = route.classify(paths)
                self.assertTrue(result["native"])
                self.assertEqual(set(result["targeted"]), set(route.GROUPS))

    def test_documentation_cannot_hide_a_resource_change(self):
        result = route.classify(["docs/design.md", "src/common/rendering/vulkan/descriptorsets/new.cpp"])
        self.assertTrue(result["native"])
        self.assertIn("resources", result["targeted"])

    def test_malformed_paths_rejected(self):
        for path in ("", "../src/file.cpp", "/tmp/file", "src\\file.cpp"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                route.classify([path])

    def test_no_regular_change_silently_launches_deep(self):
        for paths in ([], ["CMakeLists.txt"], ["tools/renderer_oracle/sdvk009_publication.py"]):
            self.assertFalse(route.classify(paths)["deep"])


class SourceAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = mock.patch.object(route, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.command("init", "-q")
        (self.root / "original.cpp").write_text("original")
        self.commit()
        self.base = self.command("rev-parse", "HEAD").strip()
        (self.root / "original.cpp").rename(self.root / "new.cpp")
        self.commit()
        self.head = self.command("rev-parse", "HEAD").strip()

    def command(self, *args):
        return subprocess.check_output(["git", "-c", "user.name=CI fixture", "-c", "user.email=fixture@example.invalid",
                                        *args], cwd=self.root, text=True)

    def commit(self):
        self.command("add", "-A")
        self.command("commit", "-qm", "routing fixture")

    def event(self):
        return {"pull_request": {"head": {"sha": self.head}, "base": {"sha": self.base}}}

    def test_renamed_and_deleted_paths_both_receive_routing(self):
        paths, head, base = route.changed_paths(self.event(), "pull_request")
        self.assertEqual(set(paths), {"original.cpp", "new.cpp"})
        self.assertEqual((head, base), (self.head, self.base))

    def test_unmatched_source_head_rejected(self):
        event = self.event()
        event["pull_request"]["head"]["sha"] = self.base
        with self.assertRaises(ValueError):
            route.changed_paths(event, "pull_request")

    def test_missing_base_is_a_failure_not_docs_pass(self):
        event = self.event()
        event["pull_request"]["base"]["sha"] = "f" * 40
        with self.assertRaises(subprocess.CalledProcessError):
            route.changed_paths(event, "pull_request")

    def test_new_branch_uses_conservative_empty_routing(self):
        paths, _, _ = route.changed_paths({"before": "0" * 40, "after": self.head}, "push")
        self.assertEqual(set(route.classify(paths)["targeted"]), set(route.GROUPS))


class WorkflowContractTests(unittest.TestCase):
    def test_deep_is_separately_invoked_and_original_suites_survive(self):
        text = (ROOT / ".github/workflows/renderer_deep.yml").read_text()
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("  pull_request:", text)
        self.assertNotIn("  push:", text)
        self.assertIn("name: Deep | PF renderer contract oracle", text)
        self.assertIn("name: Deep | ${{ matrix.config.name }}", text)
        for command in ("native_ci.py", "--full", "collision_replay.py", "sdvk008_physical.py",
                        "sdvk010_acceptance", "sdvk150_probe_owner", "sdvk153_probe_reset",
                        "sdvk158_lightmap_transition", "sdvk161_special_surfaces", "sdvk014_controlled_planes",
                        "sdvk009_publication qualify"):
            self.assertIn(command, text)

    def test_normal_workflow_routes_and_never_launches_publication(self):
        text = (ROOT / ".github/workflows/continuous_integration.yml").read_text()
        self.assertNotIn("--full", text)
        self.assertNotIn("sdvk009_publication qualify", text)
        self.assertIn("tools/ci/route.py --event-path", text)
        self.assertIn("needs: pf_oracle", text)
        self.assertIn("github.event.pull_request.head.sha || github.sha", text)
        for group in route.GROUPS:
            self.assertIn("steps.route.outputs." + group, text)
            self.assertIn("needs.pf_oracle.outputs." + group, text)
        self.assertIn("if-no-files-found: error", text)
        self.assertNotIn("continue-on-error", text)
        self.assertIn("Reject missing or malformed routing outputs", text)
        self.assertIn("Missing/invalid CI routing output", text)
        self.assertNotIn("needs.pf_oracle.outputs.native != 'true'", text)
        source = (ROOT / ".github/workflows/renderer_source_evidence.yml").read_text()
        self.assertIn("ref: ${{ github.event.pull_request.head.sha || github.sha }}", source)

    def test_stable_required_check_names_remain(self):
        text = (ROOT / ".github/workflows/continuous_integration.yml").read_text()
        self.assertIn("name: PF renderer contract oracle", text)
        self.assertIn("name: ${{ matrix.config.name }} | ${{ matrix.config.build_type }}", text)
        for name, count in (("Visual Studio 2022", 2), ("macOS", 2), ("Linux GCC 12", 1),
                            ("Linux Clang 11", 1), ("Linux Clang 15", 1), ("Linux software Vulkan", 1)):
            self.assertEqual(text.count("- name: " + name + "\n"), count)

    def test_portal_only_change_reaches_native_special_surface_gate(self):
        result = route.classify(["src/rendering/hwrenderer/scene/hw_portal.cpp"])
        self.assertIn("portals", result["targeted"])
        self.assertNotIn("lightmaps", result["targeted"])
        text = (ROOT / ".github/workflows/continuous_integration.yml").read_text()
        block = text.split("    - name: Lane B - special surfaces and portals\n", 1)[1].split("    - name:", 1)[0]
        self.assertIn("|| needs.pf_oracle.outputs.portals == 'true'", block)
        self.assertIn("sdvk161_special_surfaces", block)


class VisualMissingEffectTests(unittest.TestCase):
    def test_unchanged_or_tiny_noise_cannot_pass_off_on(self):
        off = bytes(300)
        for on in (off, bytes([3]) * 300, bytes([255]) * 3 + bytes(297)):
            with self.assertRaises(ValueError):
                routine_native.light_response(off, on)

    def test_substantive_light_effect_passes_without_pixel_exactness(self):
        result = routine_native.light_response(bytes(300), bytes([16]) * 300)
        self.assertEqual(result["pixels_with_channel_delta_at_least_4"], 100)

    def test_extent_mismatch_fails(self):
        with self.assertRaises(ValueError):
            routine_native.light_response(bytes(300), bytes(303))

    def test_native_failure_remains_fail_and_retains_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(expected_commit="a" * 40, out=Path(directory) / "run",
                extra_scene=[], exe=Path("engine"), iwad=Path("iwad"), iwad_license=None)
            with mock.patch.object(routine_native, "software_host_guard", return_value={}), \
                 mock.patch.object(routine_native.native_ci, "preflight", return_value={}), \
                 mock.patch.object(routine_native.prepare, "prepare"), \
                 mock.patch.object(routine_native.run, "capture", side_effect=ValueError("stale resource")) as capture:
                self.assertEqual(routine_native.qualify(args), 1)
            receipt = json.loads((args.out / "routine-native.json").read_text())
            self.assertEqual(receipt["status"], "FAIL")
            self.assertEqual(receipt["error"], "stale resource")
            self.assertEqual(capture.call_count, 1)
            self.assertFalse(receipt["legacy_campaign_accepted"])
            request = capture.call_args.args[0]
            self.assertEqual(request.expected_commit, args.expected_commit)
            self.assertTrue(request.require_clean)


if __name__ == "__main__":
    unittest.main()
