"""Structural height profiles for the stock Doom II flat namespace."""

import numpy as np

from structural_relief import HeightTile, brick_floor, smooth_band


FLAT_SIZE = 64


def _joints(tile, vertical=(), horizontal=(), spans=(), depth=0.38, width=2.3):
    tile.joints(vertical, horizontal, spans, depth, width)


def _parquet(tile):
    # The three stock color variants share the same drawn board layout.
    # Coordinates beyond 64 carry a joint through the repeated tile boundary.
    seams = (
        (14.25, 46.75, 14.25, 81.0),
        (18.75, 53.75, 18.75, 74.75),
        (40.5, 53.75, 40.5, 74.75),
        (35.5, 10.75, 35.5, 53.75),
        (6.5, 17.0, 6.5, 24.75),
        (6.5, 33.75, 6.5, 46.75),
        (59.0, 17.0, 78.25, 17.0),
        (59.0, 46.75, 78.25, 46.75),
        (18.0, 10.75, 40.5, 10.75),
        (6.5, 24.75, 35.5, 24.75),
        (6.5, 33.75, 35.5, 33.75),
        (18.75, 53.75, 40.5, 53.75),
    )
    _joints(tile, (59.0,), spans=seams, depth=0.47, width=2.5)
    _joints(tile, spans=((40.5, 1.75, 59.0, 1.75),), depth=0.31, width=2.1)


def _large_blocks(tile):
    _joints(tile, horizontal=(0, 32), spans=((5, 0, 5, 32), (55, 32, 55, 64)),
            depth=0.47, width=2.8)


def _flagstone(tile):
    # FLAT5 draws a staggered hexagonal repeat, with an eight-texel
    # horizontal joint alternating between the two column positions.
    spans = []
    for course in range(8):
        y = 4.5 + course * 8
        for x in (course % 2 * 16 + 0.5, course % 2 * 16 + 32.5):
            spans.extend(((x - 4, y, x + 4, y),
                          (x - 4, y, x - 12, y + 8),
                          (x + 4, y, x + 12, y + 8)))
    _joints(tile, spans=spans, depth=0.34, width=1.75)


def _box(tile, x, y, width, height, depth, bevel=1.55, chamfer=0.0):
    # A signed distance to the faces, with optional diagonal corners.
    u = np.abs(tile.wrapped_offset(tile.u, x, tile.width))
    v = np.abs(tile.wrapped_offset(tile.v, y, tile.height))
    distance = np.maximum(u - width * 0.5, v - height * 0.5)
    if chamfer:
        distance = np.maximum(distance, (u + v - (width + height) * 0.5 + chamfer) * 0.7071)
    tile.values += depth * smooth_band(distance, -bevel, bevel)


def _ring(tile, x, y, radius, depth, width=2.0):
    u = tile.wrapped_offset(tile.u, x, tile.width)
    v = tile.wrapped_offset(tile.v, y, tile.height)
    tile.values += depth * smooth_band(np.abs(np.hypot(u, v) - radius), 0.25, width)


def _vents(tile):
    _joints(tile, (0, 32), (0,), depth=0.20, width=1.65)
    for x, rows in ((16, (4, 12, 20, 28, 36, 44, 52, 60)), (47, (4, 12, 20, 44, 52, 60))):
        for y in rows:
            _box(tile, x, y, 26, 3.7, -0.26, 1.15, 1.1)


def _chamfered_tiles(tile):
    # Follow the shared octagonal plate outline and the short side-panel joins.
    outline = ((30, 0), (47, 0), (63, 16), (47, 32), (30, 32), (15, 16), (30, 0))
    spans = [
        (x0, y0 + offset, x1, y1 + offset)
        for offset in (0, 32)
        for (x0, y0), (x1, y1) in zip(outline, outline[1:])
    ]
    spans.extend(((63, 16, 79, 16), (63, 48, 79, 48)))
    _joints(tile, spans=spans, depth=0.40, width=2.1)
    for y in (16, 48):
        tile.values += 0.16 * tile.mound(39, y, 19, 13)


