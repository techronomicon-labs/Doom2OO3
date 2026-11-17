"""Structural height profiles for the validated stock Doom II wall set."""

import numpy as np

from structural_relief import HeightTile


def smoothstep(values, low, high):
    ramp = np.clip((values - low) / (high - low), 0.0, 1.0)
    return ramp * ramp * (3.0 - 2.0 * ramp)


def mean_line(values, axis, radius):
    total = values.copy()
    for distance in range(1, radius + 1):
        total += np.roll(values, distance, axis) + np.roll(values, -distance, axis)
    return total / (2 * radius + 1)


def blur(values, radius):
    return mean_line(mean_line(values, 0, radius), 1, radius)


def encode(height):
    bounded = np.clip(height, -0.48, 0.40)
    return np.uint8(np.rint(128.0 + bounded * 255.0))


class WallFeatures:
    def __init__(self, pixels, partner):
        rgb = pixels[:, :, :3].astype(np.float32) / 255.0
        self.changed = np.zeros(pixels.shape[:2], dtype=bool)
        if partner is not None and partner.shape == pixels.shape:
            # SW1/SW2 share geometry. Exclude changed actuator colours from
            # image cues, and read the same backing signal in both states.
            self.changed = np.any(pixels != partner, axis=2)
            rgb = 0.5 * (rgb + partner[:, :, :3].astype(np.float32) / 255.0)
        # Indexed deep red and blue have low luminance even in well-defined
        # brick joints or channels. Include intensity from the dominant band.
        luminance = rgb @ np.array((0.2126, 0.7152, 0.0722), dtype=np.float32)
        self.tone = 0.64 * luminance + 0.36 * rgb.max(axis=2)
        color_scale = rgb.sum(axis=2) + 0.10
        self.hue = np.stack(
            (rgb[:, :, 0] - rgb[:, :, 1], rgb[:, :, 2] - rgb[:, :, 1]), axis=2
        )
        self.hue /= color_scale[:, :, None]
        self.hue = blur(self.hue, 1)

    def seam(self, axis, shoulder, trace, ridge=False):
        along = 1 - axis
        center = mean_line(self.tone, along, trace)
        left = np.roll(center, shoulder, axis)
        right = np.roll(center, -shoulder, axis)
        polarity = -1 if ridge else 1
        contrast = np.minimum(polarity * (left - center), polarity * (right - center))
        # Require agreement from both shoulders and evidence along the joint.
        local = np.minimum(
            polarity * (np.roll(self.tone, shoulder, axis) - self.tone),
            polarity * (np.roll(self.tone, -shoulder, axis) - self.tone),
        )
        opposing_color = np.max(
            np.abs(np.roll(self.hue, shoulder, axis) - np.roll(self.hue, -shoulder, axis)),
            axis=2,
        )
        same_color = 1.0 - smoothstep(opposing_color, 0.025, 0.13)
        continuous = mean_line(smoothstep(local, 0.010, 0.055), along, trace)
        cut = smoothstep(contrast, 0.017, 0.135) * smoothstep(continuous, 0.22, 0.57)
        return mean_line(cut * same_color, axis, 1)

    def terrain(self):
        near = blur(self.tone, 1)
        middle = blur(near, 2)
        far = blur(middle, 4)
        sharp = near - middle
        broad = middle - far
        # Two scales must turn in the same direction. Paint gradients and
        # isolated palette noise contribute very little to the height.
        agree = smoothstep(np.sign(broad) * sharp, 0.005, 0.040)
        strength = smoothstep(np.abs(broad), 0.004, 0.065)
        hue_change = np.max(np.abs(self.hue - blur(self.hue, 3)), axis=2)
        field = np.sign(broad) * strength * agree
        return blur(field * (1.0 - smoothstep(hue_change, 0.035, 0.13)), 1)

    def vines(self):
        # The stock vine overlay is ochre and the backing is neutral gray.
        red, blue = self.hue[:, :, 0], self.hue[:, :, 1]
        wood = smoothstep(red, 0.025, 0.09) * smoothstep(-blue, 0.025, 0.09)
        wood *= 1.0 - smoothstep(red, 0.20, 0.32)
        wood *= ~self.changed
        return 0.40 * smoothstep(blur(wood, 2), 0.21, 0.77)


def mortar(features):
    courses = features.seam(axis=0, shoulder=3, trace=6)
    uprights = features.seam(axis=1, shoulder=3, trace=2)
    return -0.44 * np.maximum(courses, uprights) + 0.09 * features.terrain()


def planks(features, name):
    horizontal = name == "WOOD12"
    grain_axis = 0 if horizontal else 1
    seams = features.seam(axis=grain_axis, shoulder=3, trace=7)
    crossbars = features.seam(axis=1 - grain_axis, shoulder=3, trace=5)
    return -0.40 * np.maximum(seams, 0.67 * crossbars) + 0.055 * features.terrain()


def panels(features, rails=False):
    rims = np.maximum(
        features.seam(axis=0, shoulder=2, trace=6),
        features.seam(axis=1, shoulder=2, trace=6),
    )
    field = -0.34 * rims
    if rails:
        edges = np.maximum(
            features.seam(axis=0, shoulder=4, trace=3, ridge=True),
            features.seam(axis=1, shoulder=4, trace=3, ridge=True),
        )
        field += 0.22 * edges
    return field


def switch_panel(features, context, backing=None):
    visible = blur(blur((~features.changed).astype(np.float32), 1), 1)
    if backing is None:
        backing = panels(features) * smoothstep(visible, 0.59, 0.97)
    mask = context.get("switch_mask")
    if mask is not None and mask.any():
        tile = HeightTile(backing.shape[1], backing.shape[0])
        if mount_source_switch(tile, context):
            device = tile.values.reshape(backing.shape[0], 2, backing.shape[1], 2).mean(axis=(1, 3))
        else:
            device = 0.22 * blur(blur(mask.astype(np.float32), 1), 1)
    elif features.changed.any():
        y, x = np.where(features.changed)
        if (
            y.max() - y.min() > backing.shape[0] * 0.60
            or x.max() - x.min() > backing.shape[1] * 0.60
        ):
            return backing
        mask = np.zeros_like(backing)
        mask[max(0, y.min() - 4):y.max() + 5, max(0, x.min() - 4):x.max() + 5] = 1
        device = 0.22 * blur(blur(mask, 1), 1)
    else:
        return backing
    # The housing occupies these texels. Wall joints end at its perimeter.
    return np.where(mask > 0, device, backing)


PANEL_JOINTS = {
    "COMPSPAN": ((128, 32), (0,), (0, 64), 0.15),
    "METAL": ((128, 64), (16, 48), (), 0.14),
    "METAL5": ((128, 64), (0, 32), (0, 32, 64), 0.24),
    "SLADWALL": ((128, 64), (0, 32), (0, 32, 64, 96), 0.22),
}


