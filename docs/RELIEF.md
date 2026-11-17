# Stage A relief evaluation

Build the current Windows runtime as described in [BUILDING.md](BUILDING.md). Generate the opt-in materials and playable preview rooms from your local Doom II WAD. The pack evaluates every stock wall and flat, retaining the original hand-authored profiles and adding material-specific height for seams, panels, grilles, carved details and rough surfaces. Skies, moving liquids, masked cutouts and deliberately featureless surfaces keep their original response. The generated `material-build.json` lists the profile or fallback for each input. The engine defaults to relief off.

```powershell
py -m pip install numpy "Pillow>=10.1"
py tools/doom2_showcase/build.py --doom2 C:\doom2.wad --relief --out build/relief-addons
.\tools\doom2_showcase\launch.ps1 -Game DoomII -Relief `
  -Exe .\build\windows\RelWithDebInfo\vkdoom.exe -Doom2 C:\doom2.wad -Packages .\build\relief-addons
```

The launcher opens at the same grazing concrete view used in the capture batch, with the flashlight already on. Press **R** or middle-click to compare relief OFF and ON in place. The overlay reports both the relief and flashlight states. **F1** opens the room selector. **Page Up**, **Page Down**, and the mouse wheel cycle through the preview materials. Walk sideways along the surfaces or sweep the flashlight to see how the joints respond at other angles.

Add `-ReliefStock` to start the original Doom II campaign on MAP01. Press **L** to turn on the flashlight and look down toward the opening tiles. Press **R** to compare. The Entryway floor variants follow the painted joints on the original 64×64 tiles. The preview's **Entryway floor tiles** and **Detailed machinery panel** rooms are close-up checks for alignment and the stronger response on detailed materials. In MAP16, turn east from the start for the cracked `BRICK4` wall or west for the `WOOD9` planks.

Watch for texture swimming, repeating seams, detached highlights and a loss of frame rate. Use `stat fps` in the console for a live check. Record the GPU, resolution and owner judgement before proceeding to Stage B.

The console controls `gl_world_relief_depth` (default 4, range 0–16) and `gl_world_relief_orientation` (default 2.5, range 0–8) set the world-unit scales for virtual depth and slope independently. Set one to zero to isolate the other. `gl_world_relief_exaggeration` (default 1, range 0–2) scales the shared height signal. The launcher sets these three controls to 5, 5 and 1.25 for the playtest. The evaluation path uses the immediate Vulkan PBR shaders and the existing flashlight.

## Capture the matched batch

```powershell
py tools/doom2_showcase/capture_relief.py `
  --exe build/windows/RelWithDebInfo/vkdoom.exe --iwad C:\doom2.wad `
  --materials build/relief-addons/DoomII-NormalPBR.pk3 `
  --flashlight build/relief-addons/Local-Flashlight.pk3 --out build/relief-evidence
```

Use a new output directory. The batch runs the native renderer on the same camera and flashlight poses at 17°, 26° and 33° from the plane for each material. A featureless grey PBR wall with a constant neutral height exercises the same relief branch and must produce identical OFF and ON images. For a shorter run, repeat `--material` with your chosen names. Add `--depth 5 --orientation 5 --exaggeration 1.25` to capture with the launcher’s settings.

To check the alignment and detailed materials at a single angle, use `--incidence 26 --material FLOOR0_1 --material FLOOR3_3 --material MODWALL1 --material SW1SKULL --material CEIL5_2`. The last material checks the stock fallback without a height binding.

The output includes native screenshots, labelled comparison sheets, unscaled difference PNGs, RGB difference statistics and raw renderer observations. `manifest.json` records the inputs, source and runtime identity, fixed poses, timing samples and SHA-256 hashes. CPU measurements cover `RenderView`. The Vulkan timestamps cover individual named groups, which can overlap. These short instrumented samples are a frame-cost check alongside live play. Review the unamplified screenshots and the moving flashlight in game for visual acceptance.

