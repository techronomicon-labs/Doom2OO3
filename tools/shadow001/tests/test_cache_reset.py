"""Synthetic negative controls, never renderer output or native acceptance."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.shadow001 import run_demo
from tools.renderer_oracle import validate


def shadow():
    return {"actor_tid": 7101, "mode": "projected", "source_texture": "SHD1A3A7",
            "flipped": False, "light_position": [-96, -64, 128], "actor_position": [0, 0, 0],
            "light_tid": 7102, "floor_z": 0, "receiver_sector": 0, "mask_scale": 4,
            "vertex_count": 3, "vertices": [[0, 0, 0], [80, 40, 0], [40, 80, 0]],
            "geometry_hash": 2**63+123, "representation": "bounded-dark-decal"}


def cache_records():
    records = []
    for frame in range(1, run_demo.RESET_FRAMES+1):
        phase, settings = run_demo.reset_settings(frame)
        linear = settings["gl_texture_filter"] == 4
        anisotropy = linear and settings["gl_texture_filter_anisotropic"] == 2
        sampler = {"available": True, "min_filter": int(linear), "mag_filter": int(linear),
                   "mipmap_mode": int(linear), "address_u": 2, "address_v": 2, "address_w": 0,
                   "min_lod": 0, "max_lod": 100 if linear else .25, "lod_bias": 0,
                   "anisotropy": anisotropy, "max_anisotropy": 2 if anisotropy else 1}
        values = [("frame", {"settings": settings}), ("sprite-shadow", shadow()),
                  ("material", {"name": run_demo.PROXY_MATERIAL, "context": {"type": "main"},
                    "resource": {"available": True, "index": 32, "generation": phase+1,
                                 "epoch": 1, "span": 1},
                    "layers": [{"binding": 0, "semantic": "albedo", "sampler": sampler}]})]
        records += [{"kind": kind, "frame": frame, "count": 1, "data": value} for kind, value in values]
    stdout = "\n".join(f"SDVK153_SETTING {s['cvar']}={s['value']} after_main_views={s['after_main_views']}"
                       for s in run_demo.RESET_SCHEDULE)
    return {"observed_frames": run_demo.RESET_FRAMES, "warmup_frames": run_demo.RESET_WARMUP,
            "records": records}, stdout


class CacheResetTests(unittest.TestCase):
    def test_all_five_actual_binding_phases_are_required_without_rgb_equality(self):
        raw, stdout = cache_records()
        result = run_demo.validate_cache_reset(raw, stdout)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["settings_resets"], 4)
        self.assertEqual([phase["first_frame"] for phase in result["phases"]], [1, 9, 17, 25, 33])
        self.assertFalse(result["image_repeatability_required"])

    def test_missing_or_reordered_driver_reset_is_rejected(self):
        raw, stdout = cache_records()
        for markers in ("", "\n".join(stdout.splitlines()[:-1]), "\n".join(reversed(stdout.splitlines()))):
            with self.subTest(markers=markers), self.assertRaisesRegex(ValueError, "driver"):
                run_demo.validate_cache_reset(raw, markers)

    def test_stale_same_token_after_reset_is_rejected(self):
        raw, stdout = cache_records()
        for row in raw["records"]:
            if row["kind"] == "material" and row["frame"] == 9:
                row["data"]["resource"]["generation"] = 1
        with self.assertRaisesRegex(ValueError, "stale descriptor token"):
            run_demo.validate_cache_reset(raw, stdout)

    def test_unavailable_token_missing_draw_and_stale_sampler_are_rejected(self):
        original, stdout = cache_records()
        for mutation in ("unavailable", "missing-shadow", "filter", "anisotropy", "actual-setting"):
            raw = copy.deepcopy(original)
            if mutation == "missing-shadow":
                raw["records"] = [row for row in raw["records"]
                                  if not (row["kind"] == "sprite-shadow" and row["frame"] == 17)]
            elif mutation == "actual-setting":
                next(row["data"] for row in raw["records"]
                     if row["kind"] == "frame" and row["frame"] == 17)["settings"]["vk_rayquery"] = True
            else:
                material = next(row["data"] for row in raw["records"]
                                if row["kind"] == "material" and row["frame"] == 17)
                if mutation == "unavailable":
                    material["resource"] = {"available": False, "reason": "synthetic missing allocation"}
                else:
                    sampler = material["layers"][0]["sampler"]
                    sampler["min_filter" if mutation == "filter" else "max_anisotropy"] = 0
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                run_demo.validate_cache_reset(raw, stdout)


class ShadowObservationTests(unittest.TestCase):
    def test_bounded_shadow_and_explicit_fallback_structures(self):
        validate._sprite_shadow(shadow())
        negative_floor = shadow()
        negative_floor["floor_z"] = -32
        for vertex in negative_floor["vertices"]:
            vertex[2] = -32
        validate._sprite_shadow(negative_floor)
        validate._sprite_shadow_fallback({"actor_tid": 7101, "reason": "no-eligible-light",
                                          "fallback": "legacy-contact"})
        for field, value in (("vertex_count", 257), ("geometry_hash", -1), ("mask_scale", True),
                             ("vertices", [[0, 0, float("nan")]]*3),
                             ("vertices", [[0, 0, 2]]*3), ("flipped", 1)):
            candidate = shadow()
            candidate[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate._sprite_shadow(candidate)
        with self.assertRaises(ValueError):
            validate._sprite_shadow_fallback({"actor_tid": 7101, "reason": "", "fallback": "legacy-contact"})

    def test_common_observation_validates_new_channel_and_required_safety_channels(self):
        # Reuse the existing explicitly synthetic native-envelope test fixture.
        sys.path.insert(0, str(ROOT / "tools/renderer_oracle/tests"))
        from test_validation import observation, recount, row
        raw = observation()
        raw["records"] += [row("sprite-shadow", shadow()),
                           row("pipeline", {"key": {"shader": {"synthetic": True}}, "draw_count": 3}),
                           row("resource", {"descriptor_capacity": 100, "descriptor_current": 1,
                                "descriptor_high_water": 1, "descriptor_dynamic_start": 32,
                                "texture_epoch": 1, "lightmap_epoch": 1, "probe_epoch": 1,
                                "async_upload_epoch": 1})]
        required = {"frame", "context", "material", "resource", "pipeline", "sprite-shadow"}
        self.assertEqual(validate.observation(recount(raw), required_kinds=required)["status"], "PASS")
        for kind in required:
            missing = copy.deepcopy(raw)
            missing["records"] = [r for r in missing["records"] if r["kind"] != kind]
            with self.subTest(missing=kind), self.assertRaises(ValueError):
                validate.observation(recount(missing), required_kinds=required)
        raw["records"][3]["data"]["vertices"][0][2] = 99
        with self.assertRaisesRegex(ValueError, "receiver plane"):
            validate.observation(recount(raw), required_kinds=required)


if __name__ == "__main__":
    unittest.main()
