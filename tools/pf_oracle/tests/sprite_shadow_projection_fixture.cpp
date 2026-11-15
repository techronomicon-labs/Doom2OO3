// Synthetic CPU regression vectors for the actual production projection/mask.
#include "hw_sprite_shadow_math.h"
#include "shadowmask.h"
#include <cassert>
#include <limits>

int main()
{
    using namespace HWSpriteShadow;
    const Point light{-96, -64, 128}, actor{0, 0, 0};
    Vertex v{};
    assert(Project(light, {0, 0, 64}, 0, 192, actor, v));
    assert(v.x == 96 && v.y == 64 && v.z == 0);
    assert(Project(light, actor, 0, 192, actor, v));
    assert(v.x == 0 && v.y == 0 && v.z == 0);
    // Nearly parallel, light below head, backwards ray, below receiver,
    // overlong projection and nonfinite inputs must never reach the GPU.
    assert(!Project(light, {0, 0, 125}, 0, 192, actor, v));
    assert(!Project(light, {0, 0, 140}, 0, 192, actor, v));
    assert(!Project({0, 0, -10}, {0, 0, -30}, 0, 192, actor, v));
    assert(!Project(light, {0, 0, -1}, 0, 192, actor, v));
    assert(!Project(light, {0, 0, 64}, 0, 32, actor, v));
    assert(!Project(light, {std::numeric_limits<double>::quiet_NaN(), 0, 64}, 0, 192, actor, v));
    assert(!Project(light, actor, 0, std::numeric_limits<double>::infinity(), actor, v));
    // The receiver is not world Z=0: raised ordinary floors stay planted.
    assert(Project({-96, -64, 160}, {0, 0, 96}, 32, 192, {0, 0, 32}, v));
    assert(v.x == 96 && v.y == 64 && v.z == 32);

    // Asymmetric source pivot must mirror about the actor, including offsets.
    const auto p = CardPoint(actor, 0, 1, 48, 64, 17, 64, .25, .5, false, 3);
    const auto mirrored = CardPoint(actor, 0, 1, 48, 64, 17, 64, .25, .5, true, 3);
    assert(p.x == 0 && p.y == 8 && p.z == 32);
    assert(mirrored.y == -2 && mirrored.z == p.z);
    const auto rotated = CardPoint(actor, -1, 0, 48, 64, 17, 64, .25, .5, false, 3);
    assert(rotated.x == -8 && rotated.y == 0 && rotated.z == 32);
    // Camera pose is deliberately not an input to either function.
    Vertex before{}, after{};
    assert(Project(light, p, 0, 192, actor, before));
    assert(Project(light, p, 0, 192, actor, after));
    assert(before.x == after.x && before.y == after.y && before.z == after.z);

    const std::vector<Edge> room{{-8,-8,8,-8}, {8,-8,8,8}, {8,8,-8,8}, {-8,8,-8,-8}};
    const std::vector<Vertex> card{{-16,-4,0,0,0}, {16,-4,0,1,0}, {16,4,0,1,1}, {-16,4,0,0,1}};
    const auto clipped = Clip(card, room, actor);
    assert(clipped.size() == 4);
    for (const auto& point : clipped)
    {
        assert(point.x >= -8 && point.x <= 8 && point.y >= -8 && point.y <= 8);
        assert(point.u >= .25 && point.u <= .75 && point.v >= 0 && point.v <= 1);
        assert(point.z == 0);
    }
    auto reversed = room;
    for (auto& edge : reversed) { std::swap(edge.x1, edge.x2); std::swap(edge.y1, edge.y2); }
    assert(Clip(card, reversed, actor).size() == clipped.size());
    assert(Clip({{20,20,0,0,0},{24,20,0,1,0},{24,24,0,1,1},{20,24,0,0,1}}, room, actor).empty());
    assert(Clip(card, {}, actor).empty());
    auto invalidRoom = room; invalidRoom[0].x2 = invalidRoom[0].x1; invalidRoom[0].y2 = invalidRoom[0].y1;
    assert(Clip(card, invalidRoom, actor).empty());

    // Two legs and a one-source-pixel air gap. RGB is arbitrary and must be
    // irrelevant; the input bytes remain identical after mask construction.
    std::vector<uint8_t> source(5 * 5 * 4, 93);
    for (int y = 0; y < 5; ++y)
        for (int x = 0; x < 5; ++x) source[(y * 5 + x) * 4 + 3] = (x == 1 || x == 3) ? 255 : 0;
    const auto original = source;
    const auto mask = MakeMask(source.data(), 5, 5, 20, 4);
    assert(mask.size() == 400 && source == original);
    assert(mask[10 * 20 + 9] == 0 && mask[10 * 20 + 10] == 0);
    assert(mask[10 * 20 + 5] == 255 && mask[10 * 20 + 14] == 255);
    bool antialiased = false;
    for (auto alpha : mask) antialiased |= alpha > 0 && alpha < 255;
    assert(antialiased);
    const auto hard = MakeMask(source.data(), 5, 5, 20, 1);
    for (unsigned i = 0; i < hard.size(); ++i) assert(hard[i] == source[i * 4 + 3]);
    assert(MakeMask(nullptr, 5, 5, 20, 4).empty());
    assert(MakeMask(source.data(), 5, 5, 19, 4).empty());
    assert(MakeMask(source.data(), 5, 5, 20, 8).empty());
    assert(MakeMask(source.data(), 129, 5, 516, 4).empty());
    assert(MakeMask(source.data(), -1, 5, 20, 4).empty());
}
