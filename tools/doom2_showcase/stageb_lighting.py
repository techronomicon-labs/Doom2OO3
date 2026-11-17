"""Build the Doom II Stage B emitter authoring and comparison rooms."""

import argparse
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from gallery import Map, wad


MENU = "DoomIIEmitterLightingMenu"
ENTRYWAY_CHECKSUM = "3c9902e376cca1e9c3be8763bdc21df5"

WARM = (255, 187, 128)
AMBER = (255, 154, 86)
TEAL = (133, 238, 217)
SKYLIGHT = (179, 208, 255)
ENTRYWAY_DAYLIGHT = (244, 234, 217)
CEILING_LIGHT_COLOURS = {
    "FLAT2": (235, 238, 241),
}


@dataclass(frozen=True)
class Emitter:
    sector: int
    x: int
    y: int
    height: int
    radius: int
    color: tuple[int, int, int]
    intensity: int
    direction: tuple[int, int] | None = None
    linearity: float = 0.82

    def call(self):
        yaw, pitch = self.direction or (0, 0)
        rgb = ", ".join(map(str, self.color))
        directional = "false" if self.direction is None else "true"
        return (f"AddEmitter({self.sector}, ({self.x}, {self.y}), {self.height}, {self.radius // 2}, "
                f"{rgb}, {self.intensity}, {self.linearity}, {directional}, {yaw}, {pitch});")


@dataclass(frozen=True)
class CeilingFixture:
    texture: str
    sector: int
    x: int
    y: int
    below_ceiling: int
    radius: int
    intensity: int

    def call(self):
        rgb = ", ".join(map(str, CEILING_LIGHT_COLOURS[self.texture]))
        return (f'AddCeilingEmitter("{self.texture}", {self.sector}, ({self.x}, {self.y}), '
                f"{self.below_ceiling}, {self.radius // 2}, {rgb}, {self.intensity});")


@dataclass(frozen=True)
class WallStrip:
    line: int

    def call(self):
        return f"AddWallStripEmitter({self.line});"


ENTRYWAY_WALL_STRIPS = tuple(WallStrip(line) for line in (
    316, 318, 320, 322, 324, 326, 328, 330, 290, 292, 293, 295, 297, 300, 301, 308, 310,
))

# Actor X, Y, radius argument and intensity from the preceding Entryway release.
# All of these ceiling points were placed at map Z 114 with the same RGB.
RETIRED_ENTRYWAY_CEILING = (
    (370, 968, 82, 68), (398, 1096, 82, 68), (370, 1240, 82, 68),
    (398, 1384, 82, 68), (370, 1512, 82, 68), (-78, 1336, 88, 88),
    (-50, 1464, 88, 88), (-50, 1592, 88, 88), (78, 1576, 88, 88),
    (206, 1560, 90, 88), (398, 1560, 90, 88), (178, 1720, 72, 64),
)


def sky(sector, x, y, radius, intensity):
    return Emitter(sector, x, y, 80, radius, SKYLIGHT, intensity, (315, 44), 1)


# The original Entryway has no lamp actors. Leave dark and unlit sectors to
# legacy fill and the flashlight. Use native sector indices and the original
# map checksum to keep the layout tied to its light fittings and open sky.
ENTRYWAY = (
    # The overcast sky is shared across exposed terraces.
    *(Emitter(sector, x, y, 80, radius, ENTRYWAY_DAYLIGHT, intensity, (315, 54), 1)
      for sector, x, y, radius, intensity in (
          (10, -486, 768, 300, 58),
          (11, -755, 712, 490, 80),
          (11, -860, 982, 440, 62),
          (12, -1030, 918, 472, 55),
          (14, 1155, -320, 512, 70),
          (14, 1376, 198, 512, 69),
          (15, 1140, -552, 512, 67),
          (15, 1410, -400, 512, 62),
          (17, 698, 184, 512, 81),
          (17, 1070, -72, 512, 71),
          (24, 842, 414, 460, 82),
          (26, 943, 376, 284, 69),
      )),
    # The yellow strips in TEKGREN5 light the corridor and the bend.
    *ENTRYWAY_WALL_STRIPS,
    # FLAT2 fluorescent housings in the two raised computer banks.
    CeilingFixture("FLAT2", 45, 352, 2208, 12, 184, 78),
    CeilingFixture("FLAT2", 45, 352, 2336, 12, 184, 78),
    CeilingFixture("FLAT2", 45, 352, 2464, 12, 184, 78),
    CeilingFixture("FLAT2", 46, 352, 2272, 12, 108, 57),
    CeilingFixture("FLAT2", 47, 352, 2400, 12, 108, 57),
    CeilingFixture("FLAT2", 49, 32, 2208, 12, 184, 78),
    CeilingFixture("FLAT2", 49, 32, 2336, 12, 184, 78),
    CeilingFixture("FLAT2", 49, 32, 2464, 12, 184, 78),
    CeilingFixture("FLAT2", 50, 32, 2400, 12, 108, 57),
    CeilingFixture("FLAT2", 51, 32, 2272, 12, 108, 57),
    # The two outdoor door strips and the small red face of the exit sign.
    Emitter(27, 712, 504, 48, 120, (235, 238, 241), 74),
    Emitter(27, 888, 504, 48, 120, (235, 238, 241), 74),
    Emitter(34, 992, 1027, 64, 54, (255, 72, 57), 26),
)

