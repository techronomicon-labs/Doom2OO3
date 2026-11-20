"""Authored, tileable structural height for selected stock Doom II surfaces.

Coordinates are in source texels. A height of zero is the wall or floor plane;
signed offsets are encoded around 128 in the auxiliary grayscale PNG.
"""

import numpy as np


def smooth_band(distance, inner, outer):
    ramp = np.clip((outer - distance) / (outer - inner), 0.0, 1.0)
    return ramp * ramp * (3.0 - 2.0 * ramp)


class HeightTile:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.u = (np.arange(2 * width)[None, :] + 0.5) * 0.5
        self.v = (np.arange(2 * height)[:, None] + 0.5) * 0.5
        self.values = np.zeros((2 * height, 2 * width), dtype=np.float32)

    @staticmethod
    def wrapped_offset(coordinate, center, period):
        return (coordinate - center + period * 0.5) % period - period * 0.5

    def segment_distance(self, x0, y0, x1, y1):
        x = self.wrapped_offset(self.u, (x0 + x1) * 0.5, self.width)
        y = self.wrapped_offset(self.v, (y0 + y1) * 0.5, self.height)
        dx, dy = x1 - x0, y1 - y0
        along = np.clip((x * dx + y * dy) / (dx * dx + dy * dy), -0.5, 0.5)
        return np.hypot(x - along * dx, y - along * dy)

    def joints(self, vertical=(), horizontal=(), spans=(), depth=0.45, width=3.0):
        # The deepest join wins at an intersection. Stacking grooves would
        # create decorative dimples where structurally there is only mortar.
        for x in vertical:
            distance = np.abs(self.wrapped_offset(self.u, x, self.width))
            np.minimum(
                self.values, -depth * smooth_band(distance, 0.25, width), out=self.values
            )
        for y in horizontal:
            distance = np.abs(self.wrapped_offset(self.v, y, self.height))
            np.minimum(
                self.values, -depth * smooth_band(distance, 0.25, width), out=self.values
            )
        for span in spans:
            distance = self.segment_distance(*span)
            np.minimum(
                self.values, -depth * smooth_band(distance, 0.25, width), out=self.values
            )

    def contour(self, points, inner, outer):
        field = np.full_like(self.values, np.inf)
        for a, b in zip(points, points[1:]):
            np.minimum(field, self.segment_distance(*a, *b), out=field)
        return smooth_band(field, inner, outer)

    def mound(self, x, y, radius_x, radius_y):
        offset_u = self.wrapped_offset(self.u, x, self.width) / radius_x
        offset_v = self.wrapped_offset(self.v, y, self.height) / radius_y
        return smooth_band(np.hypot(offset_u, offset_v), 0.10, 1.0)


def staggered_joints(positions, course_height):
    return [
        (x, row * course_height, x, (row + 1) * course_height)
        for row, start in enumerate(positions)
        for x in range(start, 64, 32)
    ]


def brick_wall(tile):
    # Eight courses following the stagger of BRICK7's drawn joints.
    joints = staggered_joints((0, 8, 16, 24) * 2, 16)
    tile.joints(horizontal=range(0, 128, 16), spans=joints, depth=0.48, width=3.2)


def thin_brick_wall(tile):
    # BRICK1 reverses the direction of the stagger halfway down the tile.
    positions = (0, 8, 16, 24) * 2 + (0, 24, 16, 8) * 2
    joints = staggered_joints(positions, 8)
    tile.joints(horizontal=range(0, 128, 8), spans=joints, depth=0.36, width=2.15)


def fractured_wall(tile):
    # Trace the major cracks in BRICK4 and deepen the distinct pits.
    cracks = (
        (((46, 1), (46, 7), (44, 10), (36, 17), (26, 22), (19, 24), (12, 28)), 0.24),
        (((63, 24), (57, 27), (51, 31), (44, 40), (42, 45), (37, 55)), 0.31),
        (((43, 45), (48, 49), (55, 52), (62, 55)), 0.22),
        (((6, 65), (14, 68), (23, 72), (30, 75), (39, 81), (50, 91)), 0.31),
        (((23, 72), (22, 77), (17, 81)), 0.22),
        (((1, 96), (8, 100), (18, 104), (25, 111), (33, 118), (44, 123)), 0.24),
        (((33, 118), (26, 122), (19, 126)), 0.23),
    )
    for points, depth in cracks:
        np.minimum(tile.values, -depth * tile.contour(points, 0.2, 2.6), out=tile.values)

    for x, y in ((45, 9), (19, 24), (43, 45), (23, 72), (18, 104), (33, 118)):
        np.minimum(tile.values, -0.47 * tile.mound(x, y, 4.7, 4.0), out=tile.values)


