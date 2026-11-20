"""Check bilateral flashlight penumbrae on actual MAP01 floor and wall receivers in Vulkan."""

import argparse
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile

import numpy as np
from PIL import Image

from capture_projectile_map_shadows import SIZE
from capture_shadow_silhouette import camera_rays
from capture_relief import require


# MAP01's BRONZE2 pillar occupies x=[-256,-192], y=[960,1024]. Looking north
# along either side puts a centered point lamp's cast shadow behind the column.
PILLAR_SIDES = {"column-left": (-192, 1), "column-right": (-256, -1)}
DISTANCES = {"near": 32, "far": 96}
DEFAULT_RADIUS = 12


def capture(pack, exe, folder, pose, beam, shadows, radius=None):
    folder.mkdir(parents=True)
    x, y, yaw, pitch = pose
    fixture = folder / "pose.pk3"
    with ZipFile(fixture, "w") as archive:
        archive.writestr("MAPINFO", 'GameInfo { AddEventHandlers = "EntrywayLampPose" }\n')
        archive.writestr("ZSCRIPT", f'''version "4.10"
class EntrywayLampPose : EventHandler
{{
    override void WorldTick()
    {{
        let pawn = players[0].mo;
        if (level.time == 3)
        {{
            let sec = level.PointInSector(({x}, {y}));
            pawn.SetOrigin(({x}, {y}, sec.floorplane.ZatPoint(({x}, {y}))), false);
            pawn.A_SetAngle({yaw});
            pawn.A_SetPitch({pitch});
            let handler = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
            handler.Enabled[0] = {str(beam).lower()};
        }}
        if (level.time == 12)
        {{
            let it = ThinkerIterator.Create("SDVKLocalFlashlightBeam", Thinker.STAT_DLIGHT);
            let lamp = Actor(it.Next());
            if (lamp) Console.Printf("ENTRYWAY_MOUNT %.6f %.6f %.6f", lamp.Pos.X, lamp.Pos.Y, lamp.Pos.Z);
            level.SetFrozen(true);
        }}
    }}
}}
''')
    cfg = folder / "capture.ini"
    cfg.write_text("[GlobalSettings]\nvk_rayquery=false\nvid_fullscreen=false\n")
    files = [pack / "addons" / name for name in ("DoomII-NormalPBR.pk3", "DoomII-SpritePBR.pk3",
                                                 "Local-Flashlight.pk3", "DoomII-Emitter-Lighting.pk3")]
    prefix = folder / "frame"
    cache = folder / "cache"
    cache.mkdir()
    width, height = map(str, SIZE)
    args = [exe, "-iwad", pack / "doom2.wad", "-file", *files, fixture, "-noautoload", "-noautoexec",
            "-stdout", "-nostartup", "-nosound", "-nojoy", "-nomonsters", "-rngseed", "2002",
            "-window", "-width", width, "-height", height, "-config", cfg, "-savedir", folder,
            "-sdvkobserve", prefix, "-sdvkobservecache", cache, "-sdvkobservewarmup", "30",
            "-sdvkobserveframes", "1", "-sdvkobservequit",
            "+vid_setsize", width, height, "+vid_rendermode", "4", "+gl_raytrace", "false",
            "+gl_levelmesh", "false", "+lm_dynlights", "false", "+gl_lights", "true",
            "+gl_light_shadows", "0", "+gl_ubershaders", "false", "+gl_ssao", "0", "+gl_precache", "false",
            "+cl_capfps", "true", "+vid_activeinbackground", "true", "+i_pauseinbackground", "false",
            "+use_mouse", "false", "+vid_vsync", "false", "+gl_bloom", "false", "+screenblocks", "12",
            "+r_drawplayersprites", "false", "+crosshair", "0", "+con_notifylines", "0", "+gl_multisample", "4",
            "+fov", "90", "+gl_shadow_puppets", "0", "+gl_emitter_lighting", "true", "+gl_emitter_ambient", "0",
            "+gl_emitter_ambient_specular", ".5", "+gl_emitter_intensity", "1.225", "+gl_world_relief", "true",
            "+gl_sprite_lighting_relief", "true", "+sdvk_fl_offset_x", ".9", "+sdvk_fl_offset_z", "11.7",
            "+sdvk_fl_aim_pitch", "-7.875", "+sdvk_fl_range", "768", "+sdvk_fl_horizontal", "50.225",
            "+sdvk_fl_vertical", "45.325", "+gl_flashlight_map_shadows", str(shadows).lower(), "+map", "MAP01"]
    # Exercise a fresh player's installed lateral offset and aperture with the reported beam settings.
    if radius is not None:
        args.extend(["+gl_flashlight_map_shadow_radius", str(radius)])
    log = folder / "engine.log"
    with log.open("wb") as stream:
        subprocess.run(list(map(str, args)), cwd=exe.parent, stdout=stream, stderr=subprocess.STDOUT,
                       timeout=120, check=True)
    messages = log.read_text(errors="replace")
    require("Unknown command" not in messages, f"Unsupported setting in {log}")
    source = re.search(r"ENTRYWAY_MOUNT ([-.\d]+) ([-.\d]+) ([-.\d]+)", messages)
    report = json.loads(prefix.with_suffix(".renderer.json").read_text())
    frame, = [row["data"] for row in report["records"] if row["kind"] == "frame"]
    require(report["build"]["backend"] == "vulkan" and frame["map"] == "MAP01" and
            frame["camera"]["position"][:2] == [x, y] and frame["stage_b"]["requested"] and
            bool(frame["relief_flashlight_lights"]) == beam and bool(source) == beam, f"Wrong capture in {folder}")
    with Image.open(prefix.with_suffix(".png")) as image:
        return np.asarray(image.convert("RGB"), dtype=np.int16), frame["camera"], (
            tuple(map(float, source.groups())) if source else None)