def authored_panel(name, shape):
    layout = PANEL_JOINTS.get(name)
    if layout is not None and shape == layout[0]:
        _, vertical, horizontal, depth = layout
        tile = HeightTile(shape[1], shape[0])
        tile.joints(vertical=vertical, horizontal=horizontal, depth=depth, width=2.6)
        return encode(tile.values), "authored panel joints"
    if name in ("CRATE1", "CRATE2", "CRATE3") and shape == (128, 64):
        tile = HeightTile(64, 128)
        tile.joints(vertical=(0,), horizontal=(0, 64), depth=0.36, width=2.6)
        # Two crate faces share the same inset frame and carry different logos.
        for top in (0, 64):
            frame = (
                (6, top + 6), (58, top + 6), (58, top + 58), (6, top + 58), (6, top + 6)
            )
            tile.values -= 0.17 * tile.contour(frame, 0.3, 2.0)
        return encode(tile.values), "authored crate frames"
    if name == "CRATINY" and shape == (16, 64):
        tile = HeightTile(64, 16)
        tile.joints(vertical=(0, 16, 32, 48), horizontal=(0,), depth=0.28, width=1.8)
        return encode(tile.values), "authored small crate joints"
    if name == "METAL1" and shape == (128, 64):
        tile = HeightTile(64, 128)
        for y in range(0, 128, 32):
            rim = ((32, y), (48, y), (64, y + 16), (48, y + 32),
                   (32, y + 32), (16, y + 16), (32, y))
            joins = [(*first, *last) for first, last in zip(rim, rim[1:])]
            joins.append((0, y + 16, 16, y + 16))
            tile.joints(spans=joins, depth=0.28, width=2.9)
        return encode(tile.values), "authored hexagonal plate joints"
    if name in ("METAL6", "METAL7") and shape == (128, 64):
        tile = HeightTile(64, 128)
        # End the vertical seam at the lamp frame so its lens stays planar.
        start, end = (14, 128) if name == "METAL6" else (0, 112)
        frame = start if start else end
        seams = ((32, start, 32, 64), (32, 64, 32, end))
        tile.joints(horizontal=(0, frame, 64), spans=seams, depth=0.25, width=2.6)
        return encode(tile.values), "authored metal joints and light frame"
    if name == "SILVER2" and shape == (128, 64):
        tile = HeightTile(64, 128)
        for x in (13, 32.5, 51):
            u = np.abs(tile.wrapped_offset(tile.u, x, tile.width))
            for y in (33, 95):
                v = np.abs(tile.wrapped_offset(tile.v, y, tile.height))
                tile.values -= 0.27 * smoothstep(5.5 - u, 0, 2.5) * smoothstep(18 - v, 0, 2.5)
        return encode(tile.values), "authored recessed light housings"
    return None


def plate(tile, bounds, bevel):
    """A plane bounded by four smoothly beveled edges, in source texels."""
    x0, y0, x1, y1 = bounds
    u = (x1 - x0) * 0.5 - np.abs(tile.wrapped_offset(tile.u, (x0 + x1) * 0.5, tile.width))
    v = (y1 - y0) * 0.5 - np.abs(tile.wrapped_offset(tile.v, (y0 + y1) * 0.5, tile.height))
    return smoothstep(np.minimum(u, v), 0.0, bevel)


def recess(tile, bounds, inset=4, rim=0.15, depth=0.23):
    x0, y0, x1, y1 = bounds
    tile.values += rim * plate(tile, bounds, 2.0)
    interior = (x0 + inset, y0 + inset, x1 - inset, y1 - inset)
    tile.values -= (rim + depth) * plate(tile, interior, 2.7)


SWITCH_FACES = {
    # Patch-local indicator recesses and lever slots. Color changes between
    # switch states share these same physical surfaces.
    "SW1S": (32, (
        ((5, 4, 17, 14), -0.10, 1.2), ((5, 18, 17, 28), -0.10, 1.2),
        ((21, 7, 25, 26), -0.13, 1.2),
    )),
    "SW2S": (32, (
        ((5, 4, 27, 10), -0.093, 1.2), ((12, 16, 21, 24), 0.072, 1.15),
    )),
    "SW3S": (32, (
        ((7, 11, 26, 22), -0.084, 1.3), ((13, 6, 20, 26), -0.10, 1.3),
        ((8, 14, 25, 19), 0.12, 1.2),
    )),
    "SW4S": (24, (((7, 7, 18, 18), -0.13, 1.25),)),
}


def mount_switch(tile, x, y, style):
    size, fittings = SWITCH_FACES[style]
    face = 0.22 * plate(tile, (x, y, x + size, y + size), 2.1)
    for (left, top, right, bottom), depth, bevel in fittings:
        face += depth * plate(tile, (x + left, y + top, x + right, y + bottom), bevel)
    owned = (tile.u >= x) & (tile.u < x + size) & (tile.v >= y) & (tile.v < y + size)
    np.copyto(tile.values, face, where=owned)


def mount_source_switch(tile, context):
    patch = context.get("switch_patch")
    mask = context.get("switch_mask")
    if mask is None or not mask.any():
        return False
    assembly_origin = context.get("switch_assembly_origin")
    if assembly_origin is not None:
        x, y = assembly_origin
        face = 0.16 * plate(tile, (x - 8, y - 4, x + 24, y + 28), 1.7)
        face -= 0.13 * plate(tile, (x, y, x + 16, y + 24), 1.25)
        owned = np.repeat(np.repeat(mask > 0, 2, axis=0), 2, axis=1)
        np.copyto(tile.values, face, where=owned)
        return True
    if patch is None:
        return False
    x, y, name = patch
    style = name[:-1]
    if style in SWITCH_FACES and name[-1] in "01":
        size, _ = SWITCH_FACES[style]
        if (x < 0 or y < 0 or x + size > tile.width or y + size > tile.height
                or np.count_nonzero(mask) != size * size or not np.all(mask[y:y + size, x:x + size])):
            return False
        mount_switch(tile, x, y, style)
        return True
    face = sculpted_switch(tile, x, y, name)
    if face is None:
        return False
    owned = np.repeat(np.repeat(mask > 0, 2, axis=0), 2, axis=1)
    np.copyto(tile.values, face, where=owned)
    return True


def sculpted_switch(tile, x, y, name):
    if name in ("WARNA0", "WARNB0"):
        face = 0.21 * plate(tile, (x, y, x + 17, y + 23), 1.6)
        face -= 0.14 * plate(tile, (x + 5, y + 4, x + 12, y + 19), 1.2)
        return face
    if name in ("SW2_5", "SW2_6"):
        face = 0.14 * plate(tile, (x, y, x + 64, y + 50), 3.0)
        face += 0.20 * tile.mound(x + 32, y + 24, 27, 17)
        face -= 0.25 * tile.mound(x + 34, y + 25, 12, 4.5)
        return face
    if name in ("SW2_7", "SW2_8"):
        face = 0.11 * plate(tile, (x, y, x + 36, y + 38), 2.3)
        face += 0.26 * tile.mound(x + 18, y + 17, 13, 15)
        for eye in (x + 13, x + 23):
            face -= 0.18 * tile.mound(eye, y + 18, 3.3, 3.3)
        face -= 0.13 * tile.mound(x + 18, y + 27, 6, 2.5)
        return face
    if name in ("WALL42_1", "WALL42_5", "WALL42_6", "WALL47_3", "WALL47_4", "WALL47_5"):
        # These tall metal inserts cover the lower wall through the bottom
        # boundary. The sculpted head occupies only the upper part.
        face = 0.15 * plate(tile, (x, y, x + 40, tile.height + 2), 2.0)
        face += 0.24 * tile.mound(x + 20, y + 18, 14.5, 15.0)
        for eye in (x + 14, x + 26):
            face -= 0.20 * tile.mound(eye, y + 15, 4.3, 3.5)
        face -= 0.17 * tile.mound(x + 20, y + 24, 5.0, 3.5)
        return face
    return None


