# Virtual position lighting — isolated world PBR experiment

**Purpose:** Make a planar wall or floor appear closer to or farther from a moving dynamic light using authored height as a *lighting* signal. This is deliberately **not** a shadow, parallax, displacement, cavity or occlusion feature.

## A/B control

Generate a fresh world material pack with the existing local showcase builder and the owner's installed game assets. World texture/flat packs now include a `height` channel. The original artwork and existing PBR channels remain unchanged.

In the Vulkan renderer's console:

- `gl_world_virtual_relief_depth 0` — original lighting (default).
- `gl_world_virtual_relief_depth 8` — moderate virtual lighting depth.
- `gl_world_virtual_relief_depth 16` — strong experimental depth (maximum).

Depth is measured in Doom world units across the entire 0..1 height range; 0.5 is the actual plane. Compare OFF/ON while moving the flashlight across metal walls, brickwork and floors.

## Implementation boundary

For an opaque, unwarped PBR **world wall/flat** with height, evaluate local dynamic lights at `virtualPos = geometricPos + geometricNormal * ((height - 0.5) * depth)`. BRDF view/light vectors, light distance and spotlight cone use the virtual position. Normal-map shading stays intact.

Actual geometry, UVs, depth testing, existing shadow rays, portal transforms, sprite/model rendering, sunlight, ambient, probes, fog, collision and gameplay use real positions. No new geometry or ray marches. Every material bind resets the mode; only normal opaque world draw paths explicitly enable it.

## Boundaries and acceptance

This is aimed at forward/immediate dynamic-light PBR. Indexed modes, non-PBR surfaces, sprites, warped materials and translucent/special planes have no effect. Light lists and world shadow occlusion still follow real geometry. Source-derived height is a visual approximation; paint can be misclassified as depth.

**Windows GPU visual acceptance is still required.** Compare 0/8/16 while walking and sweeping the flashlight. Reject visible detachment, excessive highlight jumps, new light leaks, flicker or baseline regressions. Do not merge or enable by default without explicit owner acceptance.