The manifest maps each material and angle to a fixture map. The playable preview reproduces the 26° camera and flashlight pose from each comparison. Keep the evidence local to the licensed Doom II installation.

## Stock Doom II sprite relief

```powershell
py tools/doom2_showcase/build.py --doom2 C:\doom2.wad --relief --sprite-relief --out build/sprite-relief-addons
.\tools\doom2_showcase\launch.ps1 -Game DoomII -SpriteRelief `
  -Exe .\build\windows\RelWithDebInfo\vkdoom.exe -Doom2 C:\doom2.wad -Packages .\build\sprite-relief-addons
```

The sprite preview starts with the flashlight on. Press **R** or middle-click to compare sprite relief in place. **L** toggles the flashlight, **F1** opens the room selector, and the mouse wheel or **Page Up** and **Page Down** cycle through the rooms. Launch with `-Relief -SpriteRelief -ReliefStock` for the original campaign. In the campaign, **L** toggles the flashlight, **V** compares sprite relief, and **R** compares wall and floor relief.

The sprite manifest accounts for every patch in the stock Doom II WAD. Native-resolution height maps cover solid monsters, pickups, scenery, projectiles and first-person weapons. Each height map follows the original patch dimensions, offsets and mirror aliases. Stationary animated surfaces share a height field aligned to the patch origin. The game continues to use its original state loops, durations and sprite art. Solid fullbright surfaces such as Lost Soul skulls get a bounded structural response over their authored brightness. Torch stands use relief on their solid supports and retain the flame brightmaps. Transient emissive effects and translucent sprites keep their stock rendering. The flashlight must reach a sprite for relief to appear. The toggle defaults to off outside the launcher.

```powershell
py tools/doom2_showcase/capture_sprite_relief.py capture `
  --exe build/windows/RelWithDebInfo/vkdoom.exe --iwad C:\doom2.wad `
  --sprites build/sprite-relief-addons/DoomII-SpritePBR.pk3 `
  --flashlight build/sprite-relief-addons/Local-Flashlight.pk3 --out build/sprite-relief-evidence
```

Use a new output directory. The batch matches native captures by simulation tic and checks frame order, state durations, actor transforms, rotation and visible sprite coverage. Add `--case imp-front` for a shorter run or `--lamp-off` to verify that sprite relief adds no light with the flashlight off. Each comparison sheet shows representative frames and an amplified RGB difference. The manifest lists the individual original captures and renderer observations.

## DBP50 relief

```powershell
py tools/doom2_showcase/build.py --doom2 .\assets\wads\doom2.wad --dbp50 .\assets\wads\DBP50.wad `
  --relief --sprite-relief --out build/dbp50-relief-addons
.\tools\doom2_showcase\launch.ps1 -Game DBP50 -Relief -SpriteRelief `
  -Exe .\build\windows\RelWithDebInfo\vkdoom.exe -Doom2 .\assets\wads\doom2.wad `
  -DBP50 .\assets\wads\DBP50.wad -Packages .\build\dbp50-relief-addons
```

The launcher opens the DBP50 campaign. Press **L** for the flashlight, **R** to compare wall and floor relief, and **V** to compare sprite relief. The DBP50 pack uses the effective texture definitions, palette, and sprite patch offsets from the loaded WADs. It includes auxiliary materials for DBP50's custom walls and floors. The generated `material-build.json` and `DBP50-sprite-manifest.json` account for custom and inherited art, including surfaces with a neutral relief profile. The streetlamp uses its original six-tic animation phases and the mailbox uses its original eight rotations. DBP50's green Arch-vile fire keeps its emissive appearance.

Press **F1** for **PBR materials**. Use **Pick aimed surface** on a wall, floor, or ceiling, or use **Find by texture name** with a name such as `wall:DBLD10` or `flat:DNOX`. The editor previews roughness, metallic, normal strength, ambient occlusion, and relief depth. Depth scales the selected material's height map from **0×** to **2×** with world or sprite relief enabled. **Save material settings** writes the edits to `DBP50-Relief.ini.materials` beside the DBP50 configuration.