def _wood_ceiling(tile):
    _joints(tile, (0, 32), (), depth=0.20, width=1.6)
    for x in (16, 48):
        _box(tile, x, 9, 27, 23, 0.18, 2.2, 4)
        _box(tile, x, 44, 27, 38, 0.18, 2.2, 4)


def _lattice(tile):
    u = np.abs(tile.wrapped_offset(tile.u, 10, 16))
    v = np.abs(tile.wrapped_offset(tile.v, 9, 16))
    tile.values += 0.34 * smooth_band(np.minimum(u, v), 0.4, 2.7)


def _oval_panels(tile):
    for y in (17, 47):
        _box(tile, 32, y, 55, 24, 0.22, 2.5, 9)


def _computer_plates(tile):
    for x in (15, 40):
        _box(tile, x, 27, 22, 50, -0.24, 2.1)


def _step(tile, vertical):
    for center in (16, 48):
        x, y = (center, 32) if vertical else (32, center)
        width, height = (23, 55) if vertical else (57, 23)
        _box(tile, x, y, width, height, -0.30, 2.0)
    _joints(tile, (0,), (0,), depth=0.15, width=1.8)


def _fixture(tile, x, y, width, height):
    # Housing, bezel and inset light well have fixed geometry across color variants.
    _box(tile, x, y, width, height, 0.17, 1.9)
    _box(tile, x, y, width - 6, height - 6, -0.33, 1.45)


def _light_points(tile, xs, ys, radius):
    for x in xs:
        for y in ys:
            _ring(tile, x, y, radius, -0.23, 1.6)


def _molded_ceiling_covers(tile):
    for x in (16, 48):
        for y in (8, 24, 40, 56):
            _ring(tile, x, y, 5.5, -0.085, 1.6)


def _console(tile, name):
    if name == "CONS1_7":
        _fixture(tile, 30, 35, 27, 29)
        _box(tile, 26, 12, 21, 10, 0.15, 1.5)
        _box(tile, 10, 32, 11, 55, 0.11, 1.5)
    else:
        rotate = name == "CONS1_5"
        _fixture(tile, 30, 35 if rotate else 31, 29, 23)
        _box(tile, 11 if rotate else 52, 33, 11, 24, 0.15, 1.55)
        _box(tile, 32, 55 if rotate else 8, 51, 15, 0.11, 1.5)


def _grille(tile):
    _box(tile, 32, 32, 58, 34, 0.17, 1.9)
    for x in (10, 21, 32, 43, 54):
        _box(tile, x, 32, 5, 27, -0.45, 1.5)


def _grid_light(tile):
    _fixture(tile, 32, 32, 47, 43)
    for x in (16, 24, 32, 40, 48):
        _box(tile, x, 32, 3, 25, 0.14, 1.1)


def _blur_along(values, radius, direction):
    extent = int(np.ceil(radius * 3))
    offsets = np.arange(-extent, extent + 1)
    weights = np.exp(-0.5 * (offsets / radius) ** 2)
    weights /= weights.sum()
    return sum(
        weight * np.roll(values, (shift * direction[0], shift * direction[1]), (0, 1))
        for shift, weight in zip(offsets, weights)
    )


def _periodic_blur(values, radius):
    # Filter on the torus so the source tile has continuous height at UV wrap.
    return _blur_along(_blur_along(values, radius, (1, 0)), radius, (0, 1))


def _sample_to_tile(tile, values):
    u, v = tile.u - 0.5, tile.v - 0.5
    x, y = np.floor(u).astype(int), np.floor(v).astype(int)
    a, b = u - x, v - y
    x0, x1 = x % FLAT_SIZE, (x + 1) % FLAT_SIZE
    y0, y1 = y % FLAT_SIZE, (y + 1) % FLAT_SIZE
    return ((1 - a) * values[y0, x0] + a * values[y0, x1]) * (1 - b) + (
        (1 - a) * values[y1, x0] + a * values[y1, x1]
    ) * b