def concrete_wall(tile):
    # Large blocks and the staggered band of smaller inset blocks.
    # Continue the same joins across the tile boundary.
    outer = [(x, 74, x, 128) for x in (20, 36, 51)] + [
        (x, 0, x, 53) for x in (20, 36, 51)
    ]
    band = [(x, 53, x, 74) for x in (8, 16, 24, 33, 40, 49, 57)]
    tile.joints(
        vertical=(0,), horizontal=(53, 74), spans=outer + band, depth=0.42, width=2.9
    )


def carved_wall(tile):
    # Positive masses for the brow, muzzle, jaw and horns. Carve separately
    # positioned channels for the eyes and nostrils.
    def mirror(points, side):
        return [(64 + side * u, v) for u, v in points]

    tile.values += 0.43 * tile.mound(64, 42, 37, 36)
    tile.values += 0.36 * tile.mound(64, 87, 25, 29)
    for side in (-1, 1):
        horn = mirror([(25, 30), (37, 24), (48, 26), (50, 36), (52, 46)], side)
        tile.values += 0.36 * tile.contour(horn, 2.4, 11.2)
        tile.values += 0.23 * tile.mound(64 + side * 20, 101, 13, 18)
        brow = mirror([(4, 64), (16, 59), (25, 56)], side)
        eye = mirror([(6, 69), (14, 67), (22, 63)], side)
        tile.values += 0.26 * tile.contour(brow, 0.8, 5.0)
        tile.values -= 0.40 * tile.contour(eye, 0.9, 4.5)
        tile.values -= 0.35 * tile.mound(64 + side * 4, 89, 5, 8)
    mouth = [(50, 101), (56, 104), (72, 104), (78, 101)]
    tile.values -= 0.22 * tile.contour(mouth, 0.5, 4.3)


def wood_wall(tile):
    # Outline the two broad boards.
    tile.joints(vertical=(0, 32), depth=0.47, width=3.1)


def wood_floor(tile):
    ends = [
        (x, y, x + 16, y) for x, y in zip(range(0, 64, 16), (15, 23, 8, 31))
    ]
    tile.joints(vertical=(0, 16, 32, 48), spans=ends, depth=0.44, width=2.7)


def brick_floor(tile):
    rows = ((32,), (24, 56), (16, 48), (8, 40))
    joints = [
        (x, y, x + 16, y)
        for x, cuts in zip(range(0, 64, 16), rows)
        for y in cuts
    ]
    tile.joints(vertical=(0, 16, 32, 48), spans=joints, depth=0.44, width=2.9)


def metal_wall(tile):
    tile.joints(vertical=(0, 32), horizontal=(0, 64), depth=0.20, width=2.6)


# Match exact stock material names, namespaces and dimensions.
PROFILES = {
    ("wall", "BRICK1"): ("thin brick courses", (64, 128), thin_brick_wall),
    ("wall", "BRICK4"): ("fractured masonry", (64, 128), fractured_wall),
    ("wall", "BRICK7"): ("brick and mortar", (64, 128), brick_wall),
    ("wall", "CEMENT7"): ("concrete blocks", (64, 128), concrete_wall),
    ("wall", "MARBFAC3"): ("carved stone", (128, 128), carved_wall),
    ("wall", "WOOD8"): ("split planks", (64, 128), wood_wall),
    ("wall", "WOOD9"): ("split planks", (64, 128), wood_wall),
    ("flat", "FLAT5_2"): ("plank floor", (64, 64), wood_floor),
    ("flat", "FLOOR5_4"): ("brick floor", (64, 64), brick_floor),
    ("wall", "METAL2"): ("metal panel control", (64, 128), metal_wall),
}


def height_map(kind, name, pixels):
    profile = PROFILES.get((kind, name))
    if profile is None:
        return None
    label, (width, height), draw = profile
    if pixels.shape != (height, width, 4) or not np.all(pixels[:, :, 3] == 255):
        return None
    tile = HeightTile(width, height)
    draw(tile)
    encoded = np.clip(128.0 + 255.0 * tile.values, 0.0, 255.0)
    return np.uint8(np.rint(encoded)), label