FIXTURE_EMITTERS = {
    "SBINDR": (
        Emitter(0, -116, 88, 76, 334, AMBER, 118),
        Emitter(0, 131, 130, 88, 304, TEAL, 108),
        Emitter(1, 0, 259, 63, 228, WARM, 91),
    ),
    "SBOUT": (
        sky(0, 0, 40, 512, 98),
        Emitter(1, 0, 269, 68, 208, AMBER, 111),
    ),
    "SBDARK": (
        Emitter(1, 0, 194, 84, 392, WARM, 141),
    ),
}

LABELS = {
    "MAP01": "Entryway",
    "SBINDR": "Interior point lights",
    "SBOUT": "Courtyard directional light",
    "SBDARK": "Sealed room control",
}


def room_geometry(outside):
    room = Map()
    main = room.sector(ft="FLOOR5_4" if not outside else "FLOOR3_3", light=144)
    alcove = room.sector(floor=8, ft="FLAT5_2", light=120)
    room.rows["sector"][main].update(textureceiling="F_SKY1" if outside else "CEIL3_5", heightceiling=180)
    room.rows["sector"][alcove].update(textureceiling="CEIL3_5", heightceiling=124)

    wall = "BRICK7" if outside else "CEMENT7"
    main_boundary = ((-224, -176), (-224, 192), (-64, 192), (64, 192), (224, 192), (224, -176))
    for index, (start, end) in enumerate(zip(main_boundary, main_boundary[1:] + main_boundary[:1])):
        if index == 2:
            room.line(start, end, main, alcove, texture="SUPPORT3")
        else:
            room.line(start, end, main, texture=wall if index % 2 else "BRICK7")
        room.rows["sidedef"][-1]["scalex_mid"] = 1
        room.rows["sidedef"][-1]["scaley_mid"] = 1
    alcove_boundary = ((-64, 192), (-64, 320), (64, 320), (64, 192))
    for start, end in zip(alcove_boundary, alcove_boundary[1:]):
        room.line(start, end, alcove, texture="WOOD8" if outside else "TEKWALL4")
        room.rows["sidedef"][-1].update(scalex_mid=1, scaley_mid=1)
    room.thing(1, 0, -118, angle=90)
    if not outside:
        room.thing(2028, -116, 88)
        room.thing(2028, 131, 130)
    return room


def sealed_control():
    room = Map()
    for floor_y in (-176, 32):
        sector = room.sector(ft="FLOOR5_4", light=176)
        room.rows["sector"][sector].update(textureceiling="CEIL3_5", heightceiling=152)
        corners = ((-192, floor_y), (-192, floor_y + 176), (192, floor_y + 176), (192, floor_y))
        for start, end in zip(corners, corners[1:] + corners[:1]):
            room.line(start, end, sector, texture="CEMENT7")
            room.rows["sidedef"][-1].update(scalex_mid=1, scaley_mid=1)
    room.thing(1, 0, -117, angle=90)
    return room