def _local_feature(values, radii, directions=((1, 0), (0, 1), (1, 1), (1, -1))):
    # A groove/ridge needs opposing banks in at least one direction.
    feature = np.zeros_like(values)
    for radius in radii:
        for y, x in directions:
            a = np.roll(values, (radius * y, radius * x), (0, 1)) - values
            b = np.roll(values, (-radius * y, -radius * x), (0, 1)) - values
            np.maximum(feature, np.minimum(a, b), out=feature)
    return feature


def _natural(tile, pixels, depth, radii, ridges=0.0, ignore_red_ink=False):
    # Named material families select the scale and interpretation. Use local
    # shape contrast at two radii, which rejects paint or a gradual light ramp.
    rgb = pixels[:, :, :3].astype(np.float32) / 255.0
    red, green, blue = rgb.transpose(2, 0, 1)
    values = _periodic_blur(0.25 * red + 0.55 * green + 0.20 * blue, 0.58)
    grooves = smooth_band(-_local_feature(values, radii), -0.22, -0.035)
    relief = -depth * grooves
    if ridges:
        relief += ridges * smooth_band(-_local_feature(-values, radii), -0.22, -0.04)
    if ignore_red_ink:
        red_ink = (red - np.maximum(green, blue) > 0.12).astype(np.float32)
        relief *= 1.0 - np.clip(2.4 * _periodic_blur(red_ink, 1.0), 0.0, 1.0)
    tile.values += _sample_to_tile(tile, _periodic_blur(relief, 0.65))


def _feature_band(feature, minimum):
    # Let a low-contrast material use the authored range only where it has
    # actual opposing banks. The absolute minimum excludes quantization noise.
    upper = float(np.clip(np.quantile(feature, 0.94), minimum * 2.5, 0.18))
    return smooth_band(-feature, -upper, -max(minimum, upper * 0.30))


def _stone_shapes(tile, pixels, depth, ridge_height, minimum):
    red, green, blue = pixels[:, :, :3].astype(np.float32).transpose(2, 0, 1) / 255.0
    tone = 0.25 * red + 0.55 * green + 0.20 * blue
    _granular_shapes(tile, tone, depth, ridge_height, minimum)


def _granular_shapes(tile, tone, depth, ridge_height, minimum):
    fine = _periodic_blur(tone, 0.52)
    broad = _periodic_blur(tone, 1.32)

    def features(sign):
        small_banks = _local_feature(sign * fine, (2, 3))
        broad_banks = _local_feature(sign * broad, (4, 6))
        return _feature_band(np.maximum(0.58 * small_banks, broad_banks), minimum)

    relief = -depth * features(1)
    if ridge_height:
        relief += ridge_height * features(-1)
    tile.values += _sample_to_tile(tile, _periodic_blur(relief, 0.78))


def _brushed_plate(tile, pixels):
    # The broad light stripe runs across the sheet. Retain only narrow
    # channels that continue down the visible grain, independent of that stripe.
    tone = pixels[:, :, 0].astype(np.float32) / 255.0
    brushed = _blur_along(tone - _blur_along(tone, 3.0, (0, 1)), 2.3, (1, 0))
    across = ((0, 1),)
    cuts = _feature_band(_local_feature(brushed, (1, 2), across), 0.0035)
    ridges = _feature_band(_local_feature(-brushed, (1, 2), across), 0.0035)
    relief = 0.055 * ridges - 0.19 * cuts
    tile.values += _sample_to_tile(tile, _blur_along(relief, 0.55, (0, 1)))