def bronze_courses(tile, name):
    cuts = {
        "BRONZE1": (0, 32, 56, 80, 104),
        "BRONZE2": (0, 32, 104),
        "BRONZE3": (0, 32, 74, 90, 104),
        "BRONZE4": (0, 32, 56, 80, 104, 118),
    }
    tile.joints(horizontal=cuts[name], depth=0.31, width=3.0)
    if name == "BRONZE2":
        trim = (
            (16, 32, 16, 74), (48, 32, 48, 74), (16, 90, 16, 104), (48, 90, 48, 104),
            (0, 74, 16, 74), (48, 74, 64, 74), (0, 90, 16, 90), (48, 90, 64, 90),
        )
        tile.joints(spans=trim, depth=0.21, width=2.3)
        tile.values += 0.10 * plate(tile, (17, 32, 48, 104), 3.1)
    # The lamp lenses stay on a flat backing below the final course.
    courses = cuts[name][1:] if name == "BRONZE4" else (*cuts[name][1:], 128)
    for top, bottom in zip(courses, courses[1:]):
        # Crown the stamped faces, leaving a lip at each joint. Rust
        # mottling belongs to the color map and adds no contour.
        half_height = (bottom - top) * 0.5
        distance = np.abs(tile.v - (top + bottom) * 0.5)
        tile.values += 0.13 * (1.0 - smoothstep(distance, 0.15 * half_height, half_height - 1))
    for left, right in ((4, 15), (19, 30), (36, 47), (51, 62)):
        tile.values += 0.24 * plate(tile, (left, 1, right, 24), 3.2)
        tile.values += 0.07 * plate(tile, (left, 25, right, 29), 1.6)
    if name == "BRONZE4":
        for x in (1, 33):
            recess(tile, (x, 117, x + 30, 127), inset=2, rim=0.07, depth=0.12)


def pipe_wall(tile, name):
    # Round the four pipe runs and raise their painted collars in the
    # circumferential direction. The thin rails carry the equipment plates.
    collars = (5, 14, 21, 41, 57, 66, 80, 94, 112, 121)
    collar = np.maximum.reduce([
        1.0 - smoothstep(np.abs(tile.wrapped_offset(tile.v, y, 128)), 0.4, 2.4)
        for y in collars
    ])
    for x in (20.5, 116.5, 136.0, 149.0):
        across = np.abs(tile.wrapped_offset(tile.u, x, 256))
        barrel = 1.0 - smoothstep(across, 0.6, 5.7)
        tile.values += (0.30 + 0.06 * collar) * barrel

    for x in (9, 34, 69, 87, 105, 164, 212, 229, 246):
        across = np.abs(tile.wrapped_offset(tile.u, x, 256))
        tile.values += 0.13 * (1.0 - smoothstep(across, 0.6, 2.9))
    for bounds in ((39, 32, 66, 49), (39, 50, 69, 64), (38, 66, 76, 81),
                   (168, 7, 204, 64), (169, 65, 201, 90)):
        recess(tile, bounds, inset=3.0, rim=0.11, depth=0.13)

    if name == "PIPE4":
        # PIPE4 shares the undamaged PIPE2 hardware, with its own painted punctures.
        for x, y in ((8, 72), (6, 88), (77, 59), (43, 90),
                     (95, 84), (178, 65), (194, 98), (239, 88)):
            tile.values -= 0.26 * tile.mound(x, y, 4.0, 4.5)


def hardware_runs(tile, runs):
    ridges = np.zeros_like(tile.values)
    for points, depth, width in runs:
        np.maximum(ridges, depth * tile.contour(points, 0.25, width), out=ridges)
    tile.values += ridges


def exit_door(tile):
    tile.joints(vertical=(0, 64, 112), horizontal=(0, 64), depth=0.20, width=2.0)
    cable = ((14, 17), (9, 22), (5, 32), (5, 44), (9, 51), (17, 56))
    runs = [
        (cable, 0.20, 3.7),
        (tuple((64 - x, y) for x, y in cable), 0.20, 3.7),
        (((15, 4), (15, 16), (22, 22), (40, 22), (49, 16), (49, 4)), 0.16, 2.8),
    ]
    runs.extend((((x, 0), (x, 72)), 0.17, radius) for x, radius in ((69, 2.5), (82, 4), (91, 4), (106, 2.5)))
    hardware_runs(tile, runs)
    recess(tile, (20, 30, 45, 52), inset=2.8, rim=0.11, depth=0.12)
    for x in (76, 88):
        for y in (31, 39):
            recess(tile, (x, y, x + 11, y + 8), inset=1.3, rim=0.09, depth=0.13)
    recess(tile, (114, 1, 128, 71), inset=2.3, rim=0.16, depth=0.06)


def tech_wall(tile, name):
    if name == "TEKWALL6":
        tile.joints(horizontal=(0, 32, 105), depth=0.25, width=2.4)
        for x in range(0, 256, 16):
            tile.values += 0.20 * plate(tile, (x + 4, 3, x + 14, 24), 3.0)
            tile.values -= 0.13 * plate(tile, (x + 5, 25, x + 13, 31), 1.7)
        tile.values -= 0.11 * plate(tile, (0, 33, 256, 104), 1.6)
        rails = (7, 28, 36, 49, 68, 84, 113, 121, 150, 165, 201, 221, 229)
        hardware_runs(tile, [(((x, 36), (x, 103)), 0.18, 2.6) for x in rails])
        for bounds in ((14, 43, 28, 77), (91, 75, 106, 103), (128, 42, 148, 76),
                       (169, 37, 194, 75), (238, 37, 255, 73)):
            recess(tile, bounds, inset=2.4, rim=0.12, depth=0.13)
        return

    # Follow the larger conduit loops. The dense chips and streaks remain
    # material detail over the equipment plate.
    tile.joints(vertical=(0,), horizontal=(0,), depth=0.14, width=1.9)
    for bounds in ((6, 77, 28, 114), (43, 15, 56, 58), (57, 61, 75, 94),
                   (69, 5, 81, 44), (91, 57, 121, 86), (101, 16, 112, 49)):
        recess(tile, bounds, inset=2.5, rim=0.10, depth=0.14)
    hardware_runs(tile, (
        (((23, 2), (23, 71), (19, 75), (2, 75)), 0.22, 2.9),
        (((36, 0), (36, 77), (40, 85), (40, 122)), 0.16, 2.3),
        (((53, 3), (46, 10), (42, 16), (42, 48), (49, 57)), 0.16, 2.5),
        (((61, 0), (61, 49), (58, 55), (58, 121)), 0.22, 2.6),
        (((83, 3), (83, 39), (80, 46), (75, 52)), 0.17, 2.4),
        (((96, 2), (96, 38), (90, 46), (90, 81), (84, 91), (84, 125)), 0.20, 2.6),
        (((120, 2), (117, 8), (117, 39), (126, 49), (126, 66), (116, 79)), 0.18, 2.6),
        (((126, 91), (116, 102), (116, 126)), 0.18, 2.4),
    ))


def horizontal_pipe_wall(tile, name):
    # The orange/brown and green pipe paint follows the same round section.
    tile.values.fill(-0.13)
    collar = np.zeros_like(tile.u)
    if name == "PIPEWAL1":
        for x in (18.5, 44.5):
            distance = np.abs(tile.wrapped_offset(tile.u, x, tile.width))
            collar += 0.10 * (1.0 - smoothstep(distance, 2.0, 3.5))
    for y in (26.4, 37.6, 48.6, 59.7, 82.5, 93.6, 104.7, 115.6):
        across = tile.wrapped_offset(tile.v, y, tile.height)
        barrel = np.maximum(0.0, 1.0 - (across / 4.55) ** 2) ** 1.5
        tile.values += (0.37 + collar) * barrel

    if name == "PIPEWAL1":
        # A vertical manifold interrupts the pipes. Its indicator and access
        # plates have their own plane across the entire metal housing.
        owned = (tile.u >= 22) & (tile.u < 41)
        face = 0.04 + 0.12 * plate(tile, (22, 0, 41, 128), 2.2)
        for y in (0, 56):
            face += 0.12 * plate(tile, (28, y + 31, 35, y + 44), 1.8)
            face -= 0.09 * plate(tile, (25, y + 44, 39, y + 51), 1.6)
        for bounds in ((24, 9, 39, 21), (25, 60, 38, 64), (24, 72, 39, 81),
                       (25, 112, 38, 121)):
            face -= 0.13 * plate(tile, bounds, 1.45)
        np.copyto(tile.values, face, where=owned)


