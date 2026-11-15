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

    def test_production_receiver_guard_accepts_ordinary_floor_and_rejects_portals(self):
        """Regression for native 750eaa94: ordinary floors were all rejected.

        Compile both the actual sector query and the actual replacement guard
        with minimal sector storage; no hand-copied eligibility expression.
        """
        source = (ROOT / "src/rendering/hwrenderer/scene/hw_sprites.cpp").read_text()
        guard = block(source, "static bool HasOrdinarySpriteShadowReceiver(")
        old_query = block((ROOT / "src/g_levellocals.h").read_text(), "inline bool sector_t::PortalBlocksView(")
        code = r'''
#include <cassert>
enum { PORTS_SKYVIEWPOINT, PORTS_STACKEDSECTORTHING, PORTS_PORTAL,
       PORTS_LINKEDPORTAL, PORTS_PLANE, PORTS_HORIZON };
enum { PLANEF_NORENDER = 1, PLANEF_DISABLED = 2, PLANEF_OBSTRUCTED = 4 };
constexpr int skyflatnum = -1;
struct sector_t {
    enum { floor, ceiling };
    struct { bool slope = false; double D = 0; bool isSlope() const { return slope; } } floorplane;
    struct { int Flags = 0; } planes[2];
    struct Extra { struct { struct { unsigned count = 0; unsigned Size() const { return count; } } ffloors; } XFloor; } extra;
    Extra* e = &extra;
    int portal = PORTS_SKYVIEWPOINT, texture = 1;
    double alpha = 1, reflect = 0;
    bool fakeHeight = false;
    sector_t* GetHeightSec() { return fakeHeight ? this : nullptr; }
    int GetPortalType(int) const { return portal; }
    double GetAlpha(int) const { return alpha; }
    double GetReflect(int) const { return reflect; }
    int GetTexture(int) const { return texture; }
    bool PortalBlocksView(int plane);
};
''' + old_query + "\n" + guard + r'''
int main() {
    sector_t floor, rendered;
    // The inherited query is false on ordinary floors. Negating it in a
    // rejection guard was the native failure; do not change its semantics.
    assert(!floor.PortalBlocksView(sector_t::floor));
    assert(HasOrdinarySpriteShadowReceiver(&floor, &rendered));
    for (int portal = PORTS_STACKEDSECTORTHING; portal <= PORTS_HORIZON; ++portal) {
        floor.portal = portal;
        assert(!HasOrdinarySpriteShadowReceiver(&floor, &rendered));
    }
    floor.portal = PORTS_SKYVIEWPOINT;
    floor.texture = skyflatnum; assert(!HasOrdinarySpriteShadowReceiver(&floor, &rendered)); floor.texture = 1;
    floor.floorplane.slope = true; assert(!HasOrdinarySpriteShadowReceiver(&floor, &rendered)); floor.floorplane.slope = false;
    floor.fakeHeight = true; assert(!HasOrdinarySpriteShadowReceiver(&floor, &rendered)); floor.fakeHeight = false;
    floor.extra.XFloor.ffloors.count = 1; assert(!HasOrdinarySpriteShadowReceiver(&floor, &rendered)); floor.extra.XFloor.ffloors.count = 0;
    floor.alpha = .5; assert(!HasOrdinarySpriteShadowReceiver(&floor, &rendered)); floor.alpha = 1;
    floor.reflect = .5; assert(!HasOrdinarySpriteShadowReceiver(&floor, &rendered)); floor.reflect = 0;
    rendered.floorplane.D = 1; assert(!HasOrdinarySpriteShadowReceiver(&floor, &rendered));
}
'''
        with tempfile.TemporaryDirectory(prefix="shadow001-receiver-") as temporary:
            program = Path(temporary) / "receiver.cpp"
            program.write_text(code)
            executable = compile_fixture(program, output_dir=temporary, root=ROOT)
            subprocess.run([str(executable)], check=True, timeout=30)

    def test_production_subsector_guard_accepts_one_sided_room_and_rejects_hacks(self):
        """Native b46807a8 failure: a normal boundary carries hacked bit 2."""
        source = (ROOT / "src/rendering/hwrenderer/scene/hw_sprites.cpp").read_text()
        guard = block(source, "static bool HasOrdinarySpriteShadowSubsector(")
        code = r'''
#include <cassert>
#include "hw_sprite_shadow_math.h"
struct sector_t {};
struct subsector_t {
    sector_t* sector;
    sector_t* render_sector;
    void* polys = nullptr;
    char hacked = 0;
    unsigned numlines = 4;
};
''' + guard + r'''
int main() {
    sector_t sector, other;
    subsector_t room{&sector, &sector};
    assert(HasOrdinarySpriteShadowSubsector(&room, &sector));
    // PrepareSectorData marks a one-sided wall with 2, not a render hack.
    room.hacked = 2;
    assert(HasOrdinarySpriteShadowSubsector(&room, &sector));
    for (int flags : {1, 3, 4, 5, 6, 7, 8}) {
        room.hacked = flags;
        assert(!HasOrdinarySpriteShadowSubsector(&room, &sector));
    }
    room.hacked = 2;
    assert(!HasOrdinarySpriteShadowSubsector(nullptr, &sector));
    room.sector = &other; assert(!HasOrdinarySpriteShadowSubsector(&room, &sector)); room.sector = &sector;
    room.render_sector = &other; assert(!HasOrdinarySpriteShadowSubsector(&room, &sector)); room.render_sector = &sector;
    room.polys = &sector; assert(!HasOrdinarySpriteShadowSubsector(&room, &sector)); room.polys = nullptr;
    room.numlines = 2; assert(!HasOrdinarySpriteShadowSubsector(&room, &sector));
    room.numlines = HWSpriteShadow::MaxReceiverEdges + 1; assert(!HasOrdinarySpriteShadowSubsector(&room, &sector));
    room.numlines = HWSpriteShadow::MaxReceiverEdges; assert(HasOrdinarySpriteShadowSubsector(&room, &sector));
}
'''
        with tempfile.TemporaryDirectory(prefix="shadow001-subsector-") as temporary:
            program = Path(temporary) / "subsector.cpp"
            program.write_text(code)
            executable = compile_fixture(program, output_dir=temporary, root=ROOT,
                                         includes=("src/rendering/hwrenderer/scene",))
            subprocess.run([str(executable)], check=True, timeout=30)

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