def _dyed_floor(tile, pixels):
    blue = pixels[:, :, 2].astype(np.float32) / 255.0
    # Both logo colors are dye. Sample the original rough flooring from
    # the other half of the repeat through those solid pixels and nearby.
    dye = smooth_band(-blue, -0.59, -0.52)
    exclusion = np.clip(_periodic_blur(dye, 1.25) * 2.0, 0.0, 1.0)
    exclusion = np.maximum(exclusion, dye)
    substrate = np.minimum(blue, 0.49)
    substrate = substrate * (1.0 - exclusion) + np.roll(substrate, 32, axis=0) * exclusion
    _granular_shapes(tile, substrate, 0.11, 0.075, 0.012)


def _wood_shapes(tile, pixels, name):
    red, green, blue = pixels[:, :, :3].astype(np.float32).transpose(2, 0, 1) / 255.0
    # FLOOR3_3 draws its oblique wear with a green/brown palette separation.
    # For the other timbers use their drawn vertical grain.
    diagonal = name == "FLOOR3_3"
    tone = red - green if diagonal else 0.25 * red + 0.55 * green + 0.20 * blue
    along = (1, 1) if diagonal else (1, 0)
    across = ((1, -1),) if diagonal else ((0, 1),)
    grain = _blur_along(_periodic_blur(tone, 0.72), 2.0, along)
    cuts = _feature_band(_local_feature(grain, (2, 4, 6), across), 0.010)
    ridges = _feature_band(_local_feature(-grain, (3, 5), across), 0.012)
    relief = 0.13 * ridges - 0.31 * cuts
    tile.values += _sample_to_tile(tile, _periodic_blur(relief, 0.64))


def _crust(tile, pixels, molten):
    rgb = pixels[:, :, :3].astype(np.float32) / 255.0
    if molten:
        # The reviewed yellow lava channel has bright green and high saturation.
        red, green, blue = rgb.transpose(2, 0, 1)
        channel = smooth_band(-green, -0.60, -0.35) * smooth_band(blue - red, -0.45, -0.25)
    else:
        # RROCK04 draws explicit black gaps between the individual plates.
        channel = (rgb.max(axis=2) < 0.025).astype(np.float32)
    tile.values -= 0.43 * _sample_to_tile(tile, _periodic_blur(channel, 0.86))


