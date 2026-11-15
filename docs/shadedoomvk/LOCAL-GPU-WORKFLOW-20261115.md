# ShadeDoomVK: Local GPU development is the default

**Owner direction: 15 November 2026. Current operational guidance for project work on GPU-equipped computers.**

**Intent:** If a ShadeDoomVK development or evaluation task is executed on a machine with a usable GPU, **use that GPU** for rendering, visual iteration, playable test builds, feature integration, performance profiling and relevant validation. This is standing owner authorisation for ordinary project GPU work; **do not request a fresh, ceremonial permission for each run**.

- Real native rendering and an interactive, playable build are the expected default. Do not ship a launcher that only *prints* a command, disables input/audio or quietly disables supported visual features and call it a graphics evaluation.
- Nightly/evaluation handoffs should exercise the fullest mutually compatible implemented feature set, with practical quality defaults and simple toggles. Generate/load user-owned PBR assets locally, include local-light add-ons, preserve movement/HUD, and clearly describe any missing or incompatible effect. Diagnostic capture fixtures must be separate.
- GPU-equipped local runners should use hardware for the tests they exist to perform; software Vulkan is useful as additional portable CI coverage, **not a compulsory substitute** for real-GPU verification.
- Keep useful build, driver, feature and artifact provenance and report real crashes/failed checks. **A known repeatable driver-timeout or destructive stress reproducer is a *specific* engineering hazard**: do not blindly loop the same failure or alter hardware firmware/power settings without direction. Investigate that scenario with proportionate precautions, rather than declaring all GPU work forbidden.
- Historical GPU STOP / supervisor documents remain **unaltered records of their original dates and incidents**. They do not impose a general GPU ban on current ordinary owner-authorised local tasks. No historical failed attempt is changed into PASS; an ordinary GPU run alone still does not prove general hardware stability.

This operational direction supersedes earlier blanket *permission* interpretations for current work. It does **not** retroactively change historical data, merge any pending PR, or waive meaningful technical acceptance tests.

Context: [AGENTS.md](../../AGENTS.md), [RAG index](rag/README.md), [owner-approved visual campaign](https://github.com/techrote/ShadeDoomVK/blob/planning/lost-2003-remaster-20261114/docs/shadedoomvk/REMASTER-2003-CAMPAIGN.md), [historical #202 measurement boundary](SDVK-014-GPU-TIMING-BOUNDARY.md).
