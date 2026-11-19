"""Find local Doom II light fixtures in classic map geometry."""

from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from hashlib import md5
from math import ceil, dist, floor, hypot
from struct import iter_unpack


@dataclass(frozen=True)
class SurfaceFixture:
    regions: tuple[tuple[int, int, int, int], ...]
    color: tuple[int, int, int]
    radius: int
    intensity: int
    # Small, persistent hot spots within broad fields of glowing cracks.
    anchors: tuple[tuple[int, int, int, int], ...] = ()


FLUORESCENT = (235, 238, 241)
WARM_LENS = (255, 199, 143)
RED_LENS = (255, 72, 57)
BLUE_LENS = (103, 147, 255)
FIRELIGHT = (255, 155, 90)
YELLOW_STRIP = (255, 230, 148)
CRT_GREEN = (104, 192, 93)

# The boxes enclose the light-bearing texels at original resolution. Where
# a bulb isn't rectangular, the material can further mask the pixels by color.
FLAT_FIXTURES = {
    "FLAT2": SurfaceFixture(((16, 20, 48, 46),), FLUORESCENT, 144, 74),
    "FLAT17": SurfaceFixture(((4, 21, 60, 45),), FLUORESCENT, 150, 78),
    "CEIL1_2": SurfaceFixture(((15, 22, 49, 45),), FLUORESCENT, 116, 62),
    "CEIL1_3": SurfaceFixture(((15, 22, 49, 45),), FLUORESCENT, 116, 62),
    "FLOOR1_7": SurfaceFixture(((7, 25, 58, 41),), RED_LENS, 92, 50),
    "TLITE6_1": SurfaceFixture(((22, 22, 42, 42),), WARM_LENS, 112, 58),
    "TLITE6_4": SurfaceFixture(((22, 22, 42, 42),), WARM_LENS, 112, 58),
    "TLITE6_5": SurfaceFixture(((11, 11, 21, 21), (43, 11, 53, 21),
                                (11, 43, 21, 53), (43, 43, 53, 53)), RED_LENS, 64, 36),
    "TLITE6_6": SurfaceFixture(((10, 10, 22, 22), (42, 10, 54, 22),
                                (10, 42, 22, 54), (42, 42, 54, 54)), WARM_LENS, 78, 42),
}


def shared_fixture(table, names, fixture):
    table.update(dict.fromkeys(names.split(), fixture))


FIELD = ((0, 0, 64, 64),)
ROCK_SEAMS = ((15, 15, 18, 18), (47, 15, 50, 18), (13, 44, 17, 48), (47, 50, 51, 54))
shared_fixture(FLAT_FIXTURES, "LAVA1 LAVA2 LAVA3 LAVA4", SurfaceFixture(FIELD, FIRELIGHT, 104, 39))
shared_fixture(FLAT_FIXTURES, "RROCK05 RROCK06 RROCK07 RROCK08",
               SurfaceFixture(FIELD, (253, 66, 36), 64, 24, ROCK_SEAMS))
shared_fixture(FLAT_FIXTURES, "SLIME09 SLIME10 SLIME11 SLIME12",
               SurfaceFixture(FIELD, (253, 64, 34), 64, 24,
                              ((18, 14, 21, 17), (50, 14, 53, 17), (18, 46, 21, 49), (50, 46, 53, 49))))
FLAT_FIXTURES["RROCK02"] = SurfaceFixture(FIELD, (255, 172, 58), 78, 32, ROCK_SEAMS)