JOINT_PROFILES = (
    ("Parquet board seams", "FLOOR0_1 FLOOR0_2 FLOOR0_3", _parquet),
    ("Concrete slab joints", "FLOOR0_5 FLOOR0_6 FLOOR0_7",
     lambda t: _joints(t, (40,), (8, 40), depth=0.44)),
    ("Paving block joints", "FLAT8", brick_floor),
    ("Large masonry block joints", "RROCK14", _large_blocks),
    ("Staggered flagstone joints", "FLAT5", _flagstone),
    ("Concrete expansion joint", "FLAT18", lambda t: _joints(t, horizontal=(32,), depth=0.33)),
    ("Square tile grout", "FLAT20",
     lambda t: _joints(t, range(0, 64, 8), range(0, 64, 8), depth=0.27, width=1.35)),
    ("Steel panel seams", "FLAT3",
     lambda t: _joints(t, (0, 32), (0, 32), depth=0.32, width=1.9)),
    ("Metal lattice beams", "FLAT4", _lattice),
    ("Overhead metal frame", "MFLR8_1",
     lambda t: _joints(t, (), (14, 46), ((11, 0, 11, 14), (58, 14, 58, 46), (11, 46, 11, 64)))),
    ("Metal floor plate joints", "SLIME13",
     lambda t: _joints(t, (), (0, 11, 21, 32, 43, 53), depth=0.23, width=1.6)),
    ("Riveted floor plate joints", "SLIME14 SLIME15 SLIME16",
     lambda t: _joints(t, (0, 32), (0, 32), depth=0.30, width=2.1)),
    ("Framed timber ceiling", "CEIL1_1", lambda t: _joints(t, (4, 60), (3,), depth=0.24)),
    ("Ceiling coffers", "CEIL3_1 CEIL3_2", _wood_ceiling),
    ("Ceiling panels", "CEIL3_3",
     lambda t: _joints(t, range(0, 64, 16), range(0, 64, 16), depth=0.17, width=1.5)),
    ("Ceiling frame tracks", "CEIL3_5 CEIL3_6",
     lambda t: _joints(t, (15, 48), (11, 58), depth=0.35, width=2.35)),
    ("Vent slots in cast panels", "FLOOR4_1 FLOOR4_5", _vents),
    ("Chamfered floor plates", "FLOOR4_8 FLOOR5_1 FLOOR5_2 FLOOR5_3", _chamfered_tiles),
    ("Recessed metal step grilles", "STEP1", lambda t: _step(t, True)),
    ("Recessed metal step grilles", "STEP2", lambda t: _step(t, False)),
    ("Framed floor lamp", "FLOOR1_7", lambda t: _fixture(t, 32, 32, 59, 31)),
    ("Framed ceiling lamp", "FLAT2", lambda t: _fixture(t, 32, 32, 35, 30)),
    ("Framed ceiling lamp", "FLAT17", lambda t: _fixture(t, 32, 32, 59, 30)),
    ("Framed ceiling coffer", "CEIL3_4", lambda t: _fixture(t, 32, 32, 40, 44)),
    ("Slotted ceiling lamp", "CEIL1_2 CEIL1_3", _grid_light),
    ("Stone grille apertures", "FLAT1_3", _grille),
    ("Diamond lamp housing", "TLITE6_1 TLITE6_4",
     lambda t: _box(t, 32, 32, 30, 30, 0.23, 2.1, 14.0)),
    ("Four circular lamp bezels", "TLITE6_5 TLITE6_6",
     lambda t: _light_points(t, (11, 44), (17, 49), 5.5)),
    ("Molded circular ceiling panel rims", "GRNLITE1", _molded_ceiling_covers),
    ("Circular hatch rim", "FLAT22", lambda t: _ring(t, 32, 32, 28, -0.34, 2.4)),
    ("Gate plate rim", "GATE1 GATE2 GATE3 GATE4",
     lambda t: _ring(t, 32, 32, 27, -0.24, 2.15)),
    ("Rounded inset panels", "FLAT9", _oval_panels),
    ("Pair of framed plates", "COMP01", _computer_plates),
)


NATURAL_PROFILES = (
    ("Irregular mortar and flagstone valleys",
     "GRNROCK RROCK11 RROCK13",
     0.38, (2, 4), 0.09, False),
    ("Rock and aggregate relief",
     "FLOOR6_1 FLOOR6_2 FLAT10 MFLR8_2 MFLR8_3 MFLR8_4 RROCK16 RROCK19",
     0.23, (2, 3), 0.15, False),
    ("Weathered marble valleys",
     "FLOOR7_2 DEM1_5 DEM1_6", 0.28, (2, 5), 0.05, False),
    ("Marble carving and surface structure",
     "DEM1_1 DEM1_2 DEM1_3 DEM1_4", 0.22, (2, 4), 0.08, True),
    ("Organic folds and cavities",
     "SFLR6_1 SFLR6_4 SFLR7_1 SFLR7_4 FLAT5_6", 0.30, (2, 4), 0.09, False),
    ("Timber grain and worn grooves", "FLAT5_1", 0.23, (2, 4), 0.04, False),
)


STONE_PROFILES = (
    ("Interlocking paver joints", "FLOOR4_6", 0.44, 0.0, 0.007),
    ("Cobblestone banks and mortar joints", "FLAT1_1 FLAT1_2 RROCK10 RROCK12 RROCK15",
     0.46, 0.15, 0.011),
    ("Compacted gravel ridges and pits", "RROCK09", 0.23, 0.14, 0.008),
    ("Fine pits in a coated surface", "CEIL5_1 CEIL5_2", 0.10, 0.065, 0.0025),
    ("Low grass clumps and exposed soil", "GRASS1", 0.12, 0.14, 0.008),
    ("Aggregate pits and raised fragments", "FLAT5_7 FLAT5_8 RROCK17 RROCK18 FLAT5_5",
     0.30, 0.21, 0.011),
)


