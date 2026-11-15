# SHADOW-002 — dynamic-light actor occlusion replacement research

**Status:** EXPERIMENTAL CODE, NOT VISUALLY ACCEPTED, NO MERGE. Parent goal [#204](https://github.com/techrote/ShadeDoomVK/issues/204). The old floor-decal [PR #212](https://github.com/techrote/ShadeDoomVK/pull/212) was closed unmerged after owner rejection.

## Source baseline and non-negotiable art

- Branch starts at `master@f787f7199fc7560588bb9440b3dd0aa663cb53de`, which contains [PR #195](https://github.com/techrote/ShadeDoomVK/pull/195) merged at `2cc70f33295881f73c7460364c6fa8e4e546efb3`.
- Preserve the **original** [PR #190](https://github.com/techrote/ShadeDoomVK/pull/190) generator, material maps, flashlight and colour/normal/PBR response. Do not copy the ad hoc replacement generator.
- No floor decals, screen-space output darkening, blanket colour attenuation or artificial GPU prohibition. Preserve normal player input, sound, weapons and map navigation in eventual Windows builds.

## Correct rendering integration

The *actual local dynamic light* is the emitter. The live actor is the caster. The currently shaded world fragment is the receiver. The ray from emitter to receiver either intersects a valid caster or remains illuminated. **Only this emitter's diffuse/specular/PBR contribution is attenuated**, before compositing with other dynamic lights and ambient/probe terms.

The receiver is any eligible actual world fragment, including real walls and floors; no fake receiver mesh or horizontal-floor restriction. Existing world occlusion stays separate. A flashlight may cast actor shadows even if it does not use the world shadowmap.

## Current technical first slice, not approved art

Seven source files now carry up to **four selected local actors per light** using renderer x/height/y coordinates, a finite-height geometric ray/cylinder test, same-portal-group and live actor selection, and a bounded per-frame cache. `gl_actor_light_shadows` remains **default OFF** until native qualification.

**This is explicitly a geometric stand-in, NOT a sprite-frame alpha cutout, nor a finished visual effect.** A cylindrical shadow is not sufficient for the owner's Doom 3 / Splinter Cell visual standard. It must be replaced by an actor-light-facing source-alpha silhouette with correct animation, rotation, mirroring, authored masks and opacity before visual approval. The first slice is meant to validate per-emitter shading semantics and real world receivers, not win visual acceptance.

The actor-caster array increases packed `FDynLightInfo` from 80 to 224 bytes; C++/GLSL ABI, buffer capacity and LevelMesh and immediate lighting require compiler/native qualification. Up to four nearest in-group shootable actors per light are considered; this limit, offscreen handling, portal recursion, transparency and model alternatives are not complete.

## Mandatory qualification

1. C++/`std430` packed ABI, real Windows/Linux builds, shader variants and legacy OFF parity on the exact revision.
2. Native software Vulkan: two differently coloured dynamic lights, one real actor, one wall and one floor. Verify source-specific attenuation of direct lighting and preserved other light/sector/IBL. A single dark-pixel count is insufficient.
3. Light/actor motion and stationary-camera versus camera-orbit tests, opposite-direction cast, finite height/depth and negative portal cases, no self-shadowing, multiple casters, resource reinitialisation.
4. Complete the **source-alpha silhouette** instead of capsule proxy, with light-relative sprite rotation/mirroring and independently antialiased cutout. No visible sprite albedo changes.
5. Native Windows owner playtest: source-matched PR #195 renderer with PR #190's actual PBR assets and flashlight loaded, normal player controls and a useful real map; GPU hardware and honest feature readback.
6. Representative ON/OFF cost and bounded quality profile on older Vulkan GPUs.

**NO-GO:** Do not merge, distribute this as a visually finished implementation, or close #204 until all above gates and owner acceptance pass. Keep the old #212 implementation historical and unmerged.

Source: `hw_dynlightdata.h`, `hw_dynlightdata.cpp`, `binding_struct_definitions.glsl`, `light_shadow.glsl`, `lightmodel_{normal,specular,pbr}.glsl`. Contract tests: `tools/pf_oracle/tests/test_actor_dynamic_shadow.py`.

## Evidence on source preparation

- Independent numerical reference (floor/wall, unaffected second light, self and depth misses): PASS locally.
- C++ and GLSL, Windows/Linux native run, PBR readback, original sprite silhouette: **NOT YET VERIFIED**.
