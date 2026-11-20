# Emitter lighting evaluation

The Doom II emitter launcher starts in Entryway with fixture lighting enabled. Press **B** to compare the original sector lighting from the same spot. **F1** opens the emitter settings and comparison rooms. **L** toggles the flashlight, **J** cycles its sprite shadows through Off, Stencil and Depth, and **O** opens beam and map-shadow settings. **R** compares world relief and **V** compares sprite relief.

**Legacy ambient fill** controls room brightness from the original sector lighting, lightmaps, diffuse probe lighting, and map sunlight. **PBR ambient reflections** controls how strongly PBR materials reflect ambient light, including reflections from light probes where present. New campaign profiles start at **0.04 legacy fill** and **0.08 ambient reflections**. Both sliders range from 0 to 1. For an existing profile, choose **F1 → Dark campaign lighting** to apply these values and set emitter intensity to 1. Direct highlights from the flashlight and authored emitters respond to their own light settings.

For an emitter-only comparison, enable emitter lighting with **B**, set both ambient sliders to zero in **F1**, and keep **Emitter intensity** at 1. Press **B** again to compare the same view with legacy lighting. Use **L** to include or remove the flashlight in either view.

**Emitter intensity** controls authored surface fixtures and the directional source in the demonstration courtyard. Setting it and both ambient sliders to zero leaves direct dynamic lights and self-emitting materials visible. Flashlight power, spread, and range have independent controls.

The flashlight starts 16 map units forward and 12 below eye level, with a 4Â° upward aim. Open **Position and aim** in **Flashlight settings** to change or reset the mount.

Open **Options → Projectile lighting** in Doom II or DBP50 to adjust light output from projectiles in flight and on impact. Plasma, rockets, and the BFG each have separate sliders. Other projectiles and bullet impacts have their own controls. **100%** is the authored intensity, **0%** removes the emitted light, and **1200%** is the maximum. The settings save to the active launcher profile.

**Map geometry shadows** in that menu defaults to on. Fire a rocket at the side of an Entryway pillar and watch the floor behind it as you compare the two settings. Opaque walls, floors and ceilings block each projectile or impact light independently. The campaign launchers use this in the single-player Vulkan world view, including on GPUs without hardware ray tracing. Transformed portal views use their existing lighting. For the flashlight, use **O → Map geometry shadows**. Aim across the same pillar or through a barred opening and toggle the option to compare the beam on the floor beyond. [Flashlight shadow controls](SHADOW_PUPPETS.md)

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

The stock Doom II campaign and three comparison rooms support emitter lighting. Each campaign layout checks the map checksum before placing emitters. Stock levels without a visible light source still respond to the ambient controls and flashlight. Unrecognized maps use the legacy renderer unless they supply emitters. Emitter lighting uses the immediate Vulkan renderer in true color. Level mesh, ubershaders, dynamic lightmapping, ray tracing, palette rendering, powerup vision, and offscreen views use their established paths.

## Lighting and coverage

Opaque walls and floors and ordinary per-pixel-lit actor sprites receive point and directional emitters. Retained ambient fill also picks up subtle slope contrast on PBR walls and floors with relief. At zero fill that contribution is zero. Brightmaps and glow materials keep a separate self-emission term. Direct dynamic lights from the flashlight, projectiles, impact flashes, and decorations work in both modes. Sky pixels, additive and translucent effects, custom shaders, fullbright sprites, and viewmodels use their existing shading paths.

The campaign compiler places point lights at exposed lamp texels, accounting for offsets, wall pegging, clipped sidedefs and flat tiling. Lamps in flickering, glowing and strobing sectors follow the original sector timing on their faces and in the light they cast. The stock sky contributes through the legacy fill slider. At zero fill, an empty courtyard can be pitch black beneath a visible sky.

A light can reach opaque geometry across a sector boundary from the real fixture. The Vulkan renderer tests that path against the map, including raised floors, closed doors and ceilings. It selects up to 48 fixture shadow rows per view and 12 fixtures per receiver, including up to four from other sectors. Actor sprites receive authored sources in their own sector. The separate **Courtyard directional light** demonstration remains available in F1.

Floor lamps, torches, candles and burning barrels cast short pools from their sprite frames. Idle explosive barrels, keys, armor and ordinary health bonuses have zero cast radius in emitter mode. Luminous powerups have a small halo. Barrel explosions and weapon effects use their existing settings under **Projectile lighting**.

### Stock campaign lighting

