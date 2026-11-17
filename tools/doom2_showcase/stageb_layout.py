"""Find local Doom II light fixtures in classic map geometry."""

from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from hashlib import md5
from math import ceil, floor, hypot
from struct import iter_unpack


@dataclass(frozen=True)
class SurfaceFixture:
    regions: tuple[tuple[int, int, int, int], ...]
    color: tuple[int, int, int]
    radius: int
    intensity: int


FLUORESCENT = (235, 238, 241)
WARM_LENS = (255, 199, 143)
RED_LENS = (255, 72, 57)
BLUE_LENS = (103, 147, 255)
FIRELIGHT = (255, 150, 94)

# The boxes enclose the light-bearing texels at original resolution. Where
# a bulb isn't rectangular, the material can further mask the pixels by color.
FLAT_FIXTURES = {
    "FLAT2": SurfaceFixture(((18, 20, 46, 45),), FLUORESCENT, 224, 94),
    "CEIL1_2": SurfaceFixture(((14, 20, 49, 45),), FLUORESCENT, 172, 68),
    "CEIL1_3": SurfaceFixture(((14, 20, 49, 45),), FLUORESCENT, 172, 68),
    "TLITE6_1": SurfaceFixture(((21, 21, 43, 43),), WARM_LENS, 166, 65),
    "TLITE6_4": SurfaceFixture(((21, 21, 43, 43),), WARM_LENS, 166, 65),
    "TLITE6_5": SurfaceFixture(((7, 7, 23, 23), (40, 7, 56, 23),
                                (7, 40, 23, 56), (40, 40, 56, 56)), RED_LENS, 136, 49),
    "TLITE6_6": SurfaceFixture(((7, 7, 23, 23), (40, 7, 56, 23),
                                (7, 40, 23, 56), (40, 40, 56, 56)), WARM_LENS, 150, 57),
    "LAVA3": SurfaceFixture(((0, 0, 64, 64),), FIRELIGHT, 145, 40),
    "LAVA4": SurfaceFixture(((0, 0, 64, 64),), FIRELIGHT, 145, 40),
}

