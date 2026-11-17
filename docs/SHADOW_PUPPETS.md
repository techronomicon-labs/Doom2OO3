# Shadow puppet feasibility

The prototype compares two visibility tests for a single player flashlight. Both start with the same closed Imp mesh, using the presentation position and yaw sampled for the billboard. The puppet includes shaped shoulders, hands, and feet. Its walk pose follows the Imp's travel and settles into a planted stance at rest. The game draws and animates the original billboard and uses the original collision box.

| Backend | Integration in the immediate Vulkan renderer | Main risks |
| --- | --- | --- |
| Depth | Render the proxy triangles into a sampleable spotlight depth attachment before `HWDrawInfo::RenderScene` shades the world. Project each receiver's geometric position into the same light view and compare depth with a bias. This pass needs neither a copy of scene depth nor a second world traversal. | Finite depth-map resolution, bias at contacts, light near-plane clipping, and a separate projection and image for every additional source. |
| Stencil | Replay the immediate opaque wall and flat draw lists with colour writes disabled. `VkRenderState` ends its pass and a separate Vulkan pass loads the receiver depth. One two-sided draw rasterizes the capped volumes using opposite depth-fail operations on each face. The resolve converts nonzero stencil into per-sample visibility, and MSAA averages that coverage. | Opposite facing and capping must stay correct at near-plane intersections. Receiver replay adds work. Portals and fake floors complicate matching the resolve to the receiver. |

`VkRenderBuffers` owns scene depth/stencil. The stencil pass must preserve scene depth and return the attachment in the layout expected by the immediate scene. Each backend owns its visibility image and uses Vulkan's existing command retirement and bindless descriptor mechanisms. A frame with no effective result uses the ordinary flashlight path. Depth only needs the spotlight projection. Stencil resolves at the camera viewport and can increase cost with screen resolution.

`hw_dynlightdata.cpp` marks only the selected packed spotlight, and the normal, specular, and PBR fragment shaders apply the resulting visibility to that light's direct attenuation before evaluating its contribution. Ambient, probes, and unrelated lights follow the same shader paths in every mode. Portal views and unsupported render paths use the ordinary flashlight. The first comparison uses ordinary opaque walls, floors, and steps with one flashlight and no interleaved portal or fake-floor receivers.

## Play the comparison room

Open **Play Doom II - Shadow Puppets.cmd**. The room starts in **Off**, with the flashlight on. Press **J** to cycle **Off**, **Stencil**, and **Depth** while moving. **F1** opens the mode and depth softness controls. **L** toggles the flashlight. Strafe past the stationary Imp, aim across the floor toward the steps, and track the other Imp as it turns. The blue fill on the rear right is a separate light. The overlay reports the requested mode and shows a fallback if the renderer cannot run it.

The comparison launcher selects true-colour immediate Vulkan rendering, requests 4× MSAA, and disables SSAO. Opaque walls and flats receive puppet shadows. Masked materials, sprites, viewmodels, special vision, and portal views use their ordinary lighting. The prototype supports one circular flashlight beam. A flashlight split into several beams, multiplayer, and maps with 3D floors or linked portals fall back. Stencil needs depth clamp and a visibility attachment matching the scene's actual sample count.

The puppet tests line of sight from the flashlight to the caster. The spotlight still uses the existing flashlight's world lighting and occlusion. Depth uses a 512 × 512 image, a 0.30-unit contact bias, and a small filter that compares each tap against the receiver plane. **Depth edge softness** defaults to 1 and ranges from a hard edge at 0 to a wider filter at 2. Stencil retains hard edges at 1× and resolves actual sample coverage at higher sample counts. Its visibility storage at N× MSAA adds an N-sample 8-bit attachment beside the resolved 8-bit image.

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
  --out build/puppet-views --msaa 4 --case spawn --case stationary --case moving --case contact --case no-flashlight
py tools/doom2_showcase/capture_shadow_puppets.py --pack build/issue-2-shadow-puppets-playtest `
  --out build/puppet-timing --msaa 4 --timing
```

Use `--msaa 0` for the single-sample comparison and `--depth-softness 0` to isolate the unfiltered Depth edge at the same pose.