def stamped_base_wall(tile, name):
    for x in range(0, tile.width, 32):
        for top, bottom in ((1, 11), (14, 43), (46, 56), (58, 67),
                            (70, 111), (114, 127)):
            tile.values += 0.21 * plate(tile, (x + 1, top, x + 31, bottom), 3.4)
    if name == "STARTAN3":
        # The bright central columns and rust streaks are painted into the
        # panels. Only the bolted divider strips stand proud of the faces.
        for x in (32, 96):
            distance = np.abs(tile.wrapped_offset(tile.u, x, tile.width))
            tile.values += 0.12 * (1.0 - smoothstep(distance, 0.6, 2.2))


def equipment_wall(tile, name):
    if name in ("COMPSTA1", "COMPSTA2"):
        # Recess each display as a flat pane, including the fine graphics and
        # baked glow. These graphics must not deform under the flashlight.
        left_edge = 93 if name == "COMPSTA1" else 91
        top_edge = 21 if name == "COMPSTA1" else 22
        for bounds in ((5, 4, 53, 44), (56, 4, 88, 44),
                       (left_edge, 4, 124, top_edge), (left_edge, 27, 124, 44)):
            recess(tile, bounds, inset=1.5, rim=0.10, depth=0.15)
        return

    tile.joints(vertical=(0, 16, 57), horizontal=(0, 40, 88), depth=0.19, width=2.25)
    for bounds in ((17, 8, 35, 36), (40, 5, 55, 37), (18, 90, 34, 119), (40, 91, 55, 121),
                   (12, 47, 31, 84), (36, 43, 57, 85)):
        recess(tile, bounds, inset=2.6, rim=0.12, depth=0.18)
    for x in (15, 40):
        tile.values -= 0.16 * plate(tile, (x, 58, x + 13, 63), 1.2)


def space_door(tile):
    tile.joints(vertical=(1, 63), horizontal=(0, 15, 111), depth=0.23, width=2.3)
    recess(tile, (8, 34, 55, 98), inset=2.5, rim=0.13, depth=0.19)
    for x in (13, 41):
        for y in (54, 78):
            tile.values += 0.19 * plate(tile, (x, y, x + 13, y + 6), 1.8)
    tile.values += 0.21 * plate(tile, (26, 40, 39, 96), 3.2)
    # The lens and hazard stripes sit inside separate stamped recesses.
    recess(tile, (16, 14, 49, 20), inset=1.15, rim=0.10, depth=0.10)
    recess(tile, (13, 115, 51, 125), inset=1.8, rim=0.11, depth=0.14)
    for x, low, high in ((39, 2, 13), (8, 101, 111), (50, 101, 111)):
        for y in range(low, high, 4):
            tile.values -= 0.13 * plate(tile, (x, y, x + 8, y + 2.7), 1.2)


def metal_service_wall(tile, name):
    if name == "METAL3":
        tile.joints(vertical=(0, 32), horizontal=(0, 63), spans=((32, 29, 64, 29),),
                    depth=0.24, width=2.15)
        for y in (3, 15, 26, 38, 47, 60, 67, 79, 90, 102, 115, 124):
            for x in (5, 27, 38, 59):
                tile.values -= 0.15 * tile.mound(x, y, 1.8, 1.8)
        # The warning graphic is painted on a flat tag above three sockets.
        tile.values += 0.09 * plate(tile, (43, 38, 54, 55), 1.05)
        for y in (73, 87, 98):
            recess(tile, (43, y, 54, y + 7), inset=0.9, rim=0.08, depth=0.15)
        return

    tile.joints(vertical=(0, 27, 52, 57), depth=0.22, width=2.1)
    hardware_runs(tile, (
        (((13, 0), (13, 25), (19, 31), (27, 31)), 0.19, 2.4),
        (((17, 39), (17, 128)), 0.18, 2.7),
        (((28, 10), (51, 10)), 0.20, 2.8),
        (((28, 86), (51, 86)), 0.22, 2.8),
        (((46, 88), (46, 101), (49, 101), (49, 128)), 0.18, 2.5),
    ))
    for top, bottom in ((13, 62), (64, 80), (90, 127)):
        recess(tile, (30, top, 51, bottom), inset=2, rim=0.095, depth=0.13)


MASKED_STEEL = frozenset((
    "MIDGRATE", "MIDBARS1", "MIDBRN1", "MIDSPACE", "MIDBRONZ",
    "BRNSMAL2", "BRNSMALL", "BRNSMALC", "BRNSMALR",
))


def masked_wall_field(name, pixels):
    """Normal-map bevels following the visible stock bars and cutout edges."""
    if name not in MASKED_STEEL:
        return None
    alpha = pixels[:, :, 3] > 127
    if alpha.all() or not alpha.any():
        return None
    core = np.repeat(np.repeat(alpha, 2, axis=0), 2, axis=1)
    field = 0.085 * core.astype(np.float32)
    for rise in (0.073, 0.055, 0.035, 0.02):
        # Use the actual patch silhouette, including diagonals and apertures.
        core = core & np.roll(core, 1, 0) & np.roll(core, -1, 0) & np.roll(core, 1, 1) & np.roll(core, -1, 1)
        field += rise * core
    return blur(field, 1)


def masked_hardware(tile, name):
    if name == "MIDBARS3":
        for y in (0, 64):
            tile.values += 0.14 * plate(tile, (0, y, 64, y + 8), 2.5)
        hardware_runs(tile, [(((x, 5), (x, 67)), 0.23, 3.1) for x in (8.5, 24.5, 40.5, 56.5)])
    else:
        tile.values += 0.13 * plate(tile, (0, 0, 64, 64), 3)
        hardware_runs(tile, (
            (((38, 13), (5, 46)), 0.19, 5.8),
            (((57, 22), (25, 54)), 0.24, 6.2),
        ))


