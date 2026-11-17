# Shadow puppet feasibility

The prototype compares two ways for a Doom II Imp to block the player's flashlight. Both use the sprite submitted by the main view that frame. A change of pose, rotation, or mirror selects the corresponding opaque texels, including gaps between limbs. The renderer maps that outline through the sprite's final UVs and world-space corners. Shadows therefore follow the same animation, placement, scale, and floor clipping the player sees. The caster has no gameplay or collision role.

| Backend | Integration in the immediate Vulkan renderer | Main risks |
| --- | --- | --- |
| Depth | Rasterize the sprite's opaque regions into a spotlight depth attachment. Project each wall or floor fragment's world position into the same light view and compare depths. | Finite map resolution and contact bias affect narrow gaps and distant silhouettes. Each additional light would need its own projection. |
| Stencil | Extrude the sprite's exterior and interior edges away from the flashlight. Close both ends and count depth failures against the native opaque wall and flat depth. Resolve the result to the selected flashlight's visibility, including per-sample coverage with MSAA. | Receiver replay adds work. Near-plane intersections require correct caps and winding. Portals and fake floors complicate matching scene depth. |

`VkRenderBuffers` owns scene depth/stencil. The stencil pass must preserve scene depth and return the attachment in the layout expected by the immediate scene. Each backend owns its visibility image and uses Vulkan's existing command retirement and bindless descriptor mechanisms. A frame with no effective result uses the ordinary flashlight path. Depth only needs the spotlight projection. Stencil resolves at the camera viewport and can increase cost with screen resolution.

`hw_dynlightdata.cpp` marks only the selected packed spotlight, and the normal, specular, and PBR fragment shaders apply the resulting visibility to that light's direct attenuation before evaluating its contribution. Ambient, probes, and unrelated lights follow the same shader paths in every mode. Portal views and unsupported render paths use the ordinary flashlight. The first comparison uses ordinary opaque walls, floors, and steps with one flashlight and no interleaved portal or fake-floor receivers.

## Play the comparison room

Open **Play Doom II - Shadow Puppets.cmd**. The room starts in **Off**, with the flashlight on. Press **J** to cycle **Off**, **Stencil**, and **Depth** while moving. **F1** opens the mode and depth softness controls. **L** toggles the flashlight. Strafe past the stationary Imp, aim across the floor toward the steps, and track the other Imp as it turns. The blue fill on the rear right is a separate light. The overlay reports the requested mode and shows a fallback if the renderer cannot run it.

The comparison launcher selects true-colour immediate Vulkan rendering, requests 4× MSAA, and disables SSAO and the optional legacy sprite-floor shadows. In normal play an Imp that successfully casts a flashlight shadow also skips its duplicate legacy floor shadow for that view. Opaque walls and flats receive projected shadows. Masked materials, sprites, viewmodels, special vision, and portal views use their ordinary lighting. The prototype supports one circular flashlight beam. A flashlight split into several beams, multiplayer, and maps with 3D floors or linked portals fall back. Stencil needs depth clamp and a visibility attachment matching the scene's actual sample count.

The comparison covers up to four living Imps submitted in the main view, with line of sight from the flashlight. A sprite outside that draw list cannot cast. Depth uses a 1024 × 1024 image (4 MiB D32 or 2 MiB D16), a 0.30-unit contact bias, and a filter that compares each tap against the receiver plane. **Depth edge softness** defaults to 1 and ranges from a hard edge at 0 to a wider filter at 2. Stencil retains hard edges at 1× and resolves actual sample coverage at higher sample counts. Its visibility storage at N× MSAA adds an N-sample 8-bit attachment beside the resolved 8-bit image.

To reproduce the room with a Windows runtime built from this branch, generate current relief, sprite, and flashlight add-ons, then add the demonstration map.

```powershell
py tools/doom2_showcase/build.py --doom2 assets/wads/doom2.wad --relief --sprite-relief --out build/puppet-addons
py tools/doom2_showcase/shadow_puppets.py --out build/puppet-addons/DoomII-Shadow-Puppets.pk3
.\tools\doom2_showcase\launch.ps1 -Game DoomII -Relief -SpriteRelief -ShadowPuppets `
  -Exe .\build\windows\RelWithDebInfo\vkdoom.exe -Doom2 .\assets\wads\doom2.wad -Packages .\build\puppet-addons
```

The native capture script takes a packaged build with `runtime`, `addons`, and `doom2.wad` alongside its launcher. Use a new output directory for each run. Its silhouette checks hold the Imp in place, change its sprite, and trace reference rays from the flashlight through the original IWAD alpha onto the floor, stair risers and rear wall. A flashlight-off capture isolates the light available to block. Comparisons exclude the visible Imp and the filtered shadow edge.

```powershell
py tools/doom2_showcase/capture_shadow_puppets.py --pack build/issue-2-shadow-puppets-playtest `
  --out build/puppet-views --msaa 4
py tools/doom2_showcase/capture_shadow_puppets.py --pack build/issue-2-shadow-puppets-playtest `
  --out build/puppet-timing --msaa 4 --timing
```

Use `--msaa 0` for the single-sample comparison and `--depth-softness 0` to isolate the unfiltered Depth edge at the same pose.