def measure(pack, exe, root, edge_x, outward, distance):
    pose = (edge_x, 960 - distance, 90, 14)
    fill, fill_camera, _ = capture(pack, exe, root / "ambient", pose, False, True)
    clear, camera, lamp = capture(pack, exe, root / "unshadowed", pose, True, False)
    hard, hard_camera, hard_lamp = capture(pack, exe, root / "point", pose, True, True, 0)
    soft, soft_camera, soft_lamp = capture(pack, exe, root / "aperture", pose, True, True)
    cameras = (fill_camera, hard_camera, soft_camera)
    require(all(np.allclose(view[key], camera[key], rtol=0, atol=1e-6) for view in cameras
                for key in ("position", "angles", "hardware_angles", "fov")) and lamp == hard_lamp == soft_lamp,
            "Lamp or camera moved between exposures")
    require(abs(lamp[0] - edge_x) < .02, f"Fresh profile did not center the lamp: {lamp}")

    eye = camera["position"]
    dx, dy, dz = camera_rays(camera, SIZE)
    floor_t = (8 - eye[2]) / np.minimum(dz, -1e-8)
    floor_y = eye[1] + floor_t * dy
    wall_t = (1280 - eye[1]) / dy
    wall_z = eye[2] + wall_t * dz
    lit = np.max(clear - fill, axis=2)
    drop = np.max(clear - soft, axis=2)
    remaining = np.max(soft - fill, axis=2)
    dimmed = (drop >= 3) & (remaining >= .25 * lit)
    exact = np.max(abs(hard - clear), axis=2) <= 3
    result = {}
    # Exact receiver planes: the floor strip behind the column in sector 0,
    # and the vertical back wall above the stairs on linedefs 16 through 20.
    for kind, t, y, region in (
        ("floor", floor_t, floor_y, (dz < 0) & (floor_y > 1040) & (floor_y < 1070)),
        ("wall", wall_t, 1280, (wall_z > 68) & (wall_z < 108)),
    ):
        x = eye[0] + t * dx
        outside = outward * (x - edge_x)
        region &= (outside > 1) & (lit >= 24)
        region &= (x > -320) & (x < (-128 if kind == "wall" else -148))
        # Similar triangles: sidestep at the source needed to just clip the
        # pillar's leading corner on a ray ending at this receiver.
        aperture_x = outside * (960 - lamp[1]) / (y - 960)
        partial = region & (aperture_x > 1) & (aperture_x < 6)
        require(np.count_nonzero(partial) >= 50, f"{root.name} {kind}: insufficient lit receivers")
        require(exact[partial].mean() >= .98, f"{root.name} {kind}: point source unexpectedly blocked")
        # These clear point rays are blocked for one side of a finite aperture.
        # Partial receivers must retain light in addition to the ambient exposure.
        require(dimmed[partial].mean() >= .95, f"{root.name} {kind}: missing partial shadows")
        # For these vertical edges the fraction of a uniform disk hidden by a
        # half-plane is the area of a circular segment. The renderer may sample
        # the disk sparsely; the inner and outer bands must still be ordered.
        if kind == "floor":
            u = np.clip(aperture_x / DEFAULT_RADIUS, 0, 1)
            fraction = (np.arccos(u) - u * np.sqrt(1 - u * u)) / np.pi
            inner = region & (fraction > .37)
            outer = region & (fraction > .075) & (fraction < .15)
            attenuation = drop / np.maximum(lit, 1)
            require(inner.sum() >= 12 and outer.sum() >= 12
                    and np.median(attenuation[inner]) > np.median(attenuation[outer]) + .04,
                    f"{root.name}: the inner and outer penumbra bands lack a light gradient")
        clear_rays = region & (aperture_x > DEFAULT_RADIUS + 2)
        if clear_rays.any():
            require((drop[clear_rays] <= 3).mean() > .98,
                    f"{root.name}: shadow leaked past the projected aperture on the {kind}")
        # Express the observed outer extent at a fixed distance behind the
        # column, so perspective and pixel size cannot manufacture a near/far gain.
        dim = region & dimmed
        normalized_width = np.broadcast_to(outside * 90 / (y - 960), region.shape)
        result[kind] = float(np.percentile(normalized_width[dim], 95))
        print(root.name, kind, f"{partial.sum()} partial receivers, {result[kind]:.2f} map-unit spread",
              flush=True)
    # The illuminated south face must never cast a shadow onto itself.
    front_t = (960 - eye[1]) / dy
    x, z = eye[0] + front_t * dx, eye[2] + front_t * dz
    front = (x > -254) & (x < -194) & (z > 12) & (z < 105) & (lit >= 24)
    require(front.sum() > 500 and (np.max(abs(clear - soft), axis=2)[front] <= 2).mean() > .99,
            f"{root.name}: incorrect light on the pillar face")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="New capture directory")
    args = parser.parse_args()
    pack, out = args.pack.resolve(), args.out.resolve()
    exe = (args.exe or pack / "runtime/vkdoom.exe").resolve()
    for side, (edge_x, outward) in PILLAR_SIDES.items():
        widths = {label: measure(pack, exe, out / f"{side}-{label}", edge_x, outward, distance)
                  for label, distance in DISTANCES.items()}
        require(widths["near"]["floor"] > 2 * widths["far"]["floor"],
                f"{side}: floor penumbra failed to widen closer to the pillar: {widths}")


if __name__ == "__main__":
    main()