ZSCRIPT = '''version "4.10"
class SDVKStageBPointEmitter : PointLightAttenuated
{
    Default
    {
        +DYNAMICLIGHT.DONTLIGHTMAP
    }
    States { Spawn: TNT1 A -1; Stop; }
}

class SDVKStageBDirectionalEmitter : SDVKStageBPointEmitter
{
    Default
    {
        +DYNAMICLIGHT.NOSHADOWMAP
    }
}

class SDVKStageBLayout : EventHandler
{
    String RoomLabel;
    int EntrywayLayoutRevision;
    bool TriedEntrywayLayoutUpgrade;
    const CurrentEntrywayLayout = 1;

    SDVKStageBPointEmitter AddEmitter(int receiver, Vector2 position, double height, int size,
                    int red, int green, int blue, int intensity, double linearity, bool directional,
                    int yaw, int pitch)
    {
        let sector = level.PointInSector(position);
        if (sector == null || sector.Index() != receiver) return null;
        double floor = sector.floorplane.ZatPoint(position);
        double ceiling = sector.ceilingplane.ZatPoint(position);
        if (ceiling - floor < 16) return null;
        Vector3 origin = (position.X, position.Y, min(floor + height, ceiling - 8));
        SDVKStageBPointEmitter light;
        if (directional)
            light = SDVKStageBPointEmitter(Actor.Spawn("SDVKStageBDirectionalEmitter", origin, NO_REPLACE));
        else
            light = SDVKStageBPointEmitter(Actor.Spawn("SDVKStageBPointEmitter", origin, NO_REPLACE));
        if (light == null) return null;
        light.Args[0] = red;
        light.Args[1] = green;
        light.Args[2] = blue;
        light.Args[3] = size;
        light.Args[4] = intensity;
        light.LightLinearity = linearity;
        light.A_SetAngle(yaw);
        light.A_SetPitch(pitch);
        return light;
    }

    void AddCeilingEmitter(String texture, int receiver, Vector2 position, int belowCeiling,
                           int size, int red, int green, int blue, int intensity)
    {
        let sector = level.PointInSector(position);
        TextureID fixture = TexMan.CheckForTexture(texture, TexMan.Type_Flat);
        if (sector == null || sector.Index() != receiver || !fixture.IsValid() ||
            sector.GetTexture(Sector.ceiling) != fixture) return;
        double height = sector.ceilingplane.ZatPoint(position) - sector.floorplane.ZatPoint(position) - belowCeiling;
        if (height < 8) return;
        AddEmitter(receiver, position, height, size, red, green, blue, intensity, 0.82, false, 0, 0);
    }

    SDVKStageBPointEmitter AddWallStripEmitter(int lineIndex)
    {
        let line = level.lines[lineIndex];
        let side = line.sidedef[Line.front];
        TextureID fixture = TexMan.CheckForTexture("TEKGREN5", TexMan.Type_Wall);
        if (side == null || line.backsector != null || !fixture.IsValid() ||
            side.GetTexture(Side.mid) != fixture) return null;

        // The band spans source texels U 4–58 and V 4–11. These checksum-qualified
        // one-sided walls are ceiling-pegged and have no texture scaling.
        double along = 31 - side.GetTextureXOffset(Side.mid);
        double length = line.delta.Length();
        if (along < 0 || along >= length) return null;
        Vector2 tangent = line.delta / length;
        Vector2 face = line.v1.p + tangent * along;
        Vector2 position = face + (tangent.Y, -tangent.X) * 8;
        let sector = side.sector;
        double height = sector.ceilingplane.ZatPoint(face) + side.GetTextureYOffset(Side.mid)
                      - 8 - sector.floorplane.ZatPoint(position);
        return AddEmitter(sector.Index(), position, height, 96, 255, 245, 205, 56, 0.82, false, 0, 0);
    }

    bool IsStockEntryway()
    {
        return level.MapName == "MAP01" && level.GetChecksum() == "ENTRYWAY_CHECKSUM";
    }

    void UpgradeEntrywayLayout()
    {
        if (!IsStockEntryway()) return;

        static const int retiredSignatures[] = {RETIRED_SIGNATURES};
        static const int wallStrips[] = {WALL_STRIP_LINES};
        Array<SDVKStageBPointEmitter> retired;
        retired.Resize(retiredSignatures.Size() / 4);
        let iterator = ThinkerIterator.Create("SDVKStageBPointEmitter", Thinker.STAT_DLIGHT);
        SDVKStageBPointEmitter light;
        int matched = 0;
        while ((light = SDVKStageBPointEmitter(iterator.Next(true))))
        {
            if (light.Pos.Z != 114 || light.Args[0] != 218 || light.Args[1] != 235 ||
                light.Args[2] != 209) continue;
            for (int i = 0; i < retiredSignatures.Size(); i += 4)
            {
                if (light.Pos.X != retiredSignatures[i] || light.Pos.Y != retiredSignatures[i + 1] ||
                    light.Args[3] != retiredSignatures[i + 2] || light.Args[4] != retiredSignatures[i + 3])
                    continue;
                if (retired[i / 4] != null) return;
                retired[i / 4] = light;
                matched++;
                break;
            }
        }
        // Upgrade only a complete known layout. Preserve other lights and subclasses.
        if (matched != retired.Size()) return;

        Array<SDVKStageBPointEmitter> installed;
        for (int i = 0; i < wallStrips.Size(); i++)
        {
            light = AddWallStripEmitter(wallStrips[i]);
            if (light == null)
            {
                for (int j = 0; j < installed.Size(); j++) installed[j].Destroy();
                return;
            }
            installed.Push(light);
        }
        for (int i = 0; i < retired.Size(); i++) retired[i].Destroy();
        EntrywayLayoutRevision = CurrentEntrywayLayout;
    }

    override void WorldLoaded(WorldEvent e)
    {
        if (e.IsSaveGame || e.IsReopen) return;
        EntrywayLayoutRevision = 0;
        TriedEntrywayLayoutUpgrade = false;
        RoomLabel = "";
EMITTERS
    }

    override void WorldTick()
    {
        // A serialized EventHandler skips WorldLoaded when restoring a save.
        if (EntrywayLayoutRevision >= CurrentEntrywayLayout || TriedEntrywayLayoutUpgrade ||
            RoomLabel != "Entryway") return;
        TriedEntrywayLayoutUpgrade = true;
        UpgradeEntrywayLayout();
    }
OVERLAY
}
'''

