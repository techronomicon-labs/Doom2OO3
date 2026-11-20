"""Exercise a cold Vulkan map load, then check for shader or pipeline builds during play."""

import argparse
import csv
import json
import os
import subprocess
from collections import Counter
from pathlib import Path
from zipfile import ZipFile


SCRIPT = '''version "4.10"
class ShaderPlaytest : EventHandler
{
    override void WorldTick()
    {
        let pawn = players[0].mo;
        if (!pawn) return;
        if (level.time == 10)
        {
            let lamp = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
            lamp.Enabled[0] = true;
        }
        if (level.time == 20 || level.time == 32 || level.time == 50)
        {
            let at = pawn.Pos;
            double angle = pawn.Angle;
            at.x += cos(angle) * 52;
            at.y += sin(angle) * 52;
            at.z += 24;
            let actor = Actor.Spawn(level.time == 50 ? 'Rocket' : level.time == 32 ? 'PlasmaBall' : 'DoomImp', at, NO_REPLACE);
            if (actor)
            {
                Console.Printf("SHADER_ENCOUNTER %s", actor.GetClassName());
                actor.target = pawn;
                if (actor.bMissile) actor.Vel = (cos(angle) * 10, sin(angle) * 10, 0);
            }
        }
        if (level.time == 42 || level.time == 56 || level.time == 72) pawn.A_SetAngle(pawn.Angle + 65);
        if (level.time == 80)
        {
            Console.Printf("SHADER_PLAYTEST_FINISHED %s", level.MapName);
            level.SetFrozen(true);
        }
    }
}
'''


def check_trace(path, expect_preload):
    with path.open() as stream:
        next(stream)  # Trace version and run ID.
        rows = list(csv.DictReader(stream, delimiter="\t"))
    begin = [i for i, row in enumerate(rows) if row["event"] == "map-shader-preload-begin"]
    end = [i for i, row in enumerate(rows) if row["event"] == "map-shader-preload-end"]
    if expect_preload and not (len(begin) == len(end) == 1 and begin[0] < end[0]):
        raise RuntimeError("Expected one complete map preload in the capture")
    if not expect_preload and (begin or end):
        raise RuntimeError("Preloading ran with gl_precache disabled")

    def builds(events):
        return [r for r in events if r["event"] in ("pipeline-first-use", "shader-compile-enter")]

    during = builds(rows[begin[0]:end[0]]) if end else []
    gameplay = builds(rows[end[0]+1:] if end else [r for r in rows if int(r["frame"]) > 0])
    return {
        "preload_ms": int(rows[end[0]]["ms_utc"]) - int(rows[begin[0]]["ms_utc"]) if end else 0,
        "during_load": dict(Counter(r["event"] for r in during)),
        "during_play": [{k: r[k] for k in ("event", "frame", "stage", "detail")} for r in gameplay],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, type=Path, help="Root of the Doom II or DBP50 playtest kit")
    parser.add_argument("--exe", type=Path, help="Override the packaged executable and engine resources")
    parser.add_argument("--map", default="MAP01")
    parser.add_argument("--output", required=True, type=Path, help="New directory for isolated caches and capture")
    parser.add_argument("--baseline", action="store_true", help="Disable gl_precache and report late builds")
    args = parser.parse_args()
    pack, out = args.pack.resolve(), args.output.resolve()
    dbp = (pack / "DBP50.wad").is_file()
    game = "DBP50" if dbp else "DoomII"
    exe = (args.exe or pack / "runtime/vkdoom.exe").resolve()
    out.mkdir(parents=True)
    cache = out / "cache"
    cache.mkdir()
    fixture = out / "encounters.pk3"
    with ZipFile(fixture, "w") as archive:
        archive.writestr("MAPINFO", 'GameInfo { AddEventHandlers = "ShaderPlaytest" }\n')
        archive.writestr("ZSCRIPT", SCRIPT)
    config = out / "test.ini"
    config.write_text("[GlobalSettings]\nvk_rayquery=false\nvid_fullscreen=false\n")
    addons = pack / "addons"
    files = [pack / "DBP50.wad"] if dbp else []
    files += [addons / f"{game}-NormalPBR.pk3", addons / f"{game}-SpritePBR.pk3", addons / "Local-Flashlight.pk3"]
    if not dbp:
        files.append(addons / "DoomII-Emitter-Lighting.pk3")
    argv = [
        exe, "-iwad", pack / "doom2.wad", "-file", *files, fixture, "-config", config, "-savedir", out,
        "-nomonsters", "-noautoload", "-noautoexec", "-stdout", "-nostartup", "-nosound", "-nojoy",
        "-rngseed", "2002", "-window", "-width", "640", "-height", "480", "-sdvkobserve", out / "frame",
        "-sdvkobservecache", cache, "-sdvkobservewarmup", "100", "-sdvkobserveframes", "1", "-sdvkobservequit",
        "+vid_setsize", "640", "480", "+vid_rendermode", "4", "+gl_multisample", "4", "+gl_ssao", "0",
        "+gl_precache", str(not args.baseline).lower(), "+gl_ubershaders", "false", "+gl_levelmesh", "false",
        "+lm_dynlights", "false", "+gl_raytrace", "false", "+gl_lights", "true", "+gl_light_shadows", "0",
        "+gl_light_sprites", "true", "+gl_spritelight", "2", "+gl_viewmodel_lighting", "2",
        "+gl_world_relief", "true", "+gl_sprite_lighting_relief", "true", "+gl_emitter_lighting", str(not dbp).lower(),
        "+gl_shadow_puppets", "2", "+vid_vsync", "false", "+cl_capfps", "true", "+use_mouse", "false",
        "+i_pauseinbackground", "false", "+vid_activeinbackground", "true", "+con_notifylines", "0", "+map", args.map,
    ]
    trace = out / "pipeline.tsv"
    env = dict(os.environ, CFX_TRACE_FILE=str(trace), CFX_RUN_ID="map-shader-preload")
    log = out / "engine.log"
    with log.open("wb") as stream:
        subprocess.run(list(map(str, argv)), cwd=exe.parent, env=env, stdout=stream,
                       stderr=subprocess.STDOUT, timeout=480, check=True)
    messages = log.read_text(errors="replace")
    expected = [f"SHADER_ENCOUNTER {name}" for name in ("DoomImp", "PlasmaBall", "Rocket")]
    expected.append(f"SHADER_PLAYTEST_FINISHED {args.map}")
    if any(marker not in messages for marker in expected):
        raise RuntimeError(f"The map encounter did not finish. See {log}")
    report = check_trace(trace, not args.baseline)
    print(json.dumps(report, indent=2))
    (out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    if not args.baseline and (not report["during_load"].get("pipeline-first-use") or report["during_play"]):
        raise SystemExit("Expected the map load to cover every encountered pipeline")


if __name__ == "__main__":
    main()
