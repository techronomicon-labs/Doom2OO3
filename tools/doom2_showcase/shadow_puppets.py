"""Build the playable Doom II shadow puppet comparison room."""

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from gallery import Map, wad


MAP_NAME = "SHPDEMO"
PACK_NAME = "DoomII-Shadow-Puppets.pk3"
IMP = 30120
FILL_LIGHT = 30121
WALKER_ID = 101


def room_geometry():
    room = Map()
    west, east = -192, 192
    boundaries = (-176, 132, 164, 196, 232)
    sectors = [room.sector(floor=step * 8, ft="FLOOR5_4" if step == 0 else "FLAT5_2", light=104)
               for step in range(4)]
    for sector in sectors:
        room.rows["sector"][sector].update(heightceiling=144, textureceiling="CEIL3_5")

    def line(start, end, front, back=None, texture="CEMENT7"):
        room.line(start, end, front, back, texture=texture)
        for index in ("sidefront", "sideback"):
            side = room.rows["linedef"][-1].get(index)
            if side is not None:
                room.rows["sidedef"][side].update(scalex_mid=1, scaley_mid=1)

    for step, sector in enumerate(sectors):
        low, high = boundaries[step : step + 2]
        line((west, low), (west, high), sector)
        line((east, high), (east, low), sector)
        if step == 0:
            line((east, low), (west, low), sector, texture="BRICK7")
        if step + 1 < len(sectors):
            line((west, high), (east, high), sector, sectors[step + 1], texture="STEP1")
        else:
            line((west, high), (east, high), sector, texture="BRICK7")

    room.thing(1, -8, -66, angle=90)
    room.thing(IMP, -38, 36, angle=270)
    room.thing(IMP, 37, 66, id=WALKER_ID)
    room.thing(FILL_LIGHT, 140, 156, z=64, arg0=94, arg1=139, arg2=187, arg3=88)
    return room


ZSCRIPT = '''version "4.10"

// The two demonstration actors use the stock Imp frames and timings.
class SDVKShadowLabImp : DoomImp
{
    Default
    {
        +FRIENDLY
        +NODAMAGE
        -COUNTKILL
    }
    States
    {
    Spawn:
        TROO AB 10;
        Loop;
    Walking:
        TROO AABBCCDD 3;
        Loop;
    }
}

// An independent, cool fill on the rear steps stays on during a beam sweep.
class SDVKShadowLabFill : PointLightAttenuated
{
    Default
    {
        +DYNAMICLIGHT.NOSHADOWMAP
    }
    States { Spawn: TNT1 A -1; Stop; }
}

class SDVKShadowLabHandler : EventHandler
{
    Actor Walker;
    int Waypoint;

    override void WorldTick()
    {
        if (level.MapName != "SHPDEMO") return;
        if (level.time == 1)
        {
            let lamp = SDVKLocalFlashlightHandler(EventHandler.Find("SDVKLocalFlashlightHandler"));
            if (lamp != null) lamp.Enabled[0] = true;

            let actors = level.CreateActorIterator(101, "SDVKShadowLabImp");
            Walker = Actor(actors.Next());
            if (Walker != null) Walker.SetStateLabel("Walking");
        }
        if (Walker == null) return;

        Vector2 goal = (87, 66);
        if (Waypoint == 1) goal = (87, 104);
        else if (Waypoint == 2) goal = (14, 104);
        else if (Waypoint == 3) goal = (14, 66);
        Vector2 offset = goal - Walker.Pos.XY;
        double distance = offset.Length();
        if (distance < 0.1)
        {
            Waypoint = (Waypoint + 1) % 4;
            return;
        }

        double turn = Actor.deltaangle(Walker.Angle, atan2(offset.Y, offset.X));
        Walker.A_SetAngle(Walker.Angle + clamp(turn, -15, 15), SPF_INTERPOLATE);
        if (abs(turn) <= 20)
            Walker.TryMove(Walker.Pos.XY + offset * (min(1.4, distance) / distance), 0);
    }

    override void RenderOverlay(RenderEvent e)
    {
        if (level.MapName != "SHPDEMO" || e.Camera == null || Menu.GetCurrentMenu() != null) return;

        let option = CVar.FindCVar('gl_shadow_puppets');
        let active = CVar.FindCVar('gl_shadow_puppets_active');
        int requested = option == null ? 0 : option.GetInt();
        String mode = requested == 1 ? "Stencil" : requested == 2 ? "Depth" : "Off";
        String settings = "F1 Settings";
        if (requested != 0 && (active == null || active.GetInt() != requested))
            mode = mode .. "  (lighting fallback)";
        else if (requested == 1)
            mode = "Stencil  (hard edge)";
        else if (requested == 2)
        {
            let optionSoftness = CVar.FindCVar('gl_shadow_puppet_softness');
            double softness = optionSoftness == null ? 0 : optionSoftness.GetFloat();
            if (softness > 0)
                mode = String.Format("Depth  (softness %.2f)", softness);
            else
            {
                mode = "Depth  (hard edge)";
                settings = "F1 Adjust softness";
            }
        }
        Screen.DrawText(SmallFont, Font.CR_WHITE, 8, 8, "Shadow puppets  |  " .. mode,
            DTA_VirtualWidth, 480, DTA_VirtualHeight, 360, DTA_Shadow, true);
        Screen.DrawText(SmallFont, Font.CR_WHITE, 8, 20, "J Compare  " .. settings .. "  L Flashlight",
            DTA_VirtualWidth, 480, DTA_VirtualHeight, 360, DTA_Shadow, true);
    }
}
'''


MENUDEF = '''OptionMenu DoomIIShadowPuppetsMenu
{
    Title "Shadow Puppets"
    Option "Map geometry shadows", "gl_flashlight_map_shadows", "OnOff"
    Option "Sprite shadows (J)", "gl_shadow_puppets", "SDVKFlashlightShadowModes"
    Slider "Sprite depth edge softness", "gl_shadow_puppet_softness", 0.0, 2.0, 0.25, 2
    Command "Preview soft Depth", "gl_shadow_puppet_softness 1; gl_shadow_puppets 2", 0, 1
    Submenu "Flashlight settings", "SDVKFlashlightOptions"
    Command "Restart comparison room", "map SHPDEMO"
}
'''


def build(path):
    mapinfo = f'''GameInfo {{ AddEventHandlers = "SDVKShadowLabHandler" }}
DoomEdNums {{ {IMP} = SDVKShadowLabImp {FILL_LIGHT} = SDVKShadowLabFill }}
map {MAP_NAME} "Shadow Puppet Comparison" {{ next = "{MAP_NAME}" nointermission }}
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as archive:
        for name, value in {f"maps/{MAP_NAME}.wad": wad(MAP_NAME, room_geometry().text()),
                            "MAPINFO": mapinfo, "ZSCRIPT": ZSCRIPT, "MENUDEF": MENUDEF,
                            "DEFCVARS": "version 225\nset gl_shadow_puppets 0\n"}.items():
            archive.writestr(ZipInfo(name), value, compress_type=ZIP_DEFLATED)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help=f"output path for {PACK_NAME}")
    build(parser.parse_args().out)