OVERLAY = '''
    override void RenderOverlay(RenderEvent e)
    {
        if (RoomLabel == "" || e.Camera == null || Menu.GetCurrentMenu() != null) return;
        let mode = CVar.FindCVar('gl_emitter_lighting');
        let fill = CVar.FindCVar('gl_emitter_ambient');
        bool emitters = mode != null && mode.GetBool();
        String lighting = "Legacy lighting";
        if (emitters)
            lighting = String.Format("Emitters + %d%% legacy fill", fill == null ? 0 : int(100 * fill.GetFloat() + .5));
        String line = String.Format("%s   |   %s", RoomLabel, lighting);
        Screen.DrawText(SmallFont, Font.CR_WHITE, 8, 8, line,
            DTA_VirtualWidth, 480, DTA_VirtualHeight, 360, DTA_Shadow, true);
        Screen.DrawText(SmallFont, Font.CR_WHITE, 8, 20, "B Compare   F1 Lighting   L Flashlight",
            DTA_VirtualWidth, 480, DTA_VirtualHeight, 360, DTA_Shadow, true);
    }
'''


def actor_script(playable):
    blocks = []
    for map_name, emitters in (("MAP01", ENTRYWAY), *FIXTURE_EMITTERS.items()):
        condition = "IsStockEntryway()" if map_name == "MAP01" else f'level.MapName == "{map_name}"'
        blocks.extend((f"        if ({condition})", "        {", f'            RoomLabel = "{LABELS[map_name]}";'))
        blocks.extend(f"            {emitter.call()}" for emitter in emitters)
        if map_name == "MAP01":
            blocks.append("            EntrywayLayoutRevision = CurrentEntrywayLayout;")
        blocks.append("        }")
    return (ZSCRIPT.replace("ENTRYWAY_CHECKSUM", ENTRYWAY_CHECKSUM)
            .replace("RETIRED_SIGNATURES", ", ".join(str(value) for row in RETIRED_ENTRYWAY_CEILING for value in row))
            .replace("WALL_STRIP_LINES", ", ".join(str(strip.line) for strip in ENTRYWAY_WALL_STRIPS))
            .replace("EMITTERS", "\n".join(blocks)).replace("OVERLAY", OVERLAY if playable else ""))


def build(path, playable=True):
    rooms = {"SBINDR": room_geometry(False), "SBOUT": room_geometry(True), "SBDARK": sealed_control()}
    map_defs = ['GameInfo { AddEventHandlers = "SDVKStageBLayout" }']
    for name, next_room in zip(rooms, ("SBOUT", "SBDARK", "SBINDR"), strict=True):
        sky = ' sky1 = "SKY1"' if name == "SBOUT" else ""
        map_defs.append(f'map {name} "{LABELS[name]}" {{ next = "{next_room}" nointermission{sky} }}')

    entries = {f"maps/{name}.wad": wad(name, room.text()) for name, room in rooms.items()}
    entries["ZSCRIPT"] = actor_script(playable).encode()
    entries["MAPINFO"] = ("\n".join(map_defs) + "\n").encode()
    if playable:
        menu = [f'OptionMenu "{MENU}"', "{", '  Title "Emitter lighting"',
                '  Option "Emitter lighting (B)", "gl_emitter_lighting", "OnOff"',
                '  Slider "Legacy ambient fill", "gl_emitter_ambient", 0.0, 1.0, 0.05, 2',
                '  Slider "PBR ambient reflections", "gl_emitter_ambient_specular", 0.0, 1.0, 0.05, 2',
                '  Slider "Emitter intensity", "gl_emitter_intensity", 0.0, 2.0, 0.05, 2',
                '  Submenu "Flashlight settings", "SDVKFlashlightOptions"',
                '  Submenu "PBR materials", "PBRMaterialMenu"', '  StaticText " "']
        menu.extend(f'  Command "{label}", "map {name}"' for name, label in LABELS.items())
        menu.extend(("}", 'AddOptionMenu "OptionsMenu"', "{", f'  Submenu "Emitter lighting", "{MENU}"', "}"))
        entries["MENUDEF"] = ("\n".join(menu) + "\n").encode()

    with ZipFile(path, "w") as pack:
        for name, data in entries.items():
            member = ZipInfo(name)
            member.compress_type = ZIP_DEFLATED
            pack.writestr(member, data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-overlay", action="store_true", help="omit menus and overlay for matched captures")
    args = parser.parse_args()
    build(args.out, playable=not args.no_overlay)
