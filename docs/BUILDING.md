# Build and run Doom2OO3

This tree is an intentionally minimal, source-identical PR #195 renderer foundation. It keeps Vulkan crash, synchronization, resource-lifetime, PBR and performance fixes through that merge. The legacy qualification system is removed, **not** the production fixes.

## Windows 11 (primary)
Requires Visual Studio 2022 with Desktop development with C++, x64 compiler and Windows SDK, CMake 3.24+, and Git. Use Developer PowerShell from the repository root:

```powershell
cmake -S . -B build/windows -G "Visual Studio 17 2022" -A x64 -DPK3_QUIET_ZIPDIR=ON
cmake --build build/windows --config RelWithDebInfo --parallel 4
& .\build\windows\RelWithDebInfo\vkdoom.exe --version
& .\build\windows\RelWithDebInfo\vkdoom.exe -iwad "C:\doom2.wad"
```

Build output includes `vkdoom.exe`, `vktool.exe`, PK3 resources, DLLs and runtime assets. The `vkdoom` name, version stamp and `ShadeDoomVK` identity are deliberately retained. Run with Vulkan enabled and a real GPU for the owner's visual assessment. Do not mistake a successful compile or software renderer smoke for visual acceptance.

## Original material and flashlight add-ons
The unchanged `tools/doom2_showcase/` script creates local opt-in Doom II/DBP50 normal/metallic/roughness/AO packs, flashlight and optional gallery. It never alters original source sprite pixels or gameplay and does not redistribute proprietary WADs.

```powershell
py -m pip install numpy "Pillow>=10.1"
py tools/doom2_showcase/build.py --doom2 "C:\doom2.wad" --out ".\build\addons"
.\tools\doom2_showcase\launch.ps1 -Game DoomII -Exe ".\build\windows\RelWithDebInfo\vkdoom.exe" -Doom2 "C:\doom2.wad" -Packages ".\build\addons"
```

`--dbp50 "C:\path\to\DBP50.wad"` and `--gallery` are optional. Generate into a **new** output folder. The generator checks known WAD identities; use supported originals or explicitly extend input support instead of bypassing validation. With no `--doom2`, the builder can create the standalone flashlight using only Python's standard library.

## Linux (secondary)
Requires a C++17 compiler, CMake 3.24+, Git, Python 3 and normal SDL2/GTK/webp/VPX development dependencies:

```bash
sudo apt-get install build-essential git python3 libsdl2-dev libvpx-dev libgtk-3-dev libwebp-dev
python3 tools/fetch_build_deps.py --platform linux --output build/deps
cmake -S . -B build/linux -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_PREFIX_PATH="$PWD/build/deps/zmusic" -DPK3_QUIET_ZIPDIR=ON
cmake --build build/linux --parallel 4
LD_LIBRARY_PATH="$PWD/build/deps/zmusic/lib" ./build/linux/vkdoom -iwad /path/to/doom2.wad
```

Build system dependencies under `tools/lemon`, `tools/re2c`, `tools/zipdir` and `tools/updaterevision` are retained exactly from PR #195.

## Checks
A focused Windows Actions build compiles and invokes `vkdoom --version`, and creates the standalone flashlight archive. For graphical changes add relevant *short* negative tests (stale descriptors, invalid resource reuse, portal leakage, broken render fallback) and provide a runnable Windows result. There is no blanket full renderer publication campaign; do not remove safety checks that actually implicate changed code.

The Linux Vulkan workflow builds one runtime on a standard Ubuntu runner, then runs two independent Freedoom map smokes on the `ubuntu-latest-m` runners in the `8core` group. Each worker verifies the runtime archive and source SHA before launching native Vulkan through Mesa llvmpipe. The workflow checks rendered geometry, a nonblank screenshot and clean completion, and retains the engine log and screenshot per map. This is a short correctness check. Windows playtesting and GPU performance measurements are separate.

The Git history includes the old ShadeDoomVK investigation, but it is deliberately outside this project's active planning scope.
