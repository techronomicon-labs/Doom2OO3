"""Actual source-alpha actor shadows: per-emitter ray and source/ABI contracts.

The mathematical reference is an independently authored oracle, not a GPU PASS.
"""
from pathlib import Path
import math
import unittest

ROOT = Path(__file__).resolve().parents[3]


def solid_mask():
    return (0xFFFFFFFF,) * 16


def caster_for(light, mask=None, *, mirror_x=False, mirror_y=False):
    """A source-alpha frame looking from the actual light position."""
    dx, dz = -light[0], -light[2]
    size = math.hypot(dx, dz)
    if size == 0:
        raise ValueError("Coincident light and actor")
    return (0., 0., 0., 12., 0., 60.,
            dx / size, dz / size, -16., 16.,
            float(mirror_x), float(mirror_y),
            solid_mask() if mask is None else mask)


def visibility(light, receiver, caster):
    (x, y, z, radius, bottom, top, nx, nz,
     left, right, mirror_x, mirror_y, mask) = caster
    if radius <= 0 or bottom >= top or right <= left:
        return 1.
    delta = tuple(receiver[i] - light[i] for i in range(3))
    denominator = delta[0] * nx + delta[2] * nz
    if abs(denominator) < 1e-5:
        return 1.
    t = ((x - light[0]) * nx + (z - light[2]) * nz) / denominator
    if not .002 < t < .998:
        return 1.
    hit = tuple(light[i] + delta[i] * t for i in range(3))
    horizontal = (hit[0] - x) * (-nz) + (hit[2] - z) * nx
    u = (horizontal - left) / (right - left)
    v = (hit[1] - bottom) / (top - bottom)
    if not (0. <= u < 1. and 0. <= v < 1.):
        return 1.
    if mirror_x: u = 1. - u
    if mirror_y: v = 1. - v
    px = min(15, max(0, int(math.floor(u * 16.))))
    py = min(31, max(0, int(math.floor((1. - v) * 32.))))
    return float((mask[py // 2] & (1 << ((py % 2) * 16 + px))) == 0)


class ActorShadowContracts(unittest.TestCase):
    def test_source_alpha_occludes_actual_floor_and_wall(self):
        light = (-90., 60., 0.)
        caster = caster_for(light)
        self.assertEqual(visibility(light, (90., 0., 0.), caster), 0.)
        self.assertEqual(visibility(light, (90., 40., 0.), caster), 0.)
        self.assertEqual(visibility(light, (90., 0., 60.), caster), 1.)

    def test_transparent_holes_do_not_cast(self):
        light = (-90., 60., 0.)
        full = list(solid_mask())
        # Row 16, column 8 corresponds to the center of the silhouette.
        full[16 // 2] &= ~(1 << 8)
        self.assertEqual(visibility(light, (90., 0., 0.), caster_for(light, tuple(full))), 1.)
        self.assertEqual(visibility(light, (90., 40., 0.), caster_for(light, tuple(full))), 0.)

    def test_light_source_changes_shadow_but_not_ambient_or_other_lights(self):
        first = (-90., 60., 0.)
        second = (90., 60., 90.)
        receiver = (90., 0., 0.)
        blocked = visibility(first, receiver, caster_for(first))
        clear = visibility(second, receiver, caster_for(second))
        self.assertEqual((blocked, clear), (0., 1.))
        self.assertAlmostEqual(.15 + .7 * blocked + .4 * clear, .55)

    def test_ray_between_endpoints_and_receiver_height(self):
        light = (-90., 60., 0.)
        caster = caster_for(light)
        self.assertEqual(visibility(light, (-40., 0., 0.), caster), 1.)
        self.assertEqual(visibility(light, (0., 30., 0.), caster), 1.)
        self.assertEqual(visibility(light, (90., 0., 50.), caster), 1.)
        self.assertEqual(visibility(light, (90., 0., 5.), caster), 0.)
        self.assertEqual(visibility((-90., 200., 0.), (90., 180., 0.),
                                    caster_for((-90., 200., 0.))), 1.)

    def test_runtime_structural_abi_and_source_alpha(self):
        cpu = (ROOT / "src/common/rendering/hwrenderer/data/hw_dynlightdata.h").read_text()
        gpu = (ROOT / "wadsrc/static/shaders/binding_struct_definitions.glsl").read_text()
        tiled = (ROOT / "wadsrc/static/shaders/scene/comp_lighttiles.glsl").read_text()
        source = (ROOT / "src/rendering/hwrenderer/hw_dynlightdata.cpp").read_text()
        self.assertIn("sizeof(FActorShadowCaster) == 112", cpu)
        self.assertIn("sizeof(FDynLightInfo) == 544", cpu)
        self.assertIn("ActorShadowMaskWidth = 16", cpu)
        self.assertIn("ActorShadowMaskHeight = 32", cpu)
        self.assertIn("MaxActorShadowCastersPerLight = 4", cpu)
        self.assertIn("uint alphaWords[16]", gpu)
        self.assertIn("uint alphaWords[16]", tiled)
        self.assertIn("GetThinkerIterator<AActor>()", source)
        self.assertIn("GetSpriteFrame(", source)
        self.assertIn("GetSpriteAngle(", source)
        self.assertIn("CreateTexBuffer(0)", source)
        self.assertIn("SourceAlphaMask(", source)
        self.assertIn("candidate == light->target", source)
        self.assertIn("candidate->Sector->PortalGroup != group", source)
        self.assertIn("gl_actor_light_shadows, false", source)
        self.assertNotIn("STYLE_Stencil", source)

    def test_per_local_light_shading_not_global_composite(self):
        root = ROOT / "wadsrc/static/shaders/scene"
        for filename in ("lightmodel_normal.glsl", "lightmodel_specular.glsl",
                         "lightmodel_pbr.glsl"):
            shader = (root / filename).read_text()
            self.assertIn("attenuation *= ActorLightShadowVisibility(light);", shader)
        pbr = (root / "lightmodel_pbr.glsl").read_text()
        self.assertLess(pbr.index("attenuation *= ActorLightShadowVisibility(light);"),
                        pbr.index("vec3 radiance = light.color.rgb * attenuation"))
        self.assertIn("SampleProbePrefiltered", pbr)
        normal = (root / "lightmodel_normal.glsl").read_text()
        self.assertIn("float spotCosine = dot(lightdir, light.spotDir.xyz)", normal)
        shadow = (root / "light_shadow.glsl").read_text()
        self.assertIn("caster.alphaWords[word]", shadow)
        self.assertIn("caster.planeNx", shadow)
        self.assertIn("caster.mirrorX", shadow)
        self.assertNotIn("STYLE_Stencil", shadow)
        self.assertNotIn("discriminant", shadow)


if __name__ == "__main__":
    unittest.main()
