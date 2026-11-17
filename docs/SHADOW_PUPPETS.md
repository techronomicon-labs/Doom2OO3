# Shadow puppet feasibility

The prototype compares two ways for a Doom II Imp to block the player's flashlight. For each animated Imp in the main view, Doom selects the current frame's directional artwork and mirror as seen from the flashlight. The silhouette stands upright at the actor's interpolated position, using the selected patch's offsets, scale and floor clipping. Rays through its opaque texels cast onto real map surfaces. The two views can see different sides of the same Imp when the flashlight is close or off to one side. Modded actors that explicitly require a rolled, isometric, tilted or offset camera-facing sprite use their authored presentation geometry.

| Backend | Integration in the immediate Vulkan renderer | Main risks |
| --- | --- | --- |
| Depth | Rasterize the sprite's opaque regions into a spotlight depth attachment. Project each wall or floor fragment's world position into the same light view and compare depths. | Finite map resolution and contact bias affect narrow gaps and distant silhouettes. Each additional light would need its own projection. |
| Stencil | Extrude the sprite's exterior and interior edges away from the flashlight. Close both ends and count depth failures against the native opaque wall and flat depth. Resolve the result to the selected flashlight's visibility, including per-sample coverage with MSAA. | Receiver replay adds work. Near-plane intersections require correct caps and winding. Portals and fake floors complicate matching scene depth. |

`VkRenderBuffers` owns scene depth/stencil. The stencil pass must preserve scene depth and return the attachment in the layout expected by the immediate scene. Each backend owns its visibility image and uses Vulkan's existing command retirement and bindless descriptor mechanisms. A frame with no effective result uses the ordinary flashlight path. Depth only needs the spotlight projection. Stencil resolves at the camera viewport and can increase cost with screen resolution.

`hw_dynlightdata.cpp` marks the spotlights belonging to the player's flashlight. The normal, specular, and PBR fragment shaders evaluate visibility once per receiving fragment and apply it to each marked spotlight's direct attenuation. Ambient, probes, and unrelated lights follow the same shader paths in every mode. Portal views and unsupported render paths use the ordinary flashlight. The first comparison uses ordinary opaque walls, floors, and steps with one flashlight and no interleaved portal or fake-floor receivers.

## Play the comparison room

Open **Play Doom II - Shadow Puppets.cmd**. A new profile starts in **Off**, with the flashlight on and mounted 12 units above eye height. Subsequent launches restore the saved shadow mode and mount. Press **J** to cycle **Off**, **Stencil**, and **Depth** while moving. **F1** opens the settings and **L** toggles the flashlight. Strafe past the stationary Imp and aim toward the steps to see the shadow cross from a tread onto its riser. The blue fill on the rear right is a separate light.

For a hard/soft comparison, choose **F1 → Preview soft Depth**. This selects Depth at softness **1.00** for the current session. Look at the outline beside the Imp’s foot, then follow it back across the stairs. Contact stays sharp in both modes. Farther behind the Imp, Depth gradually lets light around the silhouette while Stencil keeps a hard outline. At zero softness, both modes model a point light and their outlines should closely match. Use the **Shadow mode** selector and **Depth edge softness** slider to save a preference.

The comparison launcher selects true-colour immediate Vulkan rendering, requests 4× MSAA, and disables SSAO and the optional legacy sprite-floor shadows. In normal play an Imp that successfully casts a flashlight shadow also skips its duplicate legacy floor shadow for that view. Opaque walls and flats receive projected shadows. Masked materials, sprites, viewmodels, special vision, and portal views use their ordinary lighting. Adjusting horizontal and vertical spread produces one, three, or five spotlights at the flashlight mount. Both shadow modes cover the full beam, including the outer lobes. Multiplayer and maps with 3D floors or linked portals fall back. Stencil needs depth clamp and a visibility attachment matching the scene's actual sample count.

The comparison covers up to four living Imps submitted in the main view, with line of sight from the flashlight. The stock artwork supplies eight horizontal views. Directly above or below the sprite, its upright extent presents no area to the light. Depth uses a 1024 × 1024 image (4 MiB D32 or 2 MiB D16) and a 0.30-unit contact bias. **Depth edge softness** ranges from 0 to 2 and defaults to 1. Positive values simulate a flashlight with a finite emitting area. Blocker and receiver depth determine how wide its penumbra appears. Stencil resolves hard-edge coverage with MSAA.

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

```powershell
py tools/doom2_showcase/capture_shadow_puppets.py --pack build/issue-2-shadow-puppets-playtest `
  --out build/puppet-views --msaa 4
py tools/doom2_showcase/capture_shadow_puppets.py --pack build/issue-2-shadow-puppets-playtest `
  --out build/puppet-timing --msaa 4 --timing
```

Use `--msaa 0` for the single-sample comparison and `--depth-softness 0` to isolate the unfiltered Depth edge at the same pose.