NEUTRAL_PROFILES = (
    ("Liquid surface", "NUKAGE1 NUKAGE2 NUKAGE3 FWATER1 FWATER2 FWATER3 FWATER4 "
     "LAVA1 LAVA2 LAVA3 LAVA4 BLOOD1 BLOOD2 BLOOD3 SLIME01 SLIME02 SLIME03 SLIME04 "
     "SLIME05 SLIME06 SLIME07 SLIME08"),
    ("Sky flat", "F_SKY1 F_RSKY1 F_RSKY2 F_RSKY3"),
    ("Animated molten crust without a stable authored height", "RROCK01 RROCK05 RROCK06 RROCK07 RROCK08 "
     "SLIME09 SLIME10 SLIME11 SLIME12"),
    ("Flat finish or fine stipple without identifiable relief",
     "FLAT1 FLAT14 FLAT19 CRATOP1 CRATOP2 "
     "RROCK03 RROCK20 GRASS2 FLOOR1_6 FLAT5_3 CEIL4_1"),
    ("Decorative blue pattern without identifiable geometry", "CEIL4_2 CEIL4_3"),
)


JOINT_BY_NAME = {name: (label, draw) for label, names, draw in JOINT_PROFILES for name in names.split()}
NATURAL_BY_NAME = {
    name: (label, depth, radii, ridges, ignore_red)
    for label, names, depth, radii, ridges, ignore_red in NATURAL_PROFILES
    for name in names.split()
}
STONE_BY_NAME = {
    name: (label, depth, ridge_height, minimum)
    for label, names, depth, ridge_height, minimum in STONE_PROFILES
    for name in names.split()
}
WOOD_NAMES = frozenset(("FLOOR3_3", "FLOOR7_1", "FLAT5_4"))
NEUTRAL_BY_NAME = {name: label for label, names in NEUTRAL_PROFILES for name in names.split()}
CONSOLES = frozenset(("CONS1_1", "CONS1_5", "CONS1_7"))


def height_map(name, pixels):
    """Return encoded height and description, or a reason for neutral coverage."""
    if pixels.shape != (FLAT_SIZE, FLAT_SIZE, 4) or not np.all(pixels[:, :, 3] == 255):
        return None
    name = name.upper()
    if name in NEUTRAL_BY_NAME:
        return None, NEUTRAL_BY_NAME[name]
    tile = HeightTile(FLAT_SIZE, FLAT_SIZE)
    if name in JOINT_BY_NAME:
        label, draw = JOINT_BY_NAME[name]
        draw(tile)
    elif name in NATURAL_BY_NAME:
        label, depth, radii, ridges, ignore_red = NATURAL_BY_NAME[name]
        _natural(tile, pixels, depth, radii, ridges, ignore_red)
    elif name in STONE_BY_NAME:
        label, depth, ridge_height, minimum = STONE_BY_NAME[name]
        _stone_shapes(tile, pixels, depth, ridge_height, minimum)
    elif name == "FLAT23":
        label = "Long, shallow brushed-steel grooves"
        _brushed_plate(tile, pixels)
    elif name == "FLOOR1_1":
        label = "Grain in the dyed flooring below the UAC mark"
        _dyed_floor(tile, pixels)
    elif name in WOOD_NAMES:
        label = "Directional worn grain and grooves"
        _wood_shapes(tile, pixels, name)
    elif name in CONSOLES:
        label = "Console panel housings"
        _console(tile, name)
    elif name in ("RROCK02", "RROCK04"):
        label = "Crust plates and exposed cracks"
        _crust(tile, pixels, molten=name == "RROCK02")
    else:
        return None

    encoded = np.rint(np.clip(128.0 + tile.values * 255.0, 0.0, 255.0)).astype(np.uint8)
    if not np.any(encoded != 128):
        return None, f"{label} without sufficient structural contrast"
    return encoded, label
