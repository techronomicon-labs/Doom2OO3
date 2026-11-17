# Shadow puppet feasibility

The prototype compares two visibility tests for a single player flashlight. Both start with the same closed Imp mesh, transformed by the actor position and yaw interpolated in `scene/hw_sprites.cpp`. The mesh is renderer data. The game still draws and animates the original billboard and uses the original collision box.

| Backend | Integration in the immediate Vulkan renderer | Main risks |
| --- | --- | --- |
| Depth | Render the proxy triangles into a sampleable spotlight depth attachment before `HWDrawInfo::RenderScene` shades the world. Project each receiver's geometric position into the same light view and compare depth with a bias. This pass needs neither a copy of scene depth nor a second world traversal. | Finite depth-map resolution, bias at contacts, light near-plane clipping, and a separate projection and image for every additional source. |
| Stencil | Replay the immediate opaque wall and flat draw lists with colour writes disabled. `VkRenderState` ends its pass and a separate Vulkan pass loads the receiver depth. It rasterizes closed, light-extruded volumes, using opposite depth-fail stencil operations on front and back faces. Resolve nonzero stencil into a visibility texture and clear the temporary stencil before the main scene resumes. | Opposite facing and capping must stay correct at near-plane intersections. Receiver replay adds work. MSAA, portal recursion, and fake floors complicate depth ownership and matching the resolve to the receiver. |

`VkRenderBuffers` owns scene depth/stencil. The stencil pass must preserve scene depth and return the attachment in the layout expected by the immediate scene. Each backend owns its visibility image and uses Vulkan's existing command retirement and bindless descriptor mechanisms. A frame with no effective result uses the ordinary flashlight path. Depth only needs the spotlight projection. Stencil resolves at the camera viewport and can increase cost with screen resolution.

`hw_dynlightdata.cpp` marks only the selected packed spotlight, and the normal, specular, and PBR fragment shaders apply the resulting visibility to that light's direct attenuation before evaluating its contribution. Ambient, probes, and unrelated lights follow the same shader paths in every mode. Portal views and unsupported render paths use the ordinary flashlight. The first comparison uses ordinary opaque walls, floors, and steps with one flashlight and no interleaved portal or fake-floor receivers.

## Play the comparison room

Open **Play Doom II - Shadow Puppets.cmd**. The room starts in **Off**, with the flashlight on. Use **F1** to select **Off**, **Stencil**, or **Depth** and **L** to turn the flashlight off and on. Strafe past the stationary Imp, aim across the floor toward the steps, and track the other Imp as it turns. The blue fill on the rear right is a separate light. The overlay reports the requested mode and shows a fallback if the renderer cannot run it.

The comparison launcher selects true-colour immediate Vulkan rendering with MSAA and SSAO off. Opaque walls and flats receive puppet shadows. Masked materials, sprites, viewmodels, special vision, and portal views use their ordinary lighting. The prototype supports one circular flashlight beam. A flashlight split into several beams, multiplayer, and maps with 3D floors or linked portals fall back. Stencil also needs a single-sample depth/stencil attachment with depth clamp support.

The puppet tests line of sight from the flashlight to the caster. The spotlight still uses the existing flashlight's world lighting and occlusion. Depth uses a 512 × 512 image with a fixed 0.65-unit receiver bias. Stencil stores an 8-bit visibility image at scene resolution and replays the opaque receivers into scene depth.

To reproduce the room with a Windows runtime built from this branch, generate current relief, sprite, and flashlight add-ons, then add the demonstration map.

```powershell
py tools/doom2_showcase/build.py --doom2 assets/wads/doom2.wad --relief --sprite-relief --out build/puppet-addons
py tools/doom2_showcase/shadow_puppets.py --out build/puppet-addons/DoomII-Shadow-Puppets.pk3
.\tools\doom2_showcase\launch.ps1 -Game DoomII -Relief -SpriteRelief -ShadowPuppets `
  -Exe .\build\windows\RelWithDebInfo\vkdoom.exe -Doom2 .\assets\wads\doom2.wad -Packages .\build\puppet-addons
```

The native capture script takes a packaged build with `runtime`, `addons`, and `doom2.wad` alongside its launcher. Use a new output directory for each run. It records matched poses, render state, native screenshots, differences, and source and output hashes.

```powershell
py tools/doom2_showcase/capture_shadow_puppets.py --pack build/issue-2-shadow-puppets-playtest `
  --out build/puppet-views --case spawn --case stationary --case moving --case contact --case no-flashlight
py tools/doom2_showcase/capture_shadow_puppets.py --pack build/issue-2-shadow-puppets-playtest `
  --out build/puppet-timing --timing
```
