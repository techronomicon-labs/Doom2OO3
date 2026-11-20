# Flashlight shadows in Doom II and DBP50

Press **L** to turn on the flashlight. **O → Map geometry shadows** switches flashlight occlusion by walls, floors and ceilings on or off. Aim past a raised step or under a moving door to see its shadow travel across the floor or wall beyond it. A fresh profile enables map shadows. To compare them while moving, bind **Toggle flashlight map shadows** under **Customize Controls → Local Flashlight**.

**O → Map shadow source radius** sets the radius of the flashlight’s emitting area from 0 to 24 map units. At the default of 12, a pillar can hide part of the source. Its shadow stays tight at contact and develops a wider, partially lit edge on surfaces farther behind it. Move closer with the lamp centred to see this on either side of the pillar. Radius 0 gives a hard point-source shadow.

**Horizontal map shadow spread** and **Vertical map shadow spread** each scale the source radius from 0% to 400%. At the default radius of 12 units, horizontal 200% and vertical 50% give the flashlight a source 24 units in radius side to side and 6 units up and down. Set both to 0% for a hard edge. Each profile saves both percentages. An existing profile starts with its previous spread on both axes.

**Map shadow edge** changes how the edge looks. **Smooth** is the default and grades the flashlight’s contribution across the edge. **Single shade** gives the projected footprint one shade, including the part that spreads beyond a nearby pillar. **Stepped** keeps the previous bands.

**Shadow darkness (%)** adjusts how much flashlight light a map or sprite shadow removes. At 0% the beam shines through, at 50% a fully blocked area keeps half its flashlight light, and at 100% a solid blocker removes all of it. Values up to 200% deepen partially shaded edges. Ambient light and other light sources keep their own intensity.

**J** cycles **Off → Stencil → Depth** for sprite shadows. **O** also lets you set **Sprite depth edge softness**. A fresh campaign profile starts in Depth. Each game's profile remembers both shadow settings and the softness.

Both campaign launchers enable `gl_precache`. At map entry Vulkan prepares the map's material pipelines, common sprite and projectile draws, and both supported flashlight shadow paths before drawing the first scene. The first load with a cold shader cache can take longer. Later levels reuse pipelines already built for the same render settings. Set `gl_precache false` in the console before changing levels to use on-demand loading.

With **Map geometry shadows** on, the renderer traces the segment from the mounted flashlight to the receiving surface through the level mesh. Walls, steps, moving doors and lifts can block the beam even when the obstruction is offscreen or close to the lamp. The bars of a masked grate cast shadows through their opaque texels and leave the gaps lit. Walls, floors, ceilings, lit actor sprites and lit particles receive these shadows. An object in shadow loses the flashlight’s direct light and keeps its ambient and fixture lighting. The console setting is `gl_flashlight_map_shadows`, and it works with sprite shadows set to Off, Stencil or Depth.

With per-pixel sprite lighting, a crossing shadow can cover part of a monster. CPU sprite lighting keeps the beam brightness calculated at the actor’s centre and masks it per pixel. Vertex sprite lighting tests visibility at the actor’s centre, so the part of a standing sprite drawn below the floor cannot dim the rest. Vertex-lit particles use their own corners.

Enemies and solid scenery cast from their current sprite frame. Doom selects the directional artwork and mirror as seen from the flashlight, then projects its opaque texels onto map geometry. The silhouette follows animation, scale, patch offsets and floor clipping. DBP50 uses its own replacements and effective actor flags. An exploding barrel stops blocking when it loses solidity. Flying enemies and ceiling-hung decorations cast from their actual heights. Pickups, projectiles and non-solid scenery let the beam through.

| Backend | Integration in the immediate Vulkan renderer | Main risks |
| --- | --- | --- |
| Depth | Rasterize the sprite's opaque regions into a spotlight depth attachment. Project each wall or floor fragment's world position into the same light view and compare depths. | Finite map resolution and contact bias affect narrow gaps and distant silhouettes. Each additional light would need its own projection. |
| Stencil | Extrude the sprite's exterior and interior edges away from the flashlight. Close both ends and count depth failures against the native opaque wall and flat depth. Resolve the result to the selected flashlight's visibility, including per-sample coverage with MSAA. | Receiver replay adds work. Near-plane intersections require correct caps and winding. Portals and fake floors complicate matching scene depth. |