WALL_FIXTURES = {
    "LITE3": SurfaceFixture(((1, 0, 31, 128),), FLUORESCENT, 128, 62),
    "LITE5": SurfaceFixture(((1, 0, 15, 128),), FLUORESCENT, 114, 58),
    "LITEBLU1": SurfaceFixture(((2, 21, 6, 36), (2, 96, 6, 111)), BLUE_LENS, 78, 39),
    "LITEBLU4": SurfaceFixture(((1, 0, 15, 128),), BLUE_LENS, 92, 46),
    "SILVER2": SurfaceFixture(tuple((x, y, x + 9, y + 15)
                                    for x in (8, 28, 47) for y in (27, 88)), BLUE_LENS, 64, 30),
    "TEKGREN5": SurfaceFixture(((4, 4, 59, 12),), (255, 245, 205), 144, 53),
    "TEKBRON2": SurfaceFixture(((18, 4, 47, 6),), WARM_LENS, 76, 36),
    "METAL6": SurfaceFixture(((5, 3, 60, 11),), YELLOW_STRIP, 110, 49),
    "METAL7": SurfaceFixture(((5, 117, 60, 125),), YELLOW_STRIP, 110, 49),
    "EXITSIGN": SurfaceFixture(((2, 3, 31, 13),), RED_LENS, 40, 21),
    "EXITSTON": SurfaceFixture(((20, 25, 47, 35),), RED_LENS, 40, 21),
    "BRICKLIT": SurfaceFixture(((29, 34, 39, 43),), FIRELIGHT, 96, 44),
    "BSTONE3": SurfaceFixture(((29, 34, 38, 44),), FIRELIGHT, 96, 44),
    "COMPSTA1": SurfaceFixture(((8, 24, 50, 41), (97, 5, 118, 19), (96, 28, 117, 41)),
                               CRT_GREEN, 44, 22),
    "COMPSTA2": SurfaceFixture(((9, 6, 49, 40), (93, 6, 120, 20), (99, 30, 117, 40)),
                               CRT_GREEN, 44, 22),
}
shared_fixture(WALL_FIXTURES, "BRONZE4 BIGBRIK3",
               SurfaceFixture(((3, 120, 29, 124), (35, 120, 61, 124)), YELLOW_STRIP, 84, 40))
shared_fixture(WALL_FIXTURES, "FIREBLU1 FIREBLU2",
               SurfaceFixture(((0, 0, 128, 128),), (157, 90, 214), 84, 30))
shared_fixture(WALL_FIXTURES, "FIRELAV3 FIRELAVA FIRELAV2",
               SurfaceFixture(((0, 0, 128, 128),), (248, 65, 36), 92, 36))
shared_fixture(WALL_FIXTURES, "FIREMAG1 FIREMAG2 FIREMAG3",
               SurfaceFixture(((0, 32, 128, 128),), (248, 67, 39), 90, 33))
shared_fixture(WALL_FIXTURES, "FIREWALA FIREWALB FIREWALL",
               SurfaceFixture(((0, 0, 128, 100),), (252, 71, 40), 96, 39))
shared_fixture(WALL_FIXTURES, "CRACKLE2 CRACKLE4",
               SurfaceFixture(((0, 0, 64, 128),), (255, 170, 58), 76, 29,
                              ROCK_SEAMS + ((15, 76, 18, 79), (47, 79, 50, 82),
                                            (14, 110, 17, 113), (45, 111, 48, 114))))


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
    texture: str | None = None
    light_cycle: tuple[int, int] | None = None

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
    light_cycle: tuple[int, int] | None = None

    def call(self):
        rgb = ", ".join(map(str, self.color))
        ceiling = "true" if self.ceiling else "false"
        return (f'AddPlaneEmitter("{self.texture}", {self.sector}, ({self.x}, {self.y}), {self.inset}, '
                f"{self.radius // 2}, {rgb}, {self.intensity}, {ceiling});")


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
    special: int = 0


class MapGeometry:
    def __init__(self, lumps):
        self.vertices = tuple(iter_unpack("<hh", lumps["VERTEXES"]))
        self.lines = tuple(iter_unpack("<HHHHHHH", lumps["LINEDEFS"]))
        self.sides = tuple(iter_unpack("<hh8s8s8sH", lumps["SIDEDEFS"]))
        self.sectors = tuple(Sector(f, c, lump_name(ft), lump_name(ct), light, special)
                             for f, c, ft, ct, light, special, _ in iter_unpack("<hh8s8shhh", lumps["SECTORS"]))
        self.edges = defaultdict(list)
        lowest_neighbour = [cell.light for cell in self.sectors]
        for a, b, flags, _, _, front, back in self.lines:
            sides = self.line_sides(front, back)
            if len(sides) == 2 and sides[0][0][-1] == sides[1][0][-1]:
                continue
            for side, adjacent, reversed_side in sides:
                start, end = (b, a) if reversed_side else (a, b)
                edge = self.vertices[start], self.vertices[end]
                self.edges[side[-1]].append(edge)
                if flags & 4 and adjacent is not None:
                    lowest_neighbour[side[-1]] = min(lowest_neighbour[side[-1]], self.sectors[adjacent].light)
        self.light_cycles = {}
        for i, cell in enumerate(self.sectors):
            if cell.special in (1, 2, 3, 4, 8, 12, 13, 17) and cell.light > 0:
                # DStrobe treats its dimmer neighbour as the lamp's off state,
                # or drops to zero when there is no darker adjacent sector.
                strobe = cell.special in (2, 3, 4, 12, 13)
                dark = lowest_neighbour[i] if strobe and lowest_neighbour[i] < cell.light else 0
                self.light_cycles[i] = (cell.light, dark)
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
                    if (u0 <= point[0] % period < u1 and v0 <= -point[1] % period < v1
                        and geometry.contains(sector, *point)):
                        yield point


