# SHADOW-002 — dynamic-light actor occlusion replacement research

**Status:** EXPERIMENTAL CODE, NOT VISUALLY ACCEPTED, NO MERGE. Parent goal [#204](https://github.com/techrote/ShadeDoomVK/issues/204). The old floor-decal [PR #212](https://github.com/techrote/ShadeDoomVK/pull/212) was closed unmerged after owner rejection.

## Source baseline and non-negotiable art

- Branch starts at `master@f787f7199fc7560588bb9440b3dd0aa663cb53de`, which contains [PR #195](https://github.com/techrote/ShadeDoomVK/pull/195) merged at `2cc70f33295881f73c7460364c6fa8e4e546efb3`.
- Preserve the **original** [PR #190](https://github.com/techrote/ShadeDoomVK/pull/190) generator, material maps, flashlight and colour/normal/PBR response. Do not copy the ad hoc replacement generator.
- No floor decals, screen-space output darkening, blanket colour attenuation or artificial GPU prohibition. Preserve normal player input, sound, weapons and map navigation in eventual Windows builds.

## Correct rendering integration

The *actual local dynamic light* is the emitter. The live actor is the caster. The currently shaded world fragment is the receiver. The ray from emitter to receiver either intersects a valid caster or remains illuminated. **Only this emitter's diffuse/specular/PBR contribution is attenuated**, before compositing with other dynamic lights and ambient/probe terms.

The receiver is any eligible actual world fragment, including real walls and floors; no fake receiver mesh or horizontal-floor restriction. Existing world occlusion stays separate. A flashlight may cast actor shadows even if it does not use the world shadowmap.

## Current technical source-alpha prototype, not yet visually accepted

The active code now generates an **independent 16×32 cutout mask from the selected source sprite frame's actual alpha**, using the light position to choose its viewing rotation. The chosen sprite's original albedo, source texels and normal/PBR materials are not altered. Correct camera-facing gameplay sprite output remains on the inherited path.

- The CPU dynamically selects up to four closest eligible live actors for each local light. The actor's frame/mirroring is selected **from that light**, not from the player's viewpoint.
- The material system's normal sprite source is decoded once per texture/frame cache entry. Transparent source pixels produce clear bits. A per-caster mask, authored rectangle coordinates, horizontal light-facing plane and flip flags are copied through the dynamic-light SSBO.
- In the **normal, specular and PBR fragment-light paths**, the shader intersects each light→world-fragment segment with each caster's light-facing sprite plane. At the intersection it tests the independently reconstructed source-alpha bit. The light contribution is zero where the source cutout is opaque; other local lights, sector colour and IBL remain untouched.
- Any real world receiving fragment already being shaded (floor, wall, etc.) can receive the effect. There is **no projected-floor mesh or final-color darkening pass**.
- The packed `FDynLightInfo` record is currently **544 bytes** (source/ABI tests and actual native compilation required). The mask is 16×32 binary, not high-quality per-pixel alpha antialiasing. Cached alpha reads are per source texture and observed frame, then selected per dynamic light.
- The experimental `gl_actor_light_shadows` control stays default OFF pending native shader correctness evidence; the separate owner research script requests it ON.

### Limits requiring follow-on engineering

This is not yet proof of acceptable 2003-remaster visuals: the mask is coarse (thin arms/guns need attention); only upright source sprites from eligible shootable actors are selected; models, wall/flat sprites, picnum overrides, partial translucency, soft penumbra, cross-portal ownership and recursion have not been validated. Source flip/offset/orientation must be confirmed against the existing final sprite billboard in real captures, and actor masks may need a higher-resolution atlas rather than inflating all light records for crowded scenes. Shadows are currently binary per contributing light, without a light-size penumbra model.

It is incorrect to call this shader a full stencil volume, ray-traced alpha geometry or completed feature. Source math and static assertions are **not** a substitute for native images and the owner's visual acceptance.

## Mandatory qualification

1. C++/`std430` packed ABI, real Windows/Linux builds, shader variants and legacy OFF parity on the exact revision.
2. Native software Vulkan: two differently coloured dynamic lights, one real actor, one wall and one floor. Verify source-specific attenuation of direct lighting and preserved other light/sector/IBL. A single dark-pixel count is insufficient.
3. Light/actor motion and stationary-camera versus camera-orbit tests, opposite-direction cast, finite height/depth and negative portal cases, no self-shadowing, multiple casters, resource reinitialisation.
4. Validate the selected light-facing **source-alpha silhouette**, rotation, animation, frame mirroring and sprite offsets against genuine native captures; then improve edge/penumbra quality. No visible source sprite albedo changes.
5. Native Windows owner playtest: source-matched PR #195 renderer with PR #190's actual PBR assets and flashlight loaded, normal player controls and a useful real map; GPU hardware and honest feature readback.
6. Representative ON/OFF cost and bounded quality profile on older Vulkan GPUs.

**NO-GO:** Do not merge, distribute this as a visually finished implementation, or close #204 until compiler/hosted native proof, accurate silhouette/camera motion tests, real Windows evaluation, representative performance and owner visual acceptance pass. Keep the old #212 implementation historical and unmerged.

Source: `hw_dynlightdata.h`, `hw_dynlightdata.cpp`, `binding_struct_definitions.glsl`, `light_shadow.glsl`, `lightmodel_{normal,specular,pbr}.glsl`. Contract tests: `tools/pf_oracle/tests/test_actor_dynamic_shadow.py`.

## Evidence on source preparation

- Independent numerical reference (floor/wall, source-alpha holes, unaffected second light, endpoint and height misses): PASS locally before conversion to GPU source.
- Revised C++ and GLSL light-facing alpha path, Windows/Linux native run, PBR readback, sprite orientation/mask quality: **NOT YET VERIFIED**. Earlier finite-height-only Windows build does not count for this revision.