def formed_hardware(name, shape):
    """Source-registered profiles for manufactured parts with planar faces."""
    h, w = shape
    if name in ("PIPEWAL1", "PIPEWAL2") and shape == (128, 64):
        tile = HeightTile(w, h)
        horizontal_pipe_wall(tile, name)
        return tile.values, "rounded pipe banks and independently formed controls"
    if (name, shape) in (("STARTAN3", (128, 128)), ("STARG1", (128, 64))):
        tile = HeightTile(w, h)
        stamped_base_wall(tile, name)
        return tile.values, "pressed wall panels and raised divider strips"
    if name == "SUPPORT3" and shape == (128, 64):
        tile = HeightTile(w, h)
        tile.joints(vertical=(0, 23.5, 40.5), depth=0.26, width=2.1)
        for x in (8.5, 16.5, 28.5, 36.5, 48.5, 56.5):
            for y in range(4, 128, 8):
                tile.values -= 0.27 * tile.mound(x, y, 2.1, 2.0)
        return tile.values, "perforated steel reinforcement rails"
    if (name, shape) in (("COMPSTA1", (128, 128)), ("COMPSTA2", (128, 128)), ("SPACEW2", (128, 64))):
        tile = HeightTile(w, h)
        equipment_wall(tile, name)
        return tile.values, "beveled equipment housings with planar displays"
    if name == "SPCDOOR2" and shape == (128, 64):
        tile = HeightTile(w, h)
        space_door(tile)
        return tile.values, "stamped door hardware and inset lens"
    if name in ("METAL3", "METAL4") and shape == (128, 64):
        tile = HeightTile(w, h)
        metal_service_wall(tile, name)
        return tile.values, "formed service panels with separate electrical fittings"
    if name in ("BRONZE1", "BRONZE2", "BRONZE3", "BRONZE4") and shape == (128, 64):
        tile = HeightTile(w, h)
        bronze_courses(tile, name)
        return tile.values, "crowned bronze plates and stamped ribs"
    if name in ("TEKGREN1", "TEKGREN2", "TEKGREN3", "TEKGREN4", "TEKGREN5") and shape == (128, 64):
        tile = HeightTile(w, h)
        if name == "TEKGREN4":
            rails = ((16, 0, 16, 95), (29, 0, 29, 95), (51, 0, 51, 95),
                     (29, 9, 51, 9), (29, 78, 51, 78), (29, 87, 51, 87))
            tile.joints(horizontal=(0, 96), spans=rails, depth=0.16, width=2.0)
        else:
            courses = (0, 24, 48, 64, 88, 96) if name in ("TEKGREN2", "TEKGREN5") else (0, 24, 64, 88, 96)
            tile.joints(vertical=(0,), horizontal=courses, depth=0.17, width=1.8)
            if name == "TEKGREN5":
                # The glass and all its yellow stripes share one plane.
                recess(tile, (2, 2, 62, 14), inset=2, rim=0.065, depth=0.07)
        return tile.values, "painted steel trays, folded seams and planar lamp glass"
    if name in ("PIPE2", "PIPE4") and shape == (128, 256):
        tile = HeightTile(w, h)
        pipe_wall(tile, name)
        return tile.values, "rounded pipe runs, raised collars and recessed faceplates"
    if name == "DOORTRAK" and shape == (128, 8):
        tile = HeightTile(w, h)
        tile.joints(vertical=(1.5, 5.5), depth=0.14, width=1.25)
        return tile.values, "straight pressed channels in dry guide rail"
    if name == "BIGDOOR1" and shape == (96, 128):
        tile = HeightTile(w, h)
        # Logo and painted stripe sit on the main stamped door panel.
        tile.joints(spans=((25, 8, 106, 8), (25, 72, 106, 72), (25, 89, 106, 89),
                           (25, 8, 25, 24), (25, 64, 25, 89), (106, 8, 106, 89)),
                    depth=0.19, width=2.2)
        for y in (24, 40, 56):
            tile.values += 0.13 * plate(tile, (95, y, 113, y + 8), 1.8)
        return tile.values, "stamped steel surround and planar UAC logo"
    if name in ("BIGDOOR2", "BIGDOOR3", "BIGDOOR4") and shape == (128, 128):
        tile = HeightTile(w, h)
        tile.joints(vertical=(0,), horizontal=(0, 15, 114), depth=0.18, width=2.1)
        for bounds in ((5, 17, 62, 112), (66, 17, 123, 112)):
            recess(tile, bounds, inset=3.5, rim=0.09, depth=0.13)
        tile.joints(spans=((64, 15, 64, 114),), depth=0.19, width=2.0)
        return tile.values, "stamped door frame, guide bands and planar warning paint"
    if name == "DOOR3" and shape == (72, 64):
        tile = HeightTile(w, h)
        tile.joints(horizontal=(0, 56, 64), depth=0.16, width=1.9)
        recess(tile, (7, 8, 57, 58), inset=3, rim=0.075, depth=0.10)
        tile.values += 0.12 * plate(tile, (46, 32, 61, 49), 1.8)
        return tile.values, "straight door folds and separate inset latch"
    if name == "SUPPORT2" and shape == (128, 64):
        tile = HeightTile(w, h)
        for x in (12, 31, 52):
            distance = np.abs(tile.wrapped_offset(tile.u, x, w))
            tile.values += 0.12 * (1.0 - smoothstep(distance, 2.7, 5.0))
            for y in range(8, 128, 16):
                tile.values -= 0.19 * plate(tile, (x - 4, y, x + 4, y + 3.5), 1.4)
        return tile.values, "straight reinforcement ribs and mounting slots"
    if name == "EXITDOOR" and shape == (72, 128):
        tile = HeightTile(w, h)
        exit_door(tile)
        return tile.values, "rounded exit-door cables and inset indicators"
    if name == "EXITSIGN" and shape == (16, 64):
        tile = HeightTile(w, h)
        tile.values += 0.13 * plate(tile, (0.5, 0.5, 32, 15.5), 1.5)
        tile.values -= 0.21 * plate(tile, (1.75, 1.75, 31.1, 14.25), 1.2)
        for x in (33, 41, 49, 57):
            tile.values -= 0.14 * plate(tile, (x, 2, x + 5.5, 14), 1.4)
        return tile.values, "beveled exit-sign casing and flat lettering"
    if name == "LITE5" and shape == (128, 16):
        tile = HeightTile(w, h)
        for y in range(0, h, 8):
            tile.values += 0.11 * plate(tile, (0.5, y, 15.5, y + 8), 1.4)
            tile.values -= 0.15 * plate(tile, (1.8, y + 0.7, 14.2, y + 7.2), 1.35)
        return tile.values, "repeated lamp bezels and level lenses"
    if (name, shape) in (("TEKWALL4", (128, 128)), ("TEKWALL6", (128, 256))):
        tile = HeightTile(w, h)
        tech_wall(tile, name)
        return tile.values, "raised conduit and inset circuit housings"
    if (name, shape) in (("MIDBARS3", (72, 64)), ("BRNSMAL1", (64, 64))):
        tile = HeightTile(w, h)
        masked_hardware(tile, name)
        return tile.values, "beveled frame and raised bars"
    if (name, shape) in (("BROWN96", (128, 128)), ("BROWNGRN", (128, 64))):
        tile = HeightTile(w, h)
        brown_panel(tile)
        return tile.values, "folded brown wall faces and raised brackets"
    if name == "BROWN1" and shape == (128, 128):
        tile = HeightTile(w, h)
        tile.joints(horizontal=(18, 74), spans=[
            (x, top, x, bottom)
            for x in range(0, w, 16)
            for top, bottom in ((21, 70), (77, 126))
        ], depth=0.26, width=2.4)
        for y in (19, 75):
            tile.values += 0.10 * plate(tile, (0, y, w, y + 6), 2.0)
        return tile.values, "pressed wall panels and folded horizontal trim"
    if name in ("SPACEW3", "COMPWERD", "SW1COMP", "SW2COMP") and shape == (128, 64):
        tile = HeightTile(w, h)
        equipment_recesses(tile, name)
        return tile.values, "separate equipment plates, recessed housings and level display faces"
    if name == "SPACEW4" and shape == (128, 64):
        tile = HeightTile(w, h)
        tile.joints(vertical=(0, 32), horizontal=(0, 32, 64, 96), depth=0.30, width=2.5)
        for x in (0, 32):
            for y in range(0, h, 32):
                tile.values += 0.09 * plate(tile, (x + 1, y + 1, x + 31, y + 31), 2.3)
                for side in (x + 4.5, x + 28.5):
                    for bolt in (4.5, 11.5, 19.5, 27.5):
                        tile.values -= 0.18 * tile.mound(side, y + bolt, 2.0, 2.3)
        return tile.values, "beveled plate joins and recessed fasteners"
    return None


def modular_wall(tile, name):
    if name in ("MODWALL1", "MODWALL2"):
        # The two dark masonry fields sit between coarse gray trim bands.
        for center in (0, 64):
            across = np.abs(tile.wrapped_offset(tile.v, center, 128))
            tile.values += 0.35 * (1.0 - smoothstep(across, 5.0, 9.0))
        if name == "MODWALL2":
            for y in (8, 72):
                tile.values -= 0.30 * plate(tile, (8, y, 56, y + 48), 3.0)
        return
    columns = ((1, 63),) if name == "MODWALL3" else ((1, 31), (33, 63))
    for y in (0, 64):
        for left, right in columns:
            recess(tile, (left, y + 1, right, y + 63), inset=7, depth=0.30)


