"""Dynamic-light actor-blocker contracts. This is NOT sprite-alpha visual acceptance."""
from pathlib import Path
import math
import unittest

ROOT = Path(__file__).resolve().parents[3]


def visibility(light, receiver, caster):
    # The GLSL contract uses renderer coordinates x,height,y.
    x, y, z, radius, bottom, top = caster
    d = tuple(receiver[i] - light[i] for i in range(3))
    dx, dz = d[0], d[2]
    ox, oz = light[0] - x, light[2] - z
    a = dx*dx + dz*dz
    if a <= .0001 or radius <= 0 or bottom >= top:
        return 1.
    hb = ox*dx + oz*dz
    discr = hb*hb - a*(ox*ox + oz*oz - radius*radius)
    if discr <= 0:
        return 1.
    root = math.sqrt(discr)
    entry = max((-hb-root)/a, .002)
    leave = min((-hb+root)/a, .998)
    if leave <= entry:
        return 1.
    px, pz = receiver[0]-x, receiver[2]-z
    if px*px+pz*pz <= radius*radius and bottom <= receiver[1] <= top:
        return 1.
    if bottom <= light[1] <= top and ox*ox+oz*oz <= radius*radius:
        return 1.
    y0, y1 = light[1]+d[1]*entry, light[1]+d[1]*leave
    if max(y0,y1) <= bottom or min(y0,y1) >= top:
        return 1.
    return 0.


class ActorShadowContracts(unittest.TestCase):
    def test_caster_occludes_floor_and_wall(self):
        actor = (0, 30, 0, 12, 0, 60)
        emitter = (-90, 60, 0)
        self.assertEqual(visibility(emitter, (90, 0, 0), actor), 0.)
        self.assertEqual(visibility(emitter, (90, 40, 0), actor), 0.)
        self.assertEqual(visibility(emitter, (90, 0, 60), actor), 1.)

    def test_other_lights_and_ambient_are_not_darkened(self):
        actor = (0, 30, 0, 12, 0, 60)
        receiver = (90, 0, 0)
        blocked = visibility((-90, 60, 0), receiver, actor)
        clear = visibility((90, 60, 90), receiver, actor)
        self.assertEqual((blocked, clear), (0., 1.))
        self.assertAlmostEqual(.15 + .7*blocked + .4*clear, .55)

    def test_non_intersection_vertical_and_self_shadow(self):
        a = (0, 30, 0, 12, 0, 60)
        self.assertEqual(visibility((-90, 60, 0), (-40, 0, 0), a), 1.)
        self.assertEqual(visibility((-90, 200, 0), (90, 180, 0), a), 1.)
        self.assertEqual(visibility((-90, 60, 0), (0, 30, 0), a), 1.)
        self.assertEqual(visibility((0, 30, 0), (90, 0, 0), a), 1.)
        self.assertEqual(visibility((-90, 30, 0), (-90, 70, 0), a), 1.)
        self.assertEqual(visibility((-90, 30, 0), (90, 0, 0), (0,30,0,0,0,60)), 1.)

    def test_cpu_gpu_record_layout_and_caster_policy(self):
        cpu = (ROOT/"src/common/rendering/hwrenderer/data/hw_dynlightdata.h").read_text()
        gpu = (ROOT/"wadsrc/static/shaders/binding_struct_definitions.glsl").read_text()
        source = (ROOT/"src/rendering/hwrenderer/hw_dynlightdata.cpp").read_text()
        self.assertIn("sizeof(FDynLightInfo) == 224", cpu)
        self.assertIn("MaxActorShadowCastersPerLight = 4", cpu)
        self.assertIn("ActorShadowCaster actorShadowCasters[4]", gpu)
        self.assertIn("GetThinkerIterator<AActor>()", source)
        self.assertIn("candidate == light->target", source)
        self.assertIn("candidate->Sector->PortalGroup != group", source)
        self.assertIn("gl_actor_light_shadows, false", source)

    def test_all_real_local_light_models_attenuate_source_not_composite(self):
        root = ROOT/"wadsrc/static/shaders/scene"
        for filename in ("lightmodel_normal.glsl", "lightmodel_specular.glsl", "lightmodel_pbr.glsl"):
            code = (root/filename).read_text()
            self.assertIn("attenuation *= ActorLightShadowVisibility(light);", code, filename)
        pbr=(root/"lightmodel_pbr.glsl").read_text()
        self.assertLess(pbr.index("attenuation *= ActorLightShadowVisibility(light);"),
                        pbr.index("vec3 radiance = light.color.rgb * attenuation"))
        self.assertIn("SampleProbePrefiltered", pbr)
        normal=(root/"lightmodel_normal.glsl").read_text()
        self.assertIn("float spotCosine = dot(lightdir, light.spotDir.xyz)", normal)
        shadow=(root/"light_shadow.glsl").read_text()
        self.assertIn("caster.bottom", shadow)
        self.assertIn("caster.top", shadow)
        self.assertNotIn("STYLE_Stencil", shadow)


if __name__ == "__main__":
    unittest.main()
