"""Local exposure adjustments for fixture materials in the original Doom II layouts."""

from dataclasses import replace


# Radius and output multipliers apply only to the named material where its lit
# texels are exposed. The general fixture calibration covers the other surfaces.
TRIM = ("METAL6", "METAL7", "TEKBRON2", "BRONZE4", "BIGBRIK3")
CEILING_BANK = ("CEIL1_2", "CEIL1_3")
RED_PANEL = ("FLOOR1_7", "TLITE6_5")
LAVA = ("LAVA3", "LAVA4")
FISSURES = ("SLIME09", "SLIME12", "RROCK02", "RROCK05", "RROCK08", "CRACKLE2", "CRACKLE4")
FLAME_WALL = ("FIREBLU2", "FIRELAV3", "FIRELAVA", "FIREMAG2", "FIREMAG3", "FIREWALL")

EXPOSURE = {
    # Repeated amber trim along the Gantlet, Crusher and Refueling Base.
    "MAP03": [(TRIM, .76, .71)],
    "MAP06": [(TRIM, .80, .75), (LAVA, .90, .86)],
    "MAP10": [(TRIM, .70, .64)],
    # Traps and the Pit use red panels beside brighter fire or fluorescent banks.
    "MAP08": [(RED_PANEL, .78, .75), (FISSURES, .74, .65)],
    "MAP09": [(RED_PANEL, .82, .76), (TRIM, .82, .82)],
    # Keep the Factory's repeated, paired ceiling/floor panels close to their bays.
    "MAP12": [(CEILING_BANK, .78, .80)],
    # Molten pools illuminate their banks on the city maps.
    "MAP13": [(LAVA, .84, .78)],
    "MAP15": [(FISSURES, .74, .65), (LAVA, .82, .79)],
    "MAP16": [(FLAME_WALL, .88, .84)],
    # Torches carry the Tenements and Citadel. Keep secondary lamps local.
    "MAP17": [(("LITE3", "LITE5"), .82, .85)],
    "MAP18": [(FISSURES, .72, .62)],
    "MAP19": [(RED_PANEL, .73, .68), (FISSURES, .83, .75)],
    "MAP20": [(LAVA, .76, .75), (TRIM, .80, .80)],
    # Narrow trim and recesses in the Hell maps, with open voids between them.
    "MAP21": [(TRIM, .74, .68)],
    "MAP22": [(FLAME_WALL, .82, .80)],
    "MAP24": [(TRIM, .72, .65), (RED_PANEL, .80, .76)],
    "MAP25": [(FISSURES, .72, .60)],
    "MAP26": [(LAVA, .82, .78)],
    "MAP27": [(("BSTONE3", "BRICKLIT"), .85, .84)],
    # The Spirit World and Living End stack flame surfaces over burning ground.
    "MAP28": [(FISSURES, .64, .58), (FLAME_WALL, .75, .71), (LAVA, .79, .75)],
    "MAP29": [(LAVA, .77, .77), (FLAME_WALL, .84, .79)],
    # The boss arena's cooling rock can show its own embers at a distance.
    "MAP30": [(FISSURES, 0, 0)],
}


def tune_stock_lights(map_name, emitters):
    settings = {texture: (reach, output) for materials, reach, output in EXPOSURE.get(map_name, ())
                for texture in materials}
    tuned = []
    for emitter in emitters:
        values = settings.get(emitter.texture)
        if values is None:
            tuned.append(emitter)
            continue
        reach, output = values
        if reach and output:
            tuned.append(replace(emitter, radius=2 * max(1, round(emitter.radius * reach / 2)),
                                 intensity=max(1, round(emitter.intensity * output))))
    return tuned
