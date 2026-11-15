# Doom2OO3 — agent instructions

This is a deliberately stripped, playable engineering baseline. It retains the code and all accepted crash, Vulkan-synchronization, descriptor-lifetime, rendering-correctness and performance fixes through ShadeDoomVK PR #195 (merge commit `2cc70f33295881f73c7460364c6fa8e4e546efb3`).

## Authority
The owner's current explicit instructions, the checked-in working source, and this document govern new work. Historical ShadeDoomVK/PF/CFX/SDVK issue plans, buried commit messages, old validation policies and evidence campaigns are **not** a development roadmap, required prerequisite, or standing prohibition. Consult them only to investigate a concrete code defect. Never resurrect the old serial programme or its multi-hour CI requirements by default.

## Product
Deliver an attractive, playable, 2003-era-inspired Doom II remaster. Keep original visible sprite and texture art crisp and recognisable. Preserve the functional #190 Doom II/DBP50 PBR material generators, flashlight and gallery; later #191–195 corrections and all earlier renderer fixes are part of the baseline. Add expressive local light response, compelling actor/environment shadows, and usable material controls without altering gameplay or content semantics.

## Hard lessons
- **Do not** create fake actor shadows by stamping a final-composite dark floor decal. A shadow must be derived from an *actual contributing light*, a light-relative actor/sprite silhouette and its real receiving geometry. Attenuate only that light's applicable lighting contribution; do not darken ambient, unrelated emitters, or probes. Honour occlusion, portal groups and supported floor/wall receivers, with honest fallbacks.
- Never replace the working #190 material/flashlight pipeline with an unqualified generator or synthetic substitute.
- Do not silently discard confirmed memory/resource-lifetime, descriptor, synchronization, compatibility, or performance fixes merely to simplify a new feature.
- No mandatory ray tracing or hardware RT. No mandatory source-sprite upscale, blur, or altered collision.
- Software Vulkan can check correctness; **owner evaluation is a real, playable Windows build on an actual GPU**. Do not substitute an hour-long CPU-rendered capture or a print-only launcher for the requested deliverable. Do not launch hazardous GPU stress tests in an uncontrolled environment.

## Development loop
1. Start from current `master` and inspect actual implementation seams before changing code.
2. Implement one small but complete visual improvement. Make it playable and visible with effect OFF/ON, and preserve existing features.
3. Compile affected targets and run short, relevant positive and negative tests. Crashes, invalid Vulkan resource use, synchronization violations and gameplay regressions block the affected change.
4. Deliver a runnable Windows build/package when requested. State exactly what changed, what was actually tested, and what remains unverified. The owner judges appearance; green CI cannot overrule a visibly poor result.
5. Keep documentation short and current. Do not regenerate a historical issue graph, RAG empire, evidence megastore, or blanket forensic qualification system.

The internal binary still uses inherited `vkdoom`/`vktool` names and some `SDVK_` identity symbols; these are compatibility/build identifiers, **not** instructions to resume the previous programme. See `README.md` and `docs/BUILDING.md`.
