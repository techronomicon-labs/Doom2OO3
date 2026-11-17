# Emitter lighting evaluation

Start in Doom II Entryway and press **B** to compare emitter lighting with the legacy renderer. **F1** opens the emitter settings and comparison rooms. **L** toggles the flashlight, **J** cycles flashlight shadows through Off, Stencil and Depth, and **O** opens beam and shadow settings. **R** compares world relief and **V** compares sprite relief.

**Legacy ambient fill** controls room brightness from the original sector lighting, lightmaps, diffuse probe lighting, and map sunlight. **PBR ambient reflections** controls how strongly PBR materials reflect ambient light, including reflections from light probes where present. Both sliders range from 0 to 1 and default to 0.35 in emitter mode. Direct highlights from the flashlight and authored emitters respond to their own light settings.

For an emitter-only comparison, enable emitter lighting with **B**, set both ambient sliders to zero in **F1**, and keep **Emitter intensity** at 1. Press **B** again to compare the same view with legacy lighting. Use **L** to include or remove the flashlight in either view.

**Emitter intensity** controls authored room and sky lighting. Set it and both ambient sliders to zero for a flashlight-only view with visible self-emitting materials. Flashlight power, spread, and range have independent controls.

The flashlight starts 16 map units forward and 12 below eye level, with a 4° upward aim. Open **Position and aim** in **Flashlight settings** to change or reset the mount.

## Edit a material

Open **PBR materials** from **F1** or **Options**. Aim at a wall, floor, or ceiling and choose **Pick aimed surface**, or enter a texture name such as `BRONZE1` or `sprite:TROOA1` under **Find by texture name**. Add `wall:`, `flat:`, or `sprite:` if a name is shared. Each change applies to every use of that material and previews in the scene behind the menu.

Roughness and metallic offsets adjust the authored maps. Normal and ambient occlusion strength scale the corresponding map effects. **Relief depth strength** scales the height map using the active world or sprite relief settings. Use **Save material settings** to write the selected material's values to the `.materials` file beside the active game configuration. **Preview material defaults** restores the authored finish. Save again to keep the reset.

## Build and launch

```powershell
py tools/doom2_showcase/build.py --doom2 C:\doom2.wad --relief --sprite-relief `
  --emitter-lighting --out build/emitter-addons
.\tools\doom2_showcase\launch.ps1 -Game DoomII -Relief -SpriteRelief -EmitterLighting `
  -Exe .\build\windows\RelWithDebInfo\vkdoom.exe -Doom2 C:\doom2.wad -Packages .\build\emitter-addons
```

The stock Doom II campaign and three comparison rooms support emitter lighting. Each campaign layout checks the map checksum before placing emitters. Stock levels without a visible light source still respond to the ambient controls and flashlight. Unrecognized maps use the legacy renderer unless they supply emitters. Emitter lighting starts off and uses the immediate Vulkan renderer in true color. Level mesh, ubershaders, dynamic lightmapping, ray tracing, palette rendering, powerup vision, and offscreen views use their established paths.

## Lighting and coverage

Opaque walls and floors and ordinary per-pixel-lit actor sprites receive point and directional emitters. Retained ambient fill also picks up subtle slope contrast on PBR walls and floors with relief. At zero fill that contribution is zero. Brightmaps and glow materials keep a separate self-emission term. The world path filters legacy dynamic lamps in emitter mode. The local flashlight contributes independently. Sky pixels, additive and translucent effects, custom shaders, fullbright sprites, and viewmodels use their existing shading paths.

Point sources use a configurable radius and falloff. A directional source provides a constant light direction inside its authored sector, with a soft range edge. Both use the engine's existing shadow map from the authored anchor. The directional approximation is suitable for bounded courtyards and openings. Large sky regions and height-dependent occlusion need separate authoring. Each source is scoped to its own sector, so adjacent closed rooms receive no contribution. The renderer uses at most 48 nearest emitter shadow rows per view and 12 authored emitters per receiver.

The local authoring pack defines `SDVKStageBPointEmitter` and `SDVKStageBDirectionalEmitter`. Each authored emitter record specifies its receiver sector, position and floor-relative height, RGB, radius, intensity, and falloff. Directional emitters also specify yaw and pitch. In Entryway's green corridors, the yellow `TEKGREN5` wall strips emit warm-white light from their original texture coordinates. The `GRNLITE1` ceiling circles are matte plastic. Entryway also uses the `FLAT2` overhead fixtures, a small exit sign source, and consistent outdoor light. The bronze recess behind the player start receives the chosen ambient fill and the player's flashlight.

Campaign layouts use visible lamp and flame surfaces, lamp and torch decorations, and open sky. Underhalls' overhead fluorescent fixtures and open courtyard provide local lighting, while dark parts of the sewer rely on ambient fill and the flashlight. Open **Underhalls** from **F1** to jump straight there. The material pack binds the normal, roughness, and relief maps to textures so each surface keeps its finish wherever the same texture appears. Switch plates use their own relief, shared by both switch states.

## Reproduce the native comparisons

```powershell
py tools/doom2_showcase/capture_stageb_lighting.py `
  --exe build/windows/RelWithDebInfo/vkdoom.exe --iwad C:\doom2.wad `
  --materials build/emitter-addons/DoomII-NormalPBR.pk3 `
  --flashlight build/emitter-addons/Local-Flashlight.pk3 --out build/emitter-evidence
```

Use a new output directory. The batch includes interior point lights, a directional courtyard, the sealed-room control, and stock Entryway. The sealed room checks for light crossing the wall, legacy ambient at zero fill, and the response to the independent flashlight.

Add `--case MAP01-corridor --case MAP02-lamp --case MAP02-yard` to compare Entryway’s yellow wall strips, Underhalls’ fluorescent fixtures, and its courtyard. Each scene shows legacy lighting, zero ambient with emitters, and zero ambient with emitter intensity muted. The manifest records the matched camera poses, selected sources, native renderer identity, image differences, and file hashes.

Repeat the command with `--timing`, a fresh output directory, and the cases you want to measure. Timing defaults to 120 uncapped frames at 1280 × 960 per mode, with VSync off. `--size WIDTH HEIGHT` and `--frames N` change the sample. The report records median and 95th-percentile frame spacing, CPU `RenderView` time, and individual Vulkan timestamp groups. The GPU groups measure specific passes and can overlap.