WALL_FIXTURES = {
    "LITE3": SurfaceFixture(((4, 0, 28, 128),), FLUORESCENT, 188, 69),
    "LITE5": SurfaceFixture(((3, 0, 13, 128),), FLUORESCENT, 170, 65),
    "LITEBLU1": SurfaceFixture(((1, 20, 7, 45), (1, 84, 7, 110)), BLUE_LENS, 116, 44),
    "LITEBLU4": SurfaceFixture(((2, 0, 14, 128),), BLUE_LENS, 146, 59),
    "TEKGREN5": SurfaceFixture(((4, 4, 59, 12),), (255, 245, 205), 192, 56),
    "EXITSIGN": SurfaceFixture(((2, 3, 31, 13),), RED_LENS, 54, 26),
    "BRICKLIT": SurfaceFixture(((28, 32, 44, 44),), FIRELIGHT, 132, 51),
    "FIREBLU2": SurfaceFixture(((0, 0, 128, 128),), (155, 105, 239), 120, 36),
    "FIRELAV3": SurfaceFixture(((0, 0, 128, 128),), (255, 108, 79), 130, 43),
    "FIRELAVA": SurfaceFixture(((0, 0, 128, 128),), (255, 108, 79), 130, 43),
    "FIREMAG2": SurfaceFixture(((0, 32, 128, 128),), FIRELIGHT, 124, 40),
    "FIREMAG3": SurfaceFixture(((0, 32, 128, 128),), FIRELIGHT, 124, 40),
    "FIREWALL": SurfaceFixture(((0, 0, 128, 100),), (255, 108, 79), 138, 48),
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
class PlaneEmitter:
    texture: str
    sector: int
    x: int
    y: int
    inset: int
    radius: int
    intensity: int
    color: tuple[int, int, int] = FLUORESCENT
    ceiling: bool = True

    def call(self):
        rgb = ", ".join(map(str, self.color))
        ceiling = "true" if self.ceiling else "false"
        return (f'AddPlaneEmitter("{self.texture}", {self.sector}, ({self.x}, {self.y}), {self.inset}, '
                f"{self.radius // 2}, {rgb}, {self.intensity}, {ceiling});")


@dataclass(frozen=True)
class ThingFixture:
    actor: str
    height: int
    radius: int
    color: tuple[int, int, int]
    intensity: int

    def call(self):
        rgb = ", ".join(map(str, self.color))
        return f'AddThingEmitters("{self.actor}", {self.height}, {self.radius // 2}, {rgb}, {self.intensity});'


# Stock DoomEdNums. Static decorations only, so the light can stay at its
# checked map position for the lifetime of the room.
THING_FIXTURES = {
    29: ThingFixture("HeadCandles", 37, 104, FIRELIGHT, 39),
    34: ThingFixture("Candlestick", 14, 84, FIRELIGHT, 35),
    35: ThingFixture("Candelabra", 49, 138, FIRELIGHT, 49),
    44: ThingFixture("BlueTorch", 60, 182, BLUE_LENS, 66),
    45: ThingFixture("GreenTorch", 60, 182, (135, 238, 115), 66),
    46: ThingFixture("RedTorch", 60, 182, FIRELIGHT, 68),
    55: ThingFixture("ShortBlueTorch", 35, 142, BLUE_LENS, 57),
    56: ThingFixture("ShortGreenTorch", 35, 142, (135, 238, 115), 57),
    57: ThingFixture("ShortRedTorch", 35, 142, FIRELIGHT, 59),
    70: ThingFixture("BurningBarrel", 32, 164, FIRELIGHT, 62),
    85: ThingFixture("TechLamp", 72, 176, FLUORESCENT, 70),
    86: ThingFixture("TechLamp2", 44, 146, FLUORESCENT, 64),
    2028: ThingFixture("Column", 44, 130, FLUORESCENT, 56),
}


def lump_name(value):
    return value.rstrip(b"\0").decode("ascii").upper()


def stock_map_lumps(wad):
    """Read classic map lumps in directory order, where lump names repeat."""
    required = ("THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES", "SEGS", "SSECTORS", "NODES",
                "SECTORS", "REJECT", "BLOCKMAP")
    for map_number in range(1, 33):
        name = f"MAP{map_number:02d}"
        marker = wad.by_name.get(name)
        if marker is None:
            raise ValueError(f"Missing Doom II map {name} in {wad.path}")
        end = marker[3] + 1 + len(required)
        entries = wad.entries[marker[3] + 1 : end]
        if tuple(entry[0] for entry in entries) != required or (
            end < len(wad.entries) and wad.entries[end][0] == "BEHAVIOR"
        ):
            raise ValueError(f"Expected a classic Doom II map at {name} in {wad.path}")
        lumps = {tag: wad.data[offset : offset + size] for tag, offset, size, _ in (marker, *entries)}
        # Matches MapData::GetChecksum for vanilla maps, excluding node-builder lumps.
        identity = md5(usedforsecurity=False)
        for tag in (name, "THINGS", "LINEDEFS", "SIDEDEFS", "SECTORS"):
            identity.update(lumps[tag])
        yield name, identity.hexdigest(), lumps


@dataclass(frozen=True)
class Sector:
    floor: int
    ceiling: int
    floor_texture: str
    ceiling_texture: str
    light: int


class MapGeometry:
    def __init__(self, lumps):
        self.vertices = tuple(iter_unpack("<hh", lumps["VERTEXES"]))
        self.lines = tuple(iter_unpack("<HHHHHHH", lumps["LINEDEFS"]))
        self.sides = tuple(iter_unpack("<hh8s8s8sH", lumps["SIDEDEFS"]))
        self.sectors = tuple(Sector(f, c, lump_name(ft), lump_name(ct), light)
                             for f, c, ft, ct, light, _, _ in iter_unpack("<hh8s8shhh", lumps["SECTORS"]))
        self.edges = defaultdict(list)
        self.open_edges = defaultdict(list)
        for a, b, flags, _, _, front, back in self.lines:
            sides = self.line_sides(front, back)
            if len(sides) == 2 and sides[0][0][-1] == sides[1][0][-1]:
                continue
            for side, adjacent, reversed_side in sides:
                start, end = (b, a) if reversed_side else (a, b)
                edge = self.vertices[start], self.vertices[end]
                self.edges[side[-1]].append(edge)
                if flags & 4 and adjacent is not None:
                    self.open_edges[side[-1]].append((adjacent, edge))
        self.scanline = cache(self.scanline)

    def line_sides(self, front, back):
        sides = []
        if front != 65535:
            sides.append((self.sides[front], None if back == 65535 else self.sides[back][-1], False))
        if back != 65535:
            sides.append((self.sides[back], None if front == 65535 else self.sides[front][-1], True))
        return sides

    def scanline(self, sector, y):
        crossings = defaultdict(int)
        for (ax, ay), (bx, by) in self.edges[sector]:
            if (ay > y) == (by > y):
                continue
            x = ax + (bx - ax) * (y - ay) / (by - ay)
            crossings[x] += 1 if ay < by else -1
        winding = 0
        intervals = []
        for x, delta in sorted(crossings.items()):
            next_winding = winding + delta
            if not winding and next_winding:
                start = x
            if winding and not next_winding:
                intervals.append((start, x))
            winding = next_winding
        return intervals

    def contains(self, sector, x, y):
        return any(first + 0.5 <= x <= last - 0.5 for first, last in self.scanline(sector, y))

    def bounds(self, sector):
        points = [position for edge in self.edges[sector] for position in edge]
        xs, ys = zip(*points)
        return min(xs), min(ys), max(xs), max(ys)


def visible_centres(low, high, first, last, period):
    """Yield centers of repeating source rectangles clipped to visible geometry."""
    for tile in range(floor((low - last) / period) + 1, ceil((high - first) / period)):
        start = max(low, tile * period + first)
        end = min(high, tile * period + last)
        if end - start >= 1:
            yield (start + end) / 2


def plane_sites(geometry, sector, bounds, regions, period):
    _, bottom, _, top = bounds
    for u0, v0, u1, v1 in regions:
        # Classic flat U follows world X and V follows minus world Y.
        for y in visible_centres(bottom, top, -v1, -v0, period):
            y = round(y)
            for left, right in geometry.scanline(sector, y):
                for x in visible_centres(left, right, u0, u1, period):
                    point = (round(x), y)
                    if geometry.contains(sector, *point):
                        yield point


def spaced_sites(sites, bounds, spacing, limit):
    """Cover the footprint evenly with a bounded number of emitters."""
    left, bottom, right, top = bounds
    center = ((left + right) / 2, (bottom + top) / 2)
    sites = sorted(set(sites))
    if not sites:
        return
    selected = min(sites, key=lambda p: hypot(p[0] - center[0], p[1] - center[1]))
    remaining = {point: float("inf") for point in sites}
    for _ in range(limit):
        yield selected
        del remaining[selected]
        if not remaining:
            break
        for point, previous in remaining.items():
            remaining[point] = min(previous, hypot(point[0] - selected[0], point[1] - selected[1]))
        selected = max(remaining, key=remaining.get)
        if remaining[selected] < spacing:
            break


def lit_intensity(intensity, original_light):
    # Adapt the real source to the map's contrast without using ambient
    # brightness as evidence of a fixture.
    return max(1, round(intensity * (0.48 + 0.52 * min(255, max(0, original_light)) / 255)))


def plane_emitters(geometry, sector, cell, bounds):
    narrow = min(bounds[2] - bounds[0], bounds[3] - bounds[1]) <= 80
    for texture, ceiling in ((cell.ceiling_texture, True), (cell.floor_texture, False)):
        fixture = FLAT_FIXTURES.get(texture)
        if fixture is None:
            continue
        sites = plane_sites(geometry, sector, bounds, fixture.regions, 64)
        spacing = 60 if narrow else max(72, fixture.radius * 0.54)
        positions = list(spaced_sites(sites, bounds, spacing, 6))
        strength = lit_intensity(fixture.intensity, cell.light)
        if narrow and len(positions) > 1:
            strength = round(strength * 0.8)
        radius = max(fixture.radius, min(288, cell.ceiling - cell.floor + 56))
        for x, y in positions:
            yield PlaneEmitter(texture, sector, x, y, 12, radius, strength, fixture.color, ceiling)


def recessed_spill(geometry, emitter):
    """Place a weaker sample just through an open lip next to a ceiling lamp."""
    if not emitter.ceiling or emitter.texture.startswith("LAVA"):
        return
    fixture = geometry.sectors[emitter.sector]
    for adjacent, ((ax, ay), (bx, by)) in geometry.open_edges[emitter.sector]:
        cell = geometry.sectors[adjacent]
        if (cell.ceiling_texture in FLAT_FIXTURES or not 0 < fixture.ceiling - cell.ceiling <= 24
            or abs(fixture.floor - cell.floor) > 16 or cell.ceiling - max(cell.floor, fixture.floor) < 48):
            continue
        length = hypot(bx - ax, by - ay)
        if length < 32:
            continue
        tx, ty = (bx - ax) / length, (by - ay) / length
        along = (emitter.x - ax) * tx + (emitter.y - ay) * ty
        if not 4 <= along <= length - 4:
            continue
        x, y = ax + tx * along, ay + ty * along
        if hypot(x - emitter.x, y - emitter.y) > 38:
            continue
        x, y = round(x - ty * 8), round(y + tx * 8)
        if geometry.contains(adjacent, x, y):
            yield Emitter(adjacent, x, y, cell.ceiling - cell.floor - 12, min(148, emitter.radius),
                          emitter.color, max(1, round(emitter.intensity * 0.38)))


SKY_COLORS = ((244, 234, 217), (242, 222, 204), (248, 179, 143))


def sky_emitters(geometry, sector, cell, bounds, color):
    if cell.ceiling_texture != "F_SKY1" or cell.floor_texture == "F_SKY1":
        return
    # A tile-less sky region; keep even very narrow skylights inside the sector.
    sites = list(plane_sites(geometry, sector, bounds, ((0, 0, 160, 160),), 160))
    if not sites:
        sites = plane_sites(geometry, sector, bounds, ((0, 0, 8, 8),), 8)
    for x, y in spaced_sites(sites, bounds, 200, 8):
        yield Emitter(sector, x, y, 80, 472, color, lit_intensity(80, cell.light), (315, 54), 1)


def wall_bands(flags, y_offset, front, back, height, part):
    peg_top = not (flags & 8)
    peg_bottom = bool(flags & 16)
    if back is None:
        if part != 2:
            return None
        low, high = front.floor, front.ceiling
        texture_top = front.floor + height if peg_bottom else front.ceiling
    elif part == 0:
        if front.ceiling_texture == back.ceiling_texture == "F_SKY1":
            return None
        low, high = back.ceiling, front.ceiling
        texture_top = back.ceiling + height if peg_top else front.ceiling
    elif part == 1:
        low, high = front.floor, min(back.floor, front.ceiling)
        texture_top = front.ceiling if peg_bottom else back.floor
    else:
        low, high = max(front.floor, back.floor), min(front.ceiling, back.ceiling)
        texture_top = low + height if peg_bottom else high
        low = max(low, texture_top + y_offset - height)
        high = min(high, texture_top + y_offset)
    # The runtime emitter needs at least eight map units clear of the planes.
    return max(low, front.floor + 8), min(high, front.ceiling - 8), texture_top + y_offset


def wall_emitters(geometry, sizes):
    for a, b, flags, _, _, front, back in geometry.lines:
        for side, adjacent, reverse in geometry.line_sides(front, back):
            sector = side[-1]
            cell = geometry.sectors[sector]
            if cell.ceiling - cell.floor < 16:
                continue
            other = geometry.sectors[adjacent] if adjacent is not None else None
            (ax, ay), (bx, by) = (geometry.vertices[i] for i in ((b, a) if reverse else (a, b)))
            length = hypot(bx - ax, by - ay)
            if length < 1:
                continue
            tx, ty = (bx - ax) / length, (by - ay) / length
            for part, raw in enumerate(side[2:5]):
                name = lump_name(raw)
                fixture = WALL_FIXTURES.get(name)
                if fixture is None or name not in sizes:
                    continue
                width, height = sizes[name]
                band = wall_bands(flags, side[1], cell, other, height, part)
                if band is None:
                    continue
                low, high, texture_top = band
                for u0, v0, u1, v1 in fixture.regions:
                    for z in visible_centres(low, high, texture_top - v1, texture_top - v0, height):
                        for along in visible_centres(0, length, u0 - side[0], u1 - side[0], width):
                            x, y = round(ax + tx * along + ty * 8), round(ay + ty * along - tx * 8)
                            if geometry.contains(sector, x, y):
                                yield Emitter(sector, x, y, round(z) - cell.floor, fixture.radius,
                                              fixture.color, lit_intensity(fixture.intensity, cell.light))


def fixture_sizes(wad):
    from wall_materials import definitions

    texture_lumps = {name: wad.lump(name) for name in ("PNAMES", "TEXTURE1", "TEXTURE2") if name in wad.by_name}
    return {name: row[:2] for name, row in definitions(texture_lumps).items()
            if name in WALL_FIXTURES}


def infer_layout(wad):
    sizes = fixture_sizes(wad)
    layouts = {}
    for name, checksum, lumps in stock_map_lumps(wad):
        if name == "MAP01":
            continue
        geometry = MapGeometry(lumps)
        by_sector = defaultdict(list)
        for emitter in wall_emitters(geometry, sizes):
            group = by_sector[emitter.sector]
            # Multiple wall segments can expose parts of the same repeated lamp.
            if all(hypot(hypot(e.x - emitter.x, e.y - emitter.y), e.height - emitter.height) >=
                   min(84, emitter.radius * 0.44) for e in group):
                group.append(emitter)
        sources = {}
        spills = defaultdict(list)
        map_number = int(name[3:])
        sky_color = SKY_COLORS[0 if map_number < 12 or map_number > 30 else 1 if map_number < 21 else 2]
        for sector, cell in enumerate(geometry.sectors):
            if cell.ceiling - cell.floor < 16 or sector not in geometry.edges:
                continue
            bounds = geometry.bounds(sector)
            planes = list(plane_emitters(geometry, sector, cell, bounds))
            sources[sector] = [*planes, *sky_emitters(geometry, sector, cell, bounds, sky_color), *by_sector[sector]]
            spill_counts = defaultdict(int)
            for emitter in planes:
                for spill in recessed_spill(geometry, emitter):
                    group = spills[spill.sector]
                    if (spill_counts[spill.sector] < 2 and len(group) < 4
                        and all(hypot(e.x - spill.x, e.y - spill.y) >= 72 for e in group)):
                        group.append(spill)
                        spill_counts[spill.sector] += 1
        # The renderer packs at most twelve Stage B lights per receiver.
        emitters = [emitter for sector, emitters in sources.items() for emitter in (emitters + spills[sector])[:10]]
        thing_types = {kind for _, _, _, kind, _ in iter_unpack("<hhhhh", lumps["THINGS"])}
        emitters.extend(fixture for kind, fixture in THING_FIXTURES.items() if kind in thing_types)
        layouts[name] = (checksum, emitters)
    return layouts