`VkRenderBuffers` owns scene depth/stencil. The stencil pass must preserve scene depth and return the attachment in the layout expected by the immediate scene. Each backend owns its visibility image and uses Vulkan's existing command retirement and bindless descriptor mechanisms. A frame with no effective result uses the ordinary flashlight path. Depth only needs the spotlight projection. Stencil resolves at the camera viewport and can increase cost with screen resolution.

`hw_dynlightdata.cpp` marks the spotlights belonging to the player's flashlight. The normal, specular and PBR shaders share the map visibility result between beam lobes at the same position. On world surfaces that also receive sprite shadows, the shader combines both visibility results.

## Play the comparison room

Open **Play Doom II - Shadow Puppets.cmd**. A new profile starts in **Off**, with the flashlight on and mounted 12 units above eye height. Subsequent launches restore the saved shadow mode and mount. Press **J** to cycle **Off**, **Stencil**, and **Depth** while moving. **F1** opens the settings and **L** toggles the flashlight. Strafe past the stationary Imp and aim toward the steps to see the shadow cross from a tread onto its riser. The blue fill on the rear right is a separate light.

For a hard/soft comparison, choose **F1 → Preview soft Depth**. This selects Depth at softness **1.00** for the current session. Look at the outline beside the Imp’s foot, then follow it back across the stairs. Contact stays sharp in both modes. Farther behind the Imp, Depth gradually lets light around the silhouette while Stencil keeps a hard outline. At zero softness, both modes model a point light and their outlines should closely match. Use **Sprite shadows (J)** and **Sprite depth edge softness** to save a preference.

The flashlight mount tilts with mouselook. **F1 → Flashlight settings → Position and aim** adjusts it relative to your view. With both aim offsets at zero the beam points parallel to the crosshair. An offset mount still produces parallax on nearby surfaces. When a wall, floor or ceiling comes between your eye and the mount, the lamp stops just before that surface and returns to its saved offset as you move away. Positive vertical aim angles tilt the beam above the crosshair.

The comparison launcher selects true-colour immediate Vulkan rendering, requests 4× MSAA, and disables SSAO and the optional legacy sprite-floor shadows. In normal play a sprite that casts a flashlight shadow skips its duplicate legacy floor shadow for that view. Its silhouette can fall across opaque walls and flats, including the outer lobes of an elliptical spotlight. As the lamp approaches a sprite, the same silhouette covers more of the wall behind it. For example, a wall 96 units behind the sprite receives a shadow three times the sprite's width with the lamp 48 units in front, and seven times its width at 16 units. This ratio applies to a wall parallel to the sprite. Stencil needs depth clamp and a visibility attachment matching the scene's actual sample count.

Map geometry shadows work in the single-player main view on the immediate Vulkan renderer, including with SSAO enabled. The trace stays within the lamp’s level-mesh group. Transformed portal views, special vision and weapon sprites use their usual lighting. Sprite silhouette rendering additionally requires the normal colour pass and falls back on maps with line portals, linked sector portals or 3D floors.

The renderer also checks actors linked to the sectors reached by the light. A close sprite can keep casting onto the wall or floor after it leaves the camera view. Directly above or below an upright sprite, its edge presents no area to the light. Depth uses a 1024 × 1024 image (4 MiB D32 or 2 MiB D16) and a 0.30-unit contact bias. **Depth edge softness** ranges from 0 to 2 and defaults to 1. Positive values simulate a flashlight with a finite emitting area. Depth widens its shadow lookup as the lamp approaches the caster so the penumbra expands with distance behind it. The depth camera also includes the close silhouette and the rays around the rim of the aperture. Stencil resolves hard edges with MSAA.

To reproduce the room with a Windows runtime built from this branch, generate current relief, sprite, and flashlight add-ons, then add the demonstration map.