def cabinet(tile):
    # The main openings sit behind the console plate. Keep the screen
    # graphics and warning decal on their support planes.
    tile.joints(
        horizontal=(0, 63), spans=((96, 0, 96, 63), (160, 0, 160, 63)),
        depth=0.29, width=2.4,
    )
    for bounds in ((34, 4, 90, 58), (3, 69, 59, 122), (193, 4, 247, 37)):
        recess(tile, bounds, inset=4, depth=0.32)
    vents = (
        (6, 8, 25, 26), (6, 39, 25, 57), (166, 8, 185, 26),
        (166, 39, 185, 57), (85, 78, 107, 96), (85, 98, 107, 116),
    )
    for bounds in vents:
        tile.values -= 0.24 * plate(tile, bounds, 2.6)
    for y in (76, 92):
        tile.values -= 0.24 * plate(tile, (130, y, 254, y + 15), 2.8)


def carved_badge(tile, name):
    # Rounded head, brows, eye sockets and mouth share a consistent relief.
    wood = name == "WOODGARG"
    center_y = {"WOODGARG": 84, "GSTLION": 35, "GSTGARG": 36, "GSTSATYR": 42}[name]
    if wood:
        tile.joints(horizontal=(0, 6, 127), depth=0.32, width=2.8)
        for x in (14, 50):
            tile.values += 0.23 * tile.mound(x, 73, 9.5, 12.5)
    else:
        tile.joints(
            horizontal=(80, 104), spans=((48, 80, 48, 104), (16, 104, 16, 128)),
            depth=0.38, width=3.0,
        )
    tile.values += 0.36 * tile.mound(32, center_y, 17, 23)
    tile.values += 0.22 * tile.mound(32, center_y + 2, 5.5, 9.0)
    for x in (24, 40):
        tile.values += 0.15 * tile.mound(x, center_y - 8, 8, 4.5)
        tile.values -= 0.31 * tile.mound(x, center_y - 2, 7, 4.5)
    tile.values -= 0.33 * tile.mound(32, center_y + 11, 10, 6.5)


def brown_trim(tile):
    # WALL62's repeated upper bracket ends at y=23, above a dark channel
    # and the join at y=32. Streaks below that join are surface coloration.
    tile.joints(horizontal=(0, 32), depth=0.33, width=2.6)
    for x in range(0, tile.width, 16):
        tile.values += 0.24 * plate(tile, (x + 4, 4, x + 14, 23), 3.2)
        tile.values -= 0.20 * plate(tile, (x + 5, 23, x + 12, 31), 2.3)


def brown_panel(tile):
    tile.joints(spans=[(x, 35, x, 127) for x in range(0, tile.width, 16)],
                depth=0.17, width=2.5)
    brown_trim(tile)


def equipment_recesses(tile, name):
    tile.joints(vertical=(0,), horizontal=(0, 64), depth=0.22, width=2.0)
    if name.startswith(("SW1", "SW2")):
        tile.joints(spans=((32, 64, 32, 128),), depth=0.14, width=1.5)
        recess(tile, (8, 6, 57, 57), inset=2.1, rim=0.11, depth=0.19)
        mount_switch(tile, 16, 72, "SW2S")
        return
    columns = ((4, 27), (36, 59)) if name == "SPACEW3" else ((7, 57),)
    windows = ((6, 23), (27, 44)) if name == "SPACEW3" else ((6, 57),)
    for y in (0, 64):
        for left, right in columns:
            for top, bottom in windows:
                recess(tile, (left, y + top, right, y + bottom), inset=2.2, rim=0.12, depth=0.23)
        if name == "SPACEW3":
            for x in (9, 31, 52):
                for slot in (56, 59, 62):
                    tile.values -= 0.12 * plate(tile, (x - 3, y + slot, x + 3, y + slot + 1.6), 0.7)


def cement9(tile):
    # Alternating rows are staggered by one source texel and the cuts
    # follow the dark joints between blocks, regardless of their paint.
    rows = (0, 21, 42, 63, 84, 105, 128)
    starts = (-0.5, 0.5) * 3
    seams = [(x, top, x, bottom)
             for start, top, bottom in zip(starts, rows, rows[1:])
             for x in np.arange(start, start + 64, 8)]
    tile.joints(horizontal=rows[:-1], spans=seams, depth=0.40, width=1.5)
    for start, top, bottom in zip(starts, rows, rows[1:]):
        for x in np.arange(start, start + 64, 8):
            tile.values += 0.10 * plate(tile, (x + 0.8, top + 0.8, x + 7.3, bottom - 1), 2.0)


def stone7(tile):
    cracks = (
        ((0, 29), (12, 24), (18, 18), (24, 20), (34, 18), (42, 15), (47, 20),
         (43, 25), (45, 32), (52, 36), (60, 47), (63, 49)),
        ((0, 49), (10, 46), (17, 40), (25, 43), (33, 45), (40, 42), (45, 34)),
        ((22, 43), (28, 48), (31, 53), (39, 57), (48, 59), (53, 57), (63, 53)),
        ((0, 63), (12, 68), (21, 70), (28, 75), (34, 80), (44, 74), (54, 77), (63, 74)),
        ((3, 92), (9, 87), (20, 87), (29, 83), (38, 90), (45, 92), (56, 88), (63, 88)),
        ((0, 111), (8, 106), (16, 102), (24, 99), (32, 102), (40, 101), (46, 105),
         (49, 112), (54, 119), (63, 111)),
        ((28, 128), (33, 119), (39, 112), (45, 108), (46, 103)),
    )
    for points in cracks:
        np.minimum(tile.values, -0.35 * tile.contour(points, 0.2, 2.35), out=tile.values)
    for x, y, width, height in ((47, 21, 4.5, 5), (45, 31, 3.8, 3.1), (24, 42, 5, 3),
                                (27, 80, 8, 5), (43, 102, 4.6, 3.1), (53, 120, 3.3, 3)):
        np.minimum(tile.values, -0.46 * tile.mound(x, y, width, height), out=tile.values)


def fractured_stone(tile, name):
    # STONE5 is the damaged variant of STONE4; their block boundaries align.
    cracks = (
        (((0, 24), (9, 21), (16, 18), (25, 19), (31, 22), (42, 30), (47, 31),
          (54, 37), (63, 48)), 0.34),
        (((19, 18), (14, 13), (10, 10), (10, 4)), 0.24),
        (((26, 19), (33, 15), (41, 13), (43, 10), (42, 1)), 0.30),
        (((42, 11), (50, 18), (55, 21), (64, 25)), 0.29),
        (((0, 49), (8, 47), (17, 45), (25, 46), (30, 45), (39, 38), (42, 30)), 0.34),
        (((12, 36), (16, 42), (20, 44)), 0.25),
        (((28, 46), (36, 51), (44, 52), (52, 58)), 0.30),
        (((0, 65), (11, 65), (18, 67), (26, 71)), 0.27),
        (((0, 81), (11, 78), (23, 78), (32, 74), (43, 67), (53, 58), (64, 53)), 0.36),
        (((44, 73), (52, 76), (64, 72)), 0.24),
        (((0, 94), (11, 89), (20, 89), (30, 93), (37, 100), (47, 102),
          (56, 99), (64, 98)), 0.34),
        (((0, 122), (13, 113), (24, 107), (37, 101), (43, 108), (49, 119),
          (51, 125), (63, 122)), 0.33),
    )
    for points, depth in cracks:
        np.minimum(tile.values, -depth * tile.contour(points, 0.20, 2.35), out=tile.values)
    if name == "STONE5":
        for x, y, rx, ry in ((46, 21, 5, 6), (18, 43, 6, 4), (32, 48, 8, 4),
                             (26, 80, 9, 5.5), (43, 103, 6.5, 4), (51, 118, 3, 6)):
            np.minimum(tile.values, -0.47 * tile.mound(x, y, rx, ry), out=tile.values)