| Map | Lighting to look for with the flashlight off |
| --- | --- |
| 01 · Entryway | Seventeen yellow corridor strips, the computer-bay fluorescents and the red exit sign. The plastic ceiling circles stay dark. |
| 02 · Underhalls | Strobing fluorescents and small green CRT faces. The sewer entrance and open yard rely on ambient fill. |
| 03 · The Gantlet | Amber footlights and colored torches. Cropped bronze panels expose no lamp. |
| 04 · The Focus | White and blue door jambs and short tech lamps. |
| 05 · The Waste Tunnels | Torches and an exit sign carry the tunnels. |
| 06 · The Crusher | Tech lamps, ceiling grilles, amber footlights and lava along its banks. |
| 07 · Dead Simple | The exit signs are the arena's only fixed surface lights. |
| 08 · Tricks and Traps | Flickering red panels, CRT banks, candles and fire walls. |
| 09 · The Pit | Red panels, fluorescents, blue lenses and strobing consoles. |
| 10 · Refueling Base | Yellow and blue strips, with a short throw on the repeated amber trim. |
| 11 · Circle of Death | Colored torches, burning barrels and cycling red and amber ceiling lamps. |
| 12 · The Factory | White grille banks and amber lenses light individual industrial bays. |
| 13 · Downtown | Building lamps and lava banks leave the street between them dark. |
| 14 · The Inmost Dens | Wall sconces and colored torches in otherwise dark stonework. |
| 15 · Industrial Zone | Candles and torches carry the rooms. Molten seams and lava stay close to the ground. |
| 16 · Suburbs | Magma and blue-fire panels, warm ceiling lenses and a few torches. |
| 17 · Tenements | Torch rows and short-range electric jambs. |
| 18 · The Courtyard | Sparse grilles and faint cooling rock. Open sky adds no point light. |
| 19 · The Citadel | Red lens clusters and short torches punctuate the masonry. |
| 20 · Gotcha! | Torches, red lenses and lava banks in a dark open arena. |
| 21 · Nirvana | Amber trim and stone sconces. Ordinary pickups leave the floor dark. |
| 22 · The Catacombs | Red and blue fire, stone sconces and a fluorescent bank. |
| 23 · Barrels o’ Fun | Burning barrels illuminate nearby walls. The rows of idle barrels only light the room when they explode. |
| 24 · The Chasm | Amber edge lights, recessed blue lenses and panel lamps pick out sections of the walkways. |
| 25 · Bloodfalls | Candles and torches dominate, with a faint glow from exposed fissures. |
| 26 · The Abandoned Mines | White strips, colored lenses, torches and lava. |
| 27 · Monster Condo | Brick sconces, candelabras and ceiling lamps around the darker halls. |
| 28 · The Spirit World | Flame walls and molten cracks each cast short-range light. |
| 29 · The Living End | Torch lines and lava edges leave space between platforms dark. |
| 30 · Icon of Sin | Cooling rock shows its own embers. The arena has no fixed surface emitters. |
| 31 · Wolfenstein | The hidden fire panels, torches and burning barrels provide local light. |
| 32 · Grosse | Fluorescent panels, amber and red lenses, and blue and green torches. |

## Reproduce the native comparisons

```powershell
py tools/doom2_showcase/capture_stageb_lighting.py `
  --exe build/windows/RelWithDebInfo/vkdoom.exe --iwad C:\doom2.wad `
  --materials build/emitter-addons/DoomII-NormalPBR.pk3 `
  --flashlight build/emitter-addons/Local-Flashlight.pk3 --out build/emitter-evidence
```

Use a new output directory. The batch includes interior point lights, a directional courtyard, the sealed-room control, and stock Entryway. The sealed room checks for light crossing the wall, legacy ambient at zero fill, and the response to the independent flashlight.

Add `--case MAP01-corridor --case MAP02-lamp --case MAP02-yard` to compare Entryway’s yellow wall strips, Underhalls’ fluorescent fixtures, and its courtyard. The lamp comparison captures both phases of the original strobe at zero ambient. Muting the cast light isolates the lamp faces. The courtyard comparison checks that enabling the fixtures leaves its unlit foreground dark.

Repeat the command with `--timing`, a fresh output directory, and the cases you want to measure. Timing defaults to 120 uncapped frames at 1280 Ã— 960 per mode, with VSync off. `--size WIDTH HEIGHT` and `--frames N` change the sample. The report records median and 95th-percentile frame spacing, CPU `RenderView` time, and individual Vulkan timestamp groups. The GPU groups measure specific passes and can overlap.