def spaced_sites(sites, center, spacing, limit):
    """Cover the footprint evenly with a bounded number of emitters."""
    sites = sorted(set(sites))
    if not sites:
        return
    selected = min(sites, key=lambda p: dist(p, center))
    remaining = {point: float("inf") for point in sites}
    for _ in range(limit):
        yield selected
        del remaining[selected]
        if not remaining:
            break
        for point, previous in remaining.items():
            remaining[point] = min(previous, dist(point, selected))
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
        sites = plane_sites(geometry, sector, bounds, fixture.anchors or fixture.regions, 64)
        spacing = 60 if narrow else max(72, fixture.radius * 0.54)
        center = ((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2)
        positions = list(spaced_sites(sites, center, spacing, 6))
        strength = lit_intensity(fixture.intensity, cell.light)
        if narrow and len(positions) > 1:
            strength = round(strength * 0.8)
        for x, y in positions:
            yield PlaneEmitter(texture, sector, x, y, 8, fixture.radius, strength, fixture.color,
                               ceiling, light_cycle=geometry.light_cycles.get(sector))


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
        if peg_bottom:
            texture_top = back.ceiling if front.ceiling_texture == back.ceiling_texture == "F_SKY1" else front.ceiling
        else:
            texture_top = back.floor
    else:
        low, high = max(front.floor, back.floor), min(front.ceiling, back.ceiling)
        texture_top = low + height if peg_bottom else high
        low = max(low, texture_top + y_offset - height)
        high = min(high, texture_top + y_offset)
    return max(low, front.floor), min(high, front.ceiling), texture_top + y_offset


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
                for u0, v0, u1, v1 in fixture.anchors or fixture.regions:
                    for z in visible_centres(low, high, texture_top - v1, texture_top - v0, height):
                        for along in visible_centres(0, length, u0 - side[0], u1 - side[0], width):
                            x, y = round(ax + tx * along + ty * 4), round(ay + ty * along - tx * 4)
                            if geometry.contains(sector, x, y):
                                # Identify the lit texels before applying the actor's plane clearance:
                                # several stock textures have a two-pixel lens right at the top or base.
                                height_above_floor = min(cell.ceiling - 8, max(cell.floor + 8, round(z))) - cell.floor
                                yield Emitter(sector, x, y, height_above_floor, fixture.radius,
                                              fixture.color, lit_intensity(fixture.intensity, cell.light),
                                              texture=name, light_cycle=geometry.light_cycles.get(sector))


def fixture_sizes(wad):
    from wall_materials import definitions

    texture_lumps = {name: wad.lump(name) for name in ("PNAMES", "TEXTURE1", "TEXTURE2") if name in wad.by_name}
    return {name: row[:2] for name, row in definitions(texture_lumps).items()
            if name in WALL_FIXTURES}


def infer_layout(wad):
    from stageb_campaign import tune_stock_lights

    sizes = fixture_sizes(wad)
    layouts = {}
    for name, checksum, lumps in stock_map_lumps(wad):
        geometry = MapGeometry(lumps)
        by_sector = defaultdict(lambda: defaultdict(dict))
        for emitter in wall_emitters(geometry, sizes):
            by_sector[emitter.sector][emitter.texture][emitter.x, emitter.y, emitter.height] = emitter
        emitters = []
        for sector, cell in enumerate(geometry.sectors):
            if cell.ceiling - cell.floor < 16 or sector not in geometry.edges:
                continue
            bounds = geometry.bounds(sector)
            emitters.extend(plane_emitters(geometry, sector, cell, bounds))
            for texture, sites in by_sector[sector].items():
                # Sidedefs may tile hundreds of identical footlights or lava cracks around one
                # room. Bound the cost spatially, retaining actual lit texels around its perimeter.
                center = tuple((min(axis) + max(axis)) / 2 for axis in zip(*sites))
                spacing = min(88, max(40, WALL_FIXTURES[texture].radius * 0.55))
                for point in spaced_sites(sites, center, spacing, 10):
                    emitters.append(sites[point])
        # Decorations already supply their own lights through the runtime's GLDEFS.
        layouts[name] = (checksum, tune_stock_lights(name, emitters))
    return layouts
