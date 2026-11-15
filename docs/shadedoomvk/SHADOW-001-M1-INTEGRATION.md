# SHADOW-001 M1 — bounded light-relative floor projection

**Implementation baseline:** `f787f7199fc7560588bb9440b3dd0aa663cb53de`.  
**Tracking:** [SHADOW-001 #204](https://github.com/techrote/ShadeDoomVK/issues/204).  
**Disposition:** Draft/HOLD; no merge, owner visual acceptance or physical-GPU resumption is implied.

## M0 decision and source inventory

Use an independent representation carried by the existing translucent sprite draw list. `HWSprite::Process` first attempts the projected path only when processing an eligible shadow in Projected mode; rejection continues into the inherited floor-grounding implementation. The visible sprite follows the original code path.

| Existing source seam | M1 decision |
| --- | --- |
| `hw_sprites.cpp`: viewer-relative frame selection, orientation and legacy shadow | Independently call the same frame-selection rules with actor-minus-light direction; preserve animation, flip and source offsets. |
| `hw_sprite_surface.h` / `hw_sprite_tangent.h`: original billboard/TBN semantics | Keep visible-card semantics unchanged; shadow vertices already lie on the receiver and bypass billboard transformation. |
| Actor section dynamic-light list and CPU `levelMesh->Trace` | Select one visible eligible same-sector point light without consulting camera-facing sprite selection or ray-query support. |
| Ordinary render subsector edges | Clip the projected strip polygons to one convex floor receiver; reject unsupported geometry and invalid rays. |
| `HWDrawList` raw arena allocation and billboard splitting | Store plain frame-arena pointers; avoid splitting a projected triangle mesh as a billboard. |
| `FGameTexture` ownership and hardware reset | Own shadow masks beneath the original source, retire descriptors through existing texture/material cleanup, and serialize lazy generation. |

This is a depth-tested **dark decal approximation** that attenuates the composed floor image, not solely the selected light contribution. It is neither a stencil-buffer shadow volume nor ray-traced sprite geometry. Small strip subdivision bounds affine texture interpolation error without adding a projective shader or changing Vulkan descriptors.

## Mask and pose

The source image's actual BGRA alpha is sampled into separate one-byte coverage. Default quality reconstructs its contour at 4x using bilinear coverage and a narrow smoothstep; there is no dilation, pinhole filling or smoothing of the original artwork. Native 1x masks are an optional lower-quality setting. Meaningful leg, arm and rifle gaps remain part of the source silhouette.

Each source owns both quality variants. A maximum mask dimension of 512 and a 16 MiB estimated aggregate mask/upload budget bound allocation. M1 stores R8 CPU coverage and uses the engine's existing RGBA upload path, including that bridge/mips in the budget. A dedicated GPU R8 path, authored overrides and cache eviction are follow-on work, not prerequisites hidden in this implementation. The per-source mask acquisition seam keeps those extensions separate from visible materials.

The caster frame is selected from the actor's current frame/facing and the selected light's position. No viewer position enters that frame-selection expression. The independently generated geometry remains world-anchored as the displayed billboard changes around it. Current actor interpolation is read; simulation, animation state, collision and input are not written.

## Receiver and fallback

M1 accepts ordinary opaque face sprites in truecolour, one eligible point light above the source silhouette, and a horizontal ordinary floor in the same sector. It rejects unsupported views/portals, slopes, 3D/fake or reflective/translucent floors, model/picnum/special/translucent casters, missiles, source/global/map/class custom shader overrides, unsuitable source images, unavailable visibility, degenerate rays, excessive projected length and occlusion. It uses existing opaque depth and a small bias instead of floating the mesh above the floor.

The maximum length setting is a rejection bound: when a projection would exceed it, this slice falls back to Legacy/Contact. It does not clamp the head of an overlong silhouette into an arbitrary shape. Receiver clipping is intentionally conservative and may truncate at an internal BSP boundary even when a neighbouring floor looks equivalent. Projection budget exhaustion also falls back. These are visible M1 limitations, not claims of general receiver support.

## Controls and evidence

`gl_sprite_shadow_mode`: 0 Off, 1 Legacy/Contact (default), 2 Projected. `r_actorspriteshadow` continues to choose eligible actors. Strength, length and edge-quality controls are in the Display menu and documented in the [Windows/demo handoff](SHADOW-001-M1-PLAYTEST.md).

Focused CPU tests execute the same mask-generation, projection and clipping functions, including meaningful holes, mirroring, invalid rays and receiver bounds. Existing sprite orientation/tangent/portal tests remain applicable. Full linked compilation and shader/runtime validity belong to hosted CI; local syntax-only checks are not relabelled as a linked build.

The original CC0 demo under `tools/shadow001` produces Off/Legacy/Projected views, fixed-actor camera-orbit views, changed actor poses and a rejected low-light case with ray queries disabled. Its hosted harness requires actual projected draw records and visible darkening, compares light-relative source/mesh identity across camera positions, and retains genuine framebuffer PNGs. Interactive orbit/rotation/movement maps are provided separately from the bounded captures. Visual quality still requires inspection; counters alone cannot accept the feature. No physical GPU test is authorised.
