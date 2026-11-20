"""Build the Doom II Stage B emitter authoring and comparison rooms."""

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from gallery import Map, wad
from stageb_layout import Emitter, FLAT_FIXTURES, PlaneEmitter, WALL_FIXTURES, infer_layout, lit_intensity


MENU = "DoomIIEmitterLightingMenu"
ENTRYWAY_CHECKSUM = "3c9902e376cca1e9c3be8763bdc21df5"

WARM = (255, 187, 128)
AMBER = (255, 154, 86)
TEAL = (133, 238, 217)
SKYLIGHT = (179, 208, 255)


def entryway_walls(texture, sector, z, sector_light, positions):
    fixture = WALL_FIXTURES[texture]
    strength = lit_intensity(fixture.intensity, sector_light)
    return tuple(Emitter(sector, x, y, z, fixture.radius, fixture.color, strength, texture=texture)
                 for x, y in positions)


def entryway_planes(texture, sector, sector_light, positions, *, ceiling=True, narrow=False):
    fixture = FLAT_FIXTURES[texture]
    strength = lit_intensity(fixture.intensity, sector_light)
    if narrow and len(positions) > 1:
        strength = round(strength * 0.8)
    return tuple(PlaneEmitter(texture, sector, x, y, 8, fixture.radius, strength, fixture.color, ceiling)
                 for x, y in positions)


def sky(sector, x, y, radius, intensity):
    return Emitter(sector, x, y, 80, radius, SKYLIGHT, intensity, (315, 44), 1)