```powershell
py tools/doom2_showcase/build.py --doom2 assets/wads/doom2.wad --relief --sprite-relief --out build/puppet-addons
py tools/doom2_showcase/shadow_puppets.py --out build/puppet-addons/DoomII-Shadow-Puppets.pk3
.\tools\doom2_showcase\launch.ps1 -Game DoomII -Relief -SpriteRelief -ShadowPuppets `
  -Exe .\build\windows\RelWithDebInfo\vkdoom.exe -Doom2 .\assets\wads\doom2.wad -Packages .\build\puppet-addons
```

The native capture script takes a packaged build with `runtime`, `addons`, and `doom2.wad` alongside its launcher. Use a new output directory for each run. Its silhouette checks trace reference rays through the original IWAD artwork. The `landing-raised` case looks down from an angle at a floor, sloped tread, riser and rear wall, with the flashlight at Z +12. It checks samples where the camera and lamp select different silhouettes and checks continuity across the stair edge. A flashlight-off capture isolates the light available to block.

The `spawn-three` case checks the two Imps from the starting position with horizontal spread 60.725°, vertical spread 63.35°, mount Z +16, and pitch −15.75°. The `outer-lobe` case uses a five-spot beam aimed off-centre. It checks that opaque sprite texels block even the outermost spotlight, holes let it through, and the separate blue room light still reaches the receiver.

The `penumbra` case aims the flashlight down to light the feet and the stairs in the same frame. It compares hard Depth and Stencil against the original Imp artwork, then checks soft Depth against rays from across the flashlight aperture.

To measure shadow growth, run `py tools/doom2_showcase/capture_shadow_magnification.py --pack build/flashlight-map-shadows-playtest/DoomII --out build/shadow-growth`. It keeps the camera, sprite and wall fixed while it moves the flashlight mount. It also checks a caster crossing the camera and one within a unit of the lamp.

To check map shadow edges in Entryway, run `py tools/doom2_showcase/capture_entryway_flashlight.py --pack build/flashlight-map-shadows-playtest/DoomII --out build/entryway-pillar`. It compares floor and wall receivers on both sides of the bronze pillar at two distances, using lamp-off, unshadowed and point-source captures as controls.

To check shader preloading, run `py tools/doom2_showcase/check_map_shader_preload.py --pack build/flashlight-map-shadows-playtest/DoomII --output build/map-shader-check`. The test starts with empty caches and records any shader or pipeline builds during a short MAP01 encounter. Use the DBP50 kit path to test The Passage.

```powershell
py tools/doom2_showcase/capture_shadow_puppets.py --pack build/issue-2-shadow-puppets-playtest `
  --out build/puppet-views --msaa 4
py tools/doom2_showcase/capture_shadow_puppets.py --pack build/issue-2-shadow-puppets-playtest `
  --out build/puppet-timing --msaa 4 --timing
```

Use `--msaa 0` for the single-sample comparison and `--depth-softness 0` to isolate the unfiltered Depth edge at the same pose.

To check the campaign builds, pass their playtest directories to the native capture tool. It compares Off, Stencil and Depth on both original MAP01s and in controlled scenes containing enemies, bosses, solid decorations and pickups. Add `--case overlap` for the 256-caster stencil regression.

```powershell
py tools/doom2_showcase/capture_campaign_shadows.py --doom2 build/issue-5-campaign-playtest `
  --dbp50 build/issue-5-dbp50-complete-playtest --out build/campaign-shadow-check
```

To check map occlusion, use the native capture tool with a built Windows runtime. It compares rendered pixels against reference rays through a moving door, an offscreen pillar, a sill next to the lamp and a masked grate. A solid decoration straddles the sill’s shadow so both sides are visible on one sprite. Flashlight-off captures measure the independent room light.

```powershell
py tools/doom2_showcase/capture_flashlight_map_shadows.py --exe build/windows/RelWithDebInfo/vkdoom.exe `
  --iwad assets/wads/doom2.wad --out build/map-shadow-check
```
