# SHADOW-001 M1: synthetic demonstration and Windows handoff

**Candidate status: Draft / HOLD. Physical GPU STOP: ACTIVE.**

The demo contains one original humanoid, one strong side light and one ordinary
floor. Its 48 × 64 source sprite remains deliberately pixelated. Only the
independent shadow proxy is eligible for 4× edge reconstruction. All generated
pixels and map geometry are original CC0-1.0 assets; this package contains no Doom
or Freedoom IWAD or extracted game artwork.

This guide prepares the owner review. It does not authorize a physical GPU launch.
Hosted software Vulkan captures are a separate, authorized qualification route.
An attractive screenshot does not establish physical driver stability or GPU cost.

## Build and prepare

Use the exact source SHA recorded by the candidate PR and build receipt. The
ordinary build produces `vkdoom.exe`, `vkdoom.pk3`, its other PK3 resources, runtime
DLLs, soundfonts and banks. Windows CI packages these without starting Vulkan:

```powershell
python tools/shadow001/package_windows.py --runtime build/RelWithDebInfo --resource-root build --out build/shadow001-windows --expected-commit <exact-source-SHA>
```

The generated ZIP contains `package.json`, which names the source commit and hashes
every payload, the synthetic cases, this guide, license files and a script that
**prints** the launch command. No IWAD or debug symbols are included.

The pure Python fixture preparation can also be run independently:

```powershell
python tools/shadow001/prepare_demo.py --out build/shadow001-demo
```

Preparation never launches an engine. It records `PREPARED`, not a visual PASS.
Reuse a fresh output directory to preserve earlier captures and failed observations.

## Windows owner session, after separate hardware authorization

Extract the candidate ZIP. Supply a legally owned Doom II IWAD or obtain Freedoom2
separately. The printed command accepts a path containing spaces:

```powershell
.\Owner-Launch-Command.ps1 -Iwad 'C:\Games\Doom\doom2.wad'
```

This script prints a command and exits. After the separate physical-test boundary
has been lifted, run that printed command. It loads the synthetic `SHDPLAY` map,
uses an isolated candidate config, disables autoload and starts with ray queries
disabled. It does not change driver settings or reproduce the old fault campaign.

Use the normal movement and mouse-look controls to circle the actor. The console
opens with the usual tilde/backtick key. Type `quit` to exit.

| Console command | Expected result |
| --- | --- |
| `gl_sprite_shadow_mode 0` | Actor remains; both inherited and projected shadows are off. |
| `gl_sprite_shadow_mode 1` | Inherited Legacy/Contact shadow. |
| `gl_sprite_shadow_mode 2` | One light-relative projected silhouette where the floor is eligible. |
| `gl_sprite_shadow_strength 0.78` | Strong theatrical darkening; control remains bounded to 0–1. |
| `gl_sprite_shadow_length 192` | World-space projection bound. |
| `gl_sprite_shadow_quality 1` | Separate 4× edge-antialiased proxy; visible source sprite stays sharp. |
| `gl_sprite_shadow_quality 0` | Native-resolution hard proxy for comparison. |
| `vk_rayquery` | Must report false throughout this demonstration. |
| `map SHDPLAY` | Player-controlled camera around stationary actor and light. |
| `map SHDORBIT` | Camera circles automatically; actor and light remain stationary. |
| `map SHDROT` | Fixed camera while the actor turns. |
| `map SHDMOVE` | Fixed camera while the actor moves. |
| `map SHD001` | Fixed reference composition. |

`r_actorspriteshadow 2` enables inherited actor eligibility; the synthetic humanoid
also explicitly sets `CASTSPRITESHADOW`. Keep this enabled while comparing the new
three-way mode control. The ordinary default remains Legacy/Contact.

## What to judge

Compare Off, Legacy and Projected from the same camera. The new shadow should show
the humanoid's head, rifle, separated legs and the gap beside its bent arm. It
should feel crisp and dramatic, with just enough edge antialiasing to avoid crawling.

Watch `SHDORBIT`: the visible billboard can choose another view, but the cast
silhouette must stay anchored to the same actor/light direction. Then watch
`SHDROT` and `SHDMOVE`: changes in the actor pose should move the projection
without a persistent trail. Confirm the original visible pixels remain sharp.

The first slice is intentionally bounded to an eligible ordinary horizontal floor
and one point light. Unsupported actors, low/invalid lights, portals, 3D floors,
sloped receivers, models and special translucent styles fall back through the
retained inherited route. It does not cast wall shadows or model a shadow volume.

## Hosted software evidence

The source-matched runner uses the existing strict GitHub-hosted CPU Vulkan guard,
an isolated lavapipe ICD, one clean binary and short bounded native observations:

```bash
python3 tools/shadow001/run_demo.py \
  --exe build/vkdoom \
  --iwad /usr/share/games/doom/freedoom2.wad \
  --expected-commit "$SOURCE_SHA" \
  --out build/shadow001-native
```

The caller supplies Xvfb and the same verified `VK_DRIVER_FILES` and
`VK_ICD_FILENAMES` settings as the existing software-Vulkan jobs. This runner has
no physical-mode switch. Do not spoof hosted-runner variables to bypass its guard.

The nine visual cases are Off, Legacy, Projected, three alternative camera poses,
a rotated actor, a moved actor and a deliberately low/invalid light. Each successful case
retains a genuine `native.png`, the native observer JSON, config, full stdout/stderr,
and exact source/executable/input identity. The runner rejects missing projected
draws and requires visible darkening. Camera comparisons use the actual selected
source/mirror/light and projected world geometry, not exact image/counter equality.

A tenth case exercises the projected mask's cached Vulkan resources through four
ordinary texture-filter/anisotropy changes. It keeps the same scene, runs 32 warmup
and 40 observed frames, and checks every actual main-frame setting, emitted shadow,
live mask descriptor generation and selected sampler. Retired descriptor tokens
must not reappear after reset. This case temporarily changes global filtering to
exercise the real reset path, then restores nearest filtering; it does not change
the source sprite pixels. The first nine visual captures keep their original
12 warmup / 3 observed frame budget. No exact RGB repetition is required.

Every case also passes the shared observer's frame, context, material, pipeline and
resource integrity checks. Projected cases require a bounded emitted shadow mesh
in every observed frame. Native validation failures remain failures.

`qualification.json` reports machine checks separately from **owner visual
acceptance**, which remains pending. CPU tests and prepared input files cannot
substitute for these native screenshots. Failed logs and captures are retained;
there is no automatic retry or benchmark campaign.

The Windows package is also independent evidence: compilation and packaging do not
mean it has been run on a physical GPU. The next owner action is to inspect the
hosted images and decide whether the projected silhouette merits further work.