def reviewed_panel(name, shape):
    height, width = shape
    if name in ("STONE4", "STONE5") and shape == (128, 64):
        tile = HeightTile(width, height)
        fractured_stone(tile, name)
        return tile.values, "traced stone fractures and damaged joints"
    if name == "BIGBRIK1" and shape == (128, 64):
        tile = HeightTile(width, height)
        rows = (0, 32, 64, 96, 128)
        uprights = [(x, top, x, bottom) for x, top, bottom in
                    zip((6, 55.5, 6, 55.5), rows, rows[1:])]
        tile.joints(horizontal=rows[:-1], spans=uprights, depth=0.40, width=2.85)
        return tile.values, "staggered brick faces and recessed mortar"
    if name in ("CEMENT9", "STONE7") and shape == (128, 64):
        tile = HeightTile(width, height)
        if name == "CEMENT9":
            cement9(tile)
            return tile.values, "staggered cement block faces and recessed mortar"
        stone7(tile)
        return tile.values, "traced fractures and deep pits in the exposed stone"
    if name in ("BLAKWAL1", "BLAKWAL2") and shape == (128, 64):
        tile = HeightTile(width, height)
        # Both have the same frame; BLAKWAL2 is the brighter frame variant.
        u = np.abs(tile.wrapped_offset(tile.u, 0, width))
        v = np.abs(tile.wrapped_offset(tile.v, 0, 64))
        tile.values += 0.27 * (1.0 - smoothstep(np.minimum(u, v), 0.6, 2.8))
        return tile.values, "raised perimeter and center rails on flat black inserts"
    if name == "SHAWN3" and shape == (72, 64):
        tile = HeightTile(width, height)
        tile.joints(vertical=(2, 62), horizontal=(2, 36, 70), depth=0.19, width=2.0)
        return tile.values, "pressed perimeter and center joins around planar logos"
    if name in ("DOORBLU", "DOORRED", "DOORYEL") and shape == (128, 8):
        tile = HeightTile(width, height)
        # Eight identical mechanical housings. Colour marks the key only.
        for y in range(0, height, 16):
            tile.values += 0.22 * plate(tile, (0.6, y, 7.4, y + 16), 0.9)
            tile.values -= 0.38 * plate(tile, (2, y + 3, 6, y + 14), 1.0)
        return tile.values, "recessed key indicator lenses in repeatable metal frames"
    if name in ("DOORBLU2", "DOORRED2", "DOORYEL2") and shape == (128, 16):
        tile = HeightTile(width, height)
        for y in range(0, 120, 24):
            tile.values += 0.11 * plate(tile, (0, y, 16, y + 3.5), 1.1)
            tile.values += 0.23 * tile.mound(8, y + 11, 7, 8.6)
            tile.values -= 0.18 * tile.mound(5, y + 15, 2.2, 2.4)
            tile.values -= 0.18 * tile.mound(11, y + 15, 2.2, 2.4)
            tile.values -= 0.10 * tile.mound(8, y + 20, 4, 1.65)
        return tile.values, "sculpted skull key indicators and separate metal rails"
    if (name, shape) in (("STEP2", (16, 32)), ("STEP3", (16, 32)),
                          ("STEP6", (16, 32)), ("STEPTOP", (16, 128))):
        tile = HeightTile(width, height)
        joins = {"STEP2": (3,), "STEP3": (2, 10), "STEP6": (8,), "STEPTOP": (4, 14)}
        tile.joints(horizontal=joins[name], depth=0.25, width=2.1)
        if name in ("STEP2", "STEP6"):
            y = 5 if name == "STEP2" else 2
            tile.values += 0.14 * plate(tile, (0, y, width, y + 4), 1.5)
        return tile.values, "source-aligned step nose and riser bevel"
    if (name, shape) in (("STEP1", (16, 32)), ("STEP4", (16, 32)),
                          ("STEP5", (16, 32)), ("STEPLAD1", (16, 64))):
        tile = HeightTile(width, height)
        if name == "STEP1":
            tile.joints(horizontal=(0, 8), depth=0.16, width=1.7)
            tile.values += 0.18 * plate(tile, (0, 0, 32, 3.5), 1.1)
        elif name == "STEP4":
            tile.joints(horizontal=(0, 5.5), depth=0.18, width=1.55)
            tile.values += 0.11 * plate(tile, (0, 1.0, 32, 5), 1.35)
        elif name == "STEP5":
            tile.joints(horizontal=(0, 8), depth=0.23, width=1.6)
            for y in (1, 9):
                for x in (0, 8, 16, 24):
                    tile.values += 0.14 * plate(tile, (x + 0.8, y, x + 7.2, y + 5.5), 1.6)
        else:
            recess(tile, (4, 5, 60, 15), inset=1.4, rim=0.10, depth=0.28)
        return tile.values, "formed riser trim and recessed fittings"
    return None


def mineral_finish(features):
    # Resolve broad clusters in cast or worn surfaces. Long gradients and
    # isolated palette dots stay in the albedo/roughness channels.
    near = blur(features.tone, 1)
    granules = near - blur(near, 3)
    return 0.14 * np.sign(granules) * smoothstep(np.abs(granules), 0.003, 0.028)


def authored_detail(name, shape):
    height, width = shape
    if name in ("MODWALL1", "MODWALL2", "MODWALL3", "MODWALL4") and shape == (128, 64):
        tile = HeightTile(width, height)
        modular_wall(tile, name)
        return encode(tile.values), "authored modular wall rails and bays"
    if name == "COMPTALL" and shape == (128, 256):
        tile = HeightTile(width, height)
        cabinet(tile)
        return encode(tile.values), "authored computer housings and vents"
    if name in ("PANEL3", "PANEL7", "WOOD3"):
        frames = {
            "PANEL3": ((128, 64), [(4, y, 60, y + 33) for y in (4, 45, 92)]),
            "PANEL7": ((128, 64), [(4, 77, 60, 117)]),
            "WOOD3": (
                (128, 256),
                [(x + 1, y + 1, x + 63, y + 63)
                 for x in range(0, 256, 64) for y in (0, 64)],
            ),
        }
        expected, bounds = frames[name]
        if shape == expected:
            tile = HeightTile(width, height)
            for frame in bounds:
                recess(tile, frame, depth=0.27)
            return encode(tile.values), "authored beveled wood frames and insets"
    if name in ("GSTLION", "GSTGARG", "GSTSATYR", "WOODGARG") and shape == (128, 64):
        tile = HeightTile(width, height)
        carved_badge(tile, name)
        return encode(tile.values), "authored raised face and recessed features"
    if name in ("SKINMET1", "SKINMET2") and shape == (128, 256):
        tile = HeightTile(width, height)
        for x0, x1 in ((6, 74), (86, 161), (174, 252)):
            recess(tile, (x0, 10, x1, 118), inset=5, rim=0.18, depth=0.30)
        return encode(tile.values), "authored metal braces and recessed skin panels"
    if name in ("SW1SKULL", "SW2SKULL") and shape == (128, 64):
        tile = HeightTile(width, height)
        tile.values += 0.42 * tile.mound(32, 72, 39, 40)
        for x in (14, 49):
            tile.values -= 0.45 * tile.mound(x, 85, 11, 8.5)
        tile.values -= 0.45 * tile.mound(32, 96, 7.0, 10.0)
        return encode(tile.values), "authored raised skull and recessed sockets"
    return None