# The standalone comparison pack can be built without a Doom II IWAD. Cache
# the resolved fixture positions for its exact MAP01 checksum and share the
# campaign's material profiles. IWAD builds resolve Entryway from the map.
ENTRYWAY = (
    *entryway_walls("TEKGREN5", 1, 64, 160, (
        (324, 1312), (444, 1056), (444, 1440), (324, 1184),
        (324, 1446), (324, 1056), (444, 1184), (444, 1312),
    )),
    *entryway_planes("CEIL1_3", 20, 176, ((416, 670),)),
    *entryway_planes("CEIL1_2", 20, 176, ((416, 670),), ceiling=False),
    *entryway_walls("LITE5", 27, 48, 176, ((708, 504), (892, 504))),
    *entryway_walls("EXITSIGN", 34, 64, 192, ((992, 1028),)),
    *entryway_planes("CEIL1_3", 40, 176, ((928, 734),)),
    *entryway_planes("CEIL1_2", 40, 176, ((928, 734),), ceiling=False),
    *entryway_planes("FLAT2", 45, 224, ((352, 2335), (288, 2207), (288, 2463), (416, 2207), (416, 2463))),
    *entryway_planes("FLAT2", 46, 224, ((288, 2271), (352, 2271)), narrow=True),
    *entryway_planes("FLAT2", 47, 224, ((288, 2399), (352, 2399)), narrow=True),
    *entryway_planes("FLAT2", 49, 224, ((32, 2335), (-32, 2207), (-32, 2463), (96, 2207), (96, 2463))),
    *entryway_planes("FLAT2", 50, 224, ((32, 2399), (96, 2399)), narrow=True),
    *entryway_planes("FLAT2", 51, 224, ((32, 2271), (96, 2271)), narrow=True),
    *entryway_walls("TEKGREN5", 52, 64, 224, (
        (96, 1540), (416, 1660), (-124, 1376), (-124, 1632), (32, 1660),
        (-124, 1504), (224, 1540), (-4, 1376), (-4, 1504),
    )),
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
    "MAP02": "Underhalls",
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
    bool AuthoredByLayout;

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
    int CampaignLayoutRevision;
    const CurrentCampaignLayout = 3;

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
        light.AuthoredByLayout = true;
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

    void AddPlaneEmitter(String texture, int receiver, Vector2 position, int inset,
                         int size, int red, int green, int blue, int intensity, bool fromCeiling)
    {
        let sector = level.PointInSector(position);
        TextureID fixture = TexMan.CheckForTexture(texture, TexMan.Type_Flat);
        if (sector == null || sector.Index() != receiver || !fixture.IsValid() ||
            sector.GetTexture(fromCeiling ? Sector.ceiling : Sector.floor) != fixture) return;
        double height = inset;
        if (fromCeiling)
            height = sector.ceilingplane.ZatPoint(position) - sector.floorplane.ZatPoint(position) - inset;
        if (height < 8) return;
        AddEmitter(receiver, position, height, size, red, green, blue, intensity, 0.82, false, 0, 0);
    }

    bool IsLegacyLayoutEmitter(SDVKStageBPointEmitter light)
    {
        // Older packs did not mark their runtime-spawned lights. Leave map
        // things, tagged actors, subclasses and unrelated light colors alone.
        if (light.TID != 0 || light.SpawnFlags != 0) return false;
        int rgb = (light.Args[0] << 16) | (light.Args[1] << 8) | light.Args[2];
        if (light.GetClassName() == 'SDVKStageBDirectionalEmitter')
            return light.Angle == 315 && light.Pitch == 54 && light.LightLinearity == 1 &&
                   (rgb == 0xf4ead9 || rgb == 0xf2decc || rgb == 0xf8b38f);
        if (light.GetClassName() != 'SDVKStageBPointEmitter' ||
            abs(light.LightLinearity - 0.82) > 0.0001) return false;
        switch (rgb)
        {
        case 0xebeef1: case 0xffc78f: case 0xff4839: case 0x6793ff:
        case 0xff965e: case 0xfff5cd: case 0x9b69ef: case 0xff6c4f:
        case 0x87ee73: case 0xdaebd1:
            return true;
        }
        return false;
    }

    void ClearSavedCampaignEmitters()
    {
        let iterator = ThinkerIterator.Create("SDVKStageBPointEmitter", Thinker.STAT_DLIGHT);
        SDVKStageBPointEmitter light;
        while ((light = SDVKStageBPointEmitter(iterator.Next())))
        {
            if (light.AuthoredByLayout || (CampaignLayoutRevision < 2 && IsLegacyLayoutEmitter(light)))
                light.Destroy();
        }
    }

    override void WorldLoaded(WorldEvent e)
    {
        if (e.IsSaveGame || e.IsReopen) return;
        RoomLabel = "";
        CampaignLayoutRevision = CurrentCampaignLayout;
EMITTERS
        LoadCampaignLayout();
    }

    override void WorldTick()
    {
        // Restored EventHandlers keep their revision and the previous room
        // label. Only a recognized map with a previously installed layout
        // needs its saved actors replaced.
        if (CampaignLayoutRevision < CurrentCampaignLayout)
        {
            LoadCampaignLayout(RoomLabel != "");
            CampaignLayoutRevision = CurrentCampaignLayout;
        }
    }

    void LoadCampaignLayout(bool replaceSavedEmitters = false)
    {
CAMPAIGN_CASES
    }
CAMPAIGN_LAYOUTS
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


def actor_script(playable, campaign=None):
    blocks = []
    for map_name, emitters in FIXTURE_EMITTERS.items():
        blocks.extend((f'        if (level.MapName == "{map_name}")', "        {",
                       f'            RoomLabel = "{LABELS[map_name]}";'))
        blocks.extend(f"            {emitter.call()}" for emitter in emitters)
        blocks.append("        }")
    cases = []
    layouts = []
    layouts_by_map = {"MAP01": (ENTRYWAY_CHECKSUM, ENTRYWAY), **(campaign or {})}
    for map_name, (checksum, emitters) in layouts_by_map.items():
        label = f'"{LABELS[map_name]}"' if map_name == "MAP01" else "level.LevelName"
        cases.extend((f'        if (level.MapName == "{map_name}" && level.GetChecksum() == "{checksum}")',
                      "        {", "            if (replaceSavedEmitters) ClearSavedCampaignEmitters();",
                      f"            RoomLabel = {label};", "            level.EnableStageBLayout();",
                      f"            Load{map_name}();", "            return;", "        }"))
        layouts.extend((f"    void Load{map_name}()", "    {"))
        cycles = {(emitter.sector, emitter.light_cycle) for emitter in emitters if emitter.light_cycle}
        layouts.extend(f"        level.SetStageBLightPeak({sector}, {peak}, {dark});"
                       for sector, (peak, dark) in sorted(cycles))
        layouts.extend(f"        {emitter.call()}" for emitter in emitters)
        layouts.append("    }")
    return (ZSCRIPT.replace("CAMPAIGN_CASES", "\n".join(cases)).replace("CAMPAIGN_LAYOUTS", "\n".join(layouts))
            .replace("EMITTERS", "\n".join(blocks)).replace("OVERLAY", OVERLAY if playable else ""))


def build(path, playable=True, *, iwad=None):
    campaign = None
    if iwad is not None:
        from material_generator import Wad

        campaign = infer_layout(Wad(iwad))
    rooms = {"SBINDR": room_geometry(False), "SBOUT": room_geometry(True), "SBDARK": sealed_control()}
    map_defs = ['GameInfo { AddEventHandlers = "SDVKStageBLayout" }']
    for name, next_room in zip(rooms, ("SBOUT", "SBDARK", "SBINDR"), strict=True):
        sky = ' sky1 = "SKY1"' if name == "SBOUT" else ""
        map_defs.append(f'map {name} "{LABELS[name]}" {{ next = "{next_room}" nointermission{sky} }}')

    entries = {f"maps/{name}.wad": wad(name, room.text()) for name, room in rooms.items()}
    entries["ZSCRIPT"] = actor_script(playable, campaign).encode()
    entries["MAPINFO"] = ("\n".join(map_defs) + "\n").encode()
    if playable:
        menu = [f'OptionMenu "{MENU}"', "{", '  Title "Emitter lighting"',
                '  Option "Emitter lighting (B)", "gl_emitter_lighting", "OnOff"',
                '  Command "Dark campaign lighting", "gl_emitter_lighting 1; gl_emitter_ambient 0.04; '
                'gl_emitter_ambient_specular 0.08; gl_emitter_intensity 1"',
                '  Slider "Legacy ambient fill", "gl_emitter_ambient", 0.0, 1.0, 0.05, 2',
                '  Slider "PBR ambient reflections", "gl_emitter_ambient_specular", 0.0, 1.0, 0.05, 2',
                '  Slider "Emitter intensity", "gl_emitter_intensity", 0.0, 2.0, 0.05, 2',
                '  Submenu "Projectile lighting", "DoomProjectileLighting"',
                '  Submenu "Flashlight settings", "SDVKFlashlightOptions"',
                '  Submenu "PBR materials", "PBRMaterialMenu"', '  StaticText " "']
        menu.extend(f'  Command "{label}", "map {name}"' for name, label in LABELS.items()
                    if name != "MAP02" or campaign is not None)
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
    parser.add_argument("--doom2", type=Path, help="owner-supplied Doom II IWAD for campaign lighting")
    parser.add_argument("--no-overlay", action="store_true", help="omit menus and overlay for matched captures")
    args = parser.parse_args()
    build(args.out, playable=not args.no_overlay, iwad=args.doom2)
