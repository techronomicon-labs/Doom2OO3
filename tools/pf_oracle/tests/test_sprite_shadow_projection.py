"""SHADOW-001 CPU geometry plus source ownership/lifecycle guardrails.

These are not native image, Vulkan resource lifetime or visual acceptance.
Those remain the separate opt-in hosted demonstration's responsibility.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from tools.pf_oracle.fixture_runner import compile_fixture, run_fixture
from tools.pf_oracle.tests.sdvk014_source import block

ROOT = Path(__file__).resolve().parents[3]


class SpriteShadowProjectionTests(unittest.TestCase):
    def test_production_mask_projection_mirror_and_receiver_negatives(self):
        run_fixture("tools/pf_oracle/tests/sprite_shadow_projection_fixture.cpp", root=ROOT,
                    includes=("src/rendering/hwrenderer/scene", "src/common/textures"))

    def test_actual_trace_range_rejects_near_endpoint_occluder(self):
        """Compile the production Trace body, not a second range formula.

        The collision stub is an analytic wall crossing at known world X.
        This isolates the actual segment supplied to Collision::FindFirstHit;
        traversal, default margin and endpoint handling come from production.
        """
        data = ROOT / "src/common/rendering/hwrenderer/data"
        body = block((data / "hw_levelmesh.cpp").read_text(), "LevelMeshSurface* LevelMesh::Trace(")
        declaration = re.search(r"LevelMeshSurface\* Trace\([^;]+;", (data / "hw_levelmesh.h").read_text()).group()
        code = r'''
#include <algorithm>
#include <cassert>
#include <vector>
struct FVector3 {
    float x,y,z;
    FVector3 operator+(FVector3 p) const { return {x+p.x,y+p.y,z+p.z}; }
    FVector3 operator*(float t) const { return {x*t,y*t,z*t}; }
};
struct TraceHit { int triangle; float fraction; };
struct LevelMeshSurface { int PortalIndex = 0; float Alpha = 1; };
struct CollisionStub {
    float wallX = 95, observedEnd = 0;
    TraceHit FindFirstHit(FVector3 start, FVector3 end) {
        observedEnd = end.x;
        if (wallX > start.x && wallX <= end.x)
            return {0, (wallX - start.x) / (end.x - start.x)};
        return {-1, 1};
    }
};
struct Portal {
    FVector3 TransformPosition(FVector3 p) const { return p; }
    FVector3 TransformRotation(FVector3 p) const { return p; }
};
struct LevelMesh {
    CollisionStub collision;
    CollisionStub* Collision = &collision;
    struct { std::vector<LevelMeshSurface> Surfaces{{}}; std::vector<int> SurfaceIndexes{0}; } Mesh;
    std::vector<Portal> Portals{{}};
''' + declaration + "\n};\n" + body + r'''
int main() {
    LevelMesh mesh;
    const FVector3 origin{0,0,0}, direction{1,0,0};
    // Original endpoint allowance stays exactly as inherited for old callers.
    assert(mesh.Trace(origin, direction, 100) == nullptr);
    assert(mesh.collision.observedEnd == 90);
    // Former projector call also missed this blocker: 99.75 - 10 = 89.75.
    assert(mesh.Trace(origin, direction, 99.75f) == nullptr);
    assert(mesh.collision.observedEnd == 89.75f);
    // New explicit allowance observes the actual near-end blocker.
    assert(mesh.Trace(origin, direction, 100, .25f) != nullptr);
    assert(mesh.collision.observedEnd == 99.75f);
    mesh.collision.wallX = 99.5f;
    assert(mesh.Trace(origin, direction, 100, .25f) != nullptr);
    // The receiving plane itself is outside the requested open segment.
    mesh.collision.wallX = 100;
    assert(mesh.Trace(origin, direction, 100, .25f) == nullptr);
    // Short non-positive effective segments cannot hit a forward wall.
    mesh.collision.wallX = .1f;
    assert(mesh.Trace(origin, direction, .2f, .25f) == nullptr);
    assert(mesh.collision.observedEnd == 0);
}
'''
        with tempfile.TemporaryDirectory(prefix="shadow001-trace-") as temporary:
            source = Path(temporary) / "trace.cpp"
            source.write_text(code)
            executable = compile_fixture(source, output_dir=temporary, root=ROOT)
            subprocess.run([str(executable)], check=True, timeout=30)
        projector = block((ROOT / "src/rendering/hwrenderer/scene/hw_sprites.cpp").read_text(),
                          "bool HWSprite::ProjectSpriteShadow(")
        self.assertEqual(projector.count("float(distance), .25f)"), 2)
        self.assertNotIn("float(distance - .25)", projector)

    def test_source_owned_proxy_participates_in_replacement_and_flush(self):
        source = (ROOT / "src/common/textures/gametexture.cpp").read_text()
        setup = block(source, "void FGameTexture::Setup(")
        clean = block(source, "void FGameTexture::CleanHardwareData(")
        generate = block(source, "FGameTexture* FGameTexture::GetSpriteShadowProxy(")
        self.assertLess(setup.index("proxy.reset()"), setup.index("Base = wrap"))
        self.assertIn("proxy->CleanHardwareData(full)", clean)
        self.assertIn("SpriteShadowMaskBytes.fetch_sub(SpriteShadowProxyBytes)", source)
        self.assertIn("std::lock_guard<std::mutex>", generate)
        self.assertIn("MaxMaskBytes - SpriteShadowMaskBytes.load()", generate)
        self.assertNotIn("TexMan.AddGameTexture", generate)
        self.assertNotRegex(generate, r"\bBase\s*=(?!=)")
        self.assertNotIn("SetImage(", generate)

    def test_projector_does_not_use_camera_billboard_or_mutate_actor(self):
        source = (ROOT / "src/rendering/hwrenderer/scene/hw_sprites.cpp").read_text()
        project = block(source, "bool HWSprite::ProjectSpriteShadow(")
        # View position belongs only to translucent draw sorting; the complete
        # projection/light/frame selection precedes it and has no camera input.
        geometry = project.split("depth = float(")[0]
        self.assertNotIn("Viewpoint.Pos", geometry)
        self.assertNotIn("ViewVector", geometry)
        self.assertIn("thing->GetSpriteAngle(angle", geometry)
        self.assertIn("GetSpriteFrame(thing->frame", geometry)
        self.assertNotIn("thing->Set", project)
        self.assertNotIn("thing->renderflags ^", project)
        self.assertIn('fallback("world-occlusion-unavailable")', project)
        self.assertIn("levelMesh->Trace", project)
        self.assertNotIn("vk_rayquery", project)
        self.assertIn("GetGlobalShader(0, thing->GetClass())", project)
        self.assertIn("GetGlobalShader(0, nullptr)", project)

    def test_translucent_mesh_is_not_billboard_split_or_depth_written(self):
        source = (ROOT / "src/rendering/hwrenderer/scene/hw_sprites.cpp").read_text()
        draw = block(source, "void HWSprite::DrawProjectedShadow(")
        process = block(source, "void HWSprite::Process(")
        sorting = (ROOT / "src/rendering/hwrenderer/scene/hw_drawlist.cpp").read_text()
        self.assertIn("SetDepthMask(false)", draw)
        self.assertNotIn("SetDepthMask(true)", draw)
        self.assertIn("state.ClearDepthBias()", draw)
        self.assertIn("ss->ProjectedShadow ||", sorting)
        self.assertIn("ProjectedShadow = nullptr", process)
        self.assertLess(process.index("gl_sprite_shadow_mode == 0"), process.index("thing->"))
        self.assertIn("RenderStyle = STYLE_Stencil", process)  # inherited fallback remains


if __name__ == "__main__":
    unittest.main()