def height_map(row, family, context):
    """Return (linear 8-bit height, profile) or (None, fallback reason)."""
    name, pixels = row["name"], row["pixels"]
    if row.get("placeholder"):
        return None, "placeholder"
    if family == "sky / static artwork":
        return None, "sky image"
    if family == "liquid / static sample" or name.startswith("DBRAIN"):
        return None, "animated liquid, flame or flesh imagery"
    if np.any(pixels[:, :, 3] != 255):
        return None, "masked wall silhouette"
    if name.startswith(("ZZWOLF3", "ZZWOLF4", "ZZWOLF6", "ZZWOLF7")):
        return None, "printed sign or mural"
    formed = formed_hardware(name, pixels.shape[:2])
    if formed is not None:
        height, label = formed
        return encode(height), label
    if name == "EXITSIGN":
        return None, "printed sign without a registered casing"
    authored = authored_detail(name, pixels.shape[:2]) or authored_panel(name, pixels.shape[:2])
    if authored is not None:
        return authored

    shape = pixels.shape[:2]
    review = reviewed_panel(name, shape)
    if review is not None:
        height, label = review
        return encode(height), label
    context = context or {}
    features = WallFeatures(pixels, context.get("paired_pixels"))
    if (name, shape) in (("SW1COMM", (72, 64)), ("SW2COMM", (72, 64)),
                         ("SW1EXIT", (72, 32)), ("SW2EXIT", (72, 32))):
        tile = HeightTile(shape[1], shape[0])
        if name.endswith("EXIT"):
            tile.joints(horizontal=(0, 63), depth=0.15, width=1.8)
        else:
            # Brushed backing is shared with SHAWN2. Keep the housing its
            # own surface instead of extending that grain through the panel.
            strip = np.median(features.tone - mean_line(features.tone, 1, 3), axis=0)
            tile.values[:] = np.repeat(0.10 * np.tanh(45.0 * strip), 2)
        if mount_source_switch(tile, context):
            return encode(tile.values), "independent switch housing on brushed metal backing"
        backing = tile.values.reshape(shape[0], 2, shape[1], 2).mean(axis=(1, 3))
        height, label = switch_panel(features, context, backing), "switch housing on brushed metal backing"
    elif name in ("SW1BRCOM", "SW2BRCOM", "SW1BRN1", "SW2BRN1", "SW1BRNGN", "SW2BRNGN") and shape in ((128, 64), (128, 128)):
        tile = HeightTile(shape[1], shape[0])
        brown_panel(tile)
        if mount_source_switch(tile, context):
            return encode(tile.values), "independent switch face on the original brown wall trim"
        backing = tile.values.reshape(shape[0], 2, shape[1], 2).mean(axis=(1, 3))
        height, label = switch_panel(features, context, backing), "switch housing on the original brown wall trim"
    elif name == "BROVINE2" and context.get("vine_mask") is not None:
        tile = HeightTile(shape[1], shape[0])
        brown_panel(tile)
        mask = context["vine_mask"]
        vines = 0.30 * smoothstep(blur(mask, 1), 0.06, 0.88)
        backing = tile.values.reshape(shape[0], 2, shape[1], 2).mean(axis=(1, 3))
        height, label = backing * (1.0 - mask) + vines, "relief from the original vine patch silhouette"
    elif name == "SP_HOT1" and shape == (128, 256):
        tile = HeightTile(256, 128)
        rows = (0, 26, 51, 80, 104, 128)
        spans = [(x, start, x, stop)
                 for (start, stop), stagger in zip(zip(rows, rows[1:]), (0, 15.5, 0, 48.5, 16))
                 for x in np.arange(stagger, 256, 64)]
        tile.joints(horizontal=rows[:-1], spans=spans, depth=0.43, width=3.0)
        return encode(tile.values), "original red masonry courses and staggered mortar"
    elif name in ("BROWNHUG", "STUCCO", "BRICK2"):
        height, label = mineral_finish(features), "weathered mineral clusters and worn joints"
        if name == "STUCCO":
            height *= 1.35
        elif name == "BRICK2":
            # Very low contrast in the original. Accentuate coherent runs only.
            features.tone = np.clip(0.5 + 2.6 * (features.tone - blur(features.tone, 5)), 0.0, 1.0)
            height += 0.70 * mortar(features)
    elif name in ("SHAWN2", "SILVER1") and shape == (128, 64):
        # The narrow grooves are persistent down the grain. The broad
        # horizontal lighting painted into this texture adds no contour.
        strip = np.median(features.tone - mean_line(features.tone, 1, 3), axis=0)
        strength = 0.10 if name == "SHAWN2" else 0.08
        height = np.broadcast_to(strength * np.tanh(45.0 * strip), shape).copy()
        if name == "SILVER1":
            tile = HeightTile(64, 128)
            tile.joints(horizontal=(8, 120), depth=0.23, width=2.1)
            height += tile.values.reshape(128, 2, 64, 2).mean(axis=(1, 3))
        label = "brushed metal grain independent of baked lighting"
    elif name in ("GRAYVINE", "SW1VINE", "SW2VINE"):
        height = features.vines()
        if name != "GRAYVINE":
            height = switch_panel(features, context, height)
        label = "raised vine overlay on stone backing"
    elif name in ("SW1STRTN", "SW2STRTN") and shape == (128, 64):
        tile = HeightTile(64, 128)
        stamped_base_wall(tile, name)
        if mount_source_switch(tile, context):
            return encode(tile.values), "independent switch housing on stamped wall panels"
        backing = tile.values.reshape(128, 2, 64, 2).mean(axis=(1, 3))
        height, label = switch_panel(features, context, backing), "switch housing on stamped wall panels"
    elif name in ("SW1MOD1", "SW2MOD1") and pixels.shape[:2] == (128, 64):
        tile = HeightTile(64, 128)
        modular_wall(tile, "MODWALL1")
        backing = tile.values.reshape(128, 2, 64, 2).mean(axis=(1, 3))
        height, label = switch_panel(features, context, backing), "switch plate on modular rails"
    elif name.startswith(("SW1", "SW2")):
        height, label = switch_panel(features, context), "switch plate and backing seams"
    elif family == "brick / mortar" or name.startswith(("GSTONE", "MARBLE2", "MARBLE3")):
        height, label = mortar(features), "masonry courses and mortar"
    elif family == "wood":
        height, label = planks(features, name), "board joints and crossbars"
    elif name in ("TEKWALL4", "TEKWALL6", "TEKBRON1", "TEKBRON2", "STARTAN3", "EXITDOOR", "ZELDOOR"):
        height, label = 0.55 * panels(features, rails=True), "shallow coherent seams in painted machinery"
    elif family in ("metal", "painted panels", "painted technology"):
        rails = name.startswith(
            ("PIPE", "TEKBRON", "TEKWALL", "TEKGREN", "COMP", "SPACE", "LITE")
        )
        height, label = panels(features, rails), "fitted panels, channels and rails"
    elif family == "stone / concrete":
        masonry = mortar(features)
        height, label = 0.80 * masonry + 0.26 * features.terrain(), "mineral blocks and surface contours"
    elif family in ("carved stone", "organic"):
        height, label = 0.40 * features.terrain(), "rounded carved or organic contours"
    else:
        height = 0.68 * panels(features) + 0.14 * features.terrain()
        label = "shallow seams and formed surface contours"

    if np.count_nonzero(np.abs(height) >= 0.028) < max(12, height.size // 400):
        return None, "no confident structural features"
    return encode(height), label
