"""Doom II and DBP50 sprite height in the original patch coordinates."""

from collections import defaultdict
from dataclasses import dataclass
import struct

import numpy as np
from PIL import Image, ImageFilter


ACTORS = {
    "human": "POSS SPOS CPOS SSWV PLAY KEEN",
    "demon": "TROO SARG BOS2 BOSS VILE FATT",
    "floating demon": "HEAD PAIN",
    "skeleton": "SKEL SKUL",
    "cyborg": "CYBR SPID BSPI",
    "brain": "BBRN",
}

PROPS = {
    "armor": "ARM1 ARM2 BON2",
    "medical": "MEDI STIM PSTR SUIT",
    "ammunition": "CLIP AMMO SHEL SBOX ROCK BROK CELL CELP BPAK",
    "weapon pickup": "SHOT SGN2 MGUN LAUN PLAS BFUG CSAW",
    "keycard": "BKEY RKEY YKEY",
    "skull key": "BSKU RSKU YSKU",
    "powerup": "BON1 SOUL MEGA PINS PINV PVIS PMAP",
    "pillar": "COL1 COL2 COL3 COL4 COL5 COL6 COLU ELEC",
    "barrel": "BAR1 FCAN",
    "fixture": "CAND CBRA TBLU TGRN TRED SMBT SMGT SMRT TLMP TLP2",
    "ornament": "CEYE FSKU",
    "wood": "TRE1 TRE2 SMIT SMT2",
    "corpse": "GOR1 GOR2 GOR3 GOR4 GOR5 HDB1 HDB2 HDB3 HDB4 HDB5 HDB6 POL1 POL2 POL3 POL4 POL5 POL6",
}

ROLES = {
    prefix: role
    for group in (ACTORS, PROPS)
    for role, names in group.items()
    for prefix in names.split()
}
DBP50_ROLES = {
    "COL1": "foliage", "COL2": "foliage", "COL3": "foliage",
    "TRE1": "foliage", "TRE2": "foliage", "POB2": "reeds",
    "COL4": "rubble", "POB1": "trash bag", "COL6": "mailbox",
    "POL3": "fixture",
}
VIEWMODEL = frozenset("PUNG PISG SHTG SHT2 CHGG MISG PLSG BFGG SAWG".split())
EFFECTS = frozenset(
    "APBX APLS BAL1 BAL2 BAL7 BEXP BFE1 BFE2 BFGF BFS1 BLUD BOSF BRS1 CHGF FATB FBXP "
    "FIRE IFOG MANF MISF MISL PISF PLSE PLSF PLSS PUFF SHTF TFOG".split()
)
POOLS = frozenset(("POB1", "POB2"))

# The same material role uses the same native-pixel distance and height in every
# pose. Mip filtering and the light's scale then see a stable physical range.
VOLUME = {
    "human": (8.0, 0.41), "demon": (10.5, 0.41), "floating demon": (15.0, 0.41),
    "skeleton": (8.0, 0.36), "cyborg": (12.5, 0.40), "brain": (14.0, 0.39),
    "armor": (7.0, 0.41), "medical": (6.0, 0.37), "ammunition": (5.0, 0.39),
    "weapon pickup": (4.5, 0.41), "keycard": (4.0, 0.31), "skull key": (4.0, 0.34),
    "powerup": (7.0, 0.37), "pillar": (7.0, 0.41), "barrel": (6.0, 0.40),
    "fixture": (4.0, 0.34), "ornament": (6.0, 0.34), "wood": (8.0, 0.34),
    "corpse": (5.5, 0.32), "viewmodel": (10.0, 0.38), "rocket casing": (6.5, 0.39),
    "foliage": (8.0, 0.43), "reeds": (4.0, 0.40), "rubble": (7.0, 0.42),
    "trash bag": (11.0, 0.43), "mailbox": (7.5, 0.39),
}

# Bounds are in patch-origin vertical coordinates. Isolate fixture supports
# and the cap of a flaming skull from their changing light or flame pixels.
FIXTURE_CUTS = {
    "CAND": (None, 8), "CBRA": (None, 46), "FCAN": (None, 26), "FSKU": (35, None),
    "TBLU": (None, 56), "TGRN": (None, 56), "TRED": (None, 56),
    "SMBT": (None, 38), "SMGT": (None, 38), "SMRT": (None, 38),
    "TLMP": (None, 62), "TLP2": (None, 46),
}

# The rotating organ on the evil-eye altar still has a stationary support.
# Its animation, hanging-corpse motion and actor actions retain their own art.
STATIONARY_ROLES = frozenset(("armor", "keycard", "skull key", "powerup", "fixture", "barrel", "pillar", "ornament"))


def smoothstep(values, low, high):
    ramp = np.clip((values - low) / (high - low), 0.0, 1.0)
    return ramp * ramp * (3.0 - 2.0 * ramp)


def blur(field, radius):
    image = Image.fromarray(np.uint8(np.rint(np.clip(field, 0, 1) * 255)))
    return np.asarray(image.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32) / 255.0


def distance_to_edge(solid, limit):
    """Bounded chamfer distance on a nonrepeating silhouette."""
    field = np.pad(np.where(solid, np.float32(limit), np.float32(0)), 1)
    for _ in range(int(np.ceil(limit))):
        inner = field[1:-1, 1:-1]
        cardinal = np.minimum(np.minimum(field[1:-1, :-2], field[1:-1, 2:]),
                              np.minimum(field[:-2, 1:-1], field[2:, 1:-1]))
        diagonal = np.minimum(np.minimum(field[:-2, :-2], field[2:, 2:]),
                              np.minimum(field[:-2, 2:], field[2:, :-2]))
        inner[:] = np.minimum(inner, np.minimum(cardinal + 1.0, diagonal + np.float32(2 ** 0.5)))
    return field[1:-1, 1:-1]


@dataclass(frozen=True)
class PatchBounds:
    width: int
    height: int
    left: int
    top: int

    @classmethod
    def from_lump(cls, data):
        return cls(*struct.unpack_from("<hhhh", data))

    def window(self, canvas_left, canvas_top):
        x, y = canvas_left - self.left, canvas_top - self.top
        return np.s_[y:y + self.height, x:x + self.width]


def fixture_solid(prefix, coverage, bounds):
    low, high = FIXTURE_CUTS.get(prefix, (None, None))
    y = bounds.top - np.arange(bounds.height) - 0.5
    solid = coverage.copy()
    if low is not None:
        solid &= (y >= low)[:, None]
    if high is not None:
        solid &= (y <= high)[:, None]
    return solid


def volume(solid, role):
    radius, amplitude = VOLUME[role]
    distance = distance_to_edge(solid, radius)
    relief = amplitude * smoothstep(distance, 0.2, radius)
    edge = smoothstep(distance, 0.55, min(2.5, radius * 0.5))
    return relief, edge


def projected_hard_parts(pixels, solid, prefix, role):
    """Place a restrained secondary volume on recognizable stock colour groups."""
    rgb = pixels[:, :, :3].astype(np.float32) / 255.0
    red, green, blue = rgb.transpose(2, 0, 1)
    value, minimum = rgb.max(axis=2), rgb.min(axis=2)
    bright = smoothstep(value, 0.22, 0.52)
    metallic = (1.0 - smoothstep(value - minimum, 0.065, 0.22)) * bright
    bone = smoothstep(green, 0.36, 0.60) * smoothstep(blue, 0.27, 0.49)
    bone *= 1.0 - smoothstep(red - green, 0.19, 0.31)
    warm = smoothstep(red - blue, 0.05, 0.19) * smoothstep(green, 0.24, 0.49)
    if role == "cyborg" or prefix in ("FATT", "SKEL"):
        structure = np.maximum(0.96 * metallic, 0.43 * bone)
    elif role in ("skeleton", "floating demon", "demon"):
        structure = 0.82 * bone + 0.25 * warm
    elif role in ("human", "weapon pickup", "viewmodel", "rocket casing"):
        structure = np.maximum(0.74 * metallic, 0.52 * warm)
    elif role == "mailbox":
        # Red stamped rails and brown vines follow the art in each of the eight views.
        rails = (green < 0.025) & (blue < 0.025) & (red > 0.40)
        vines = (red - green > 0.045) & (green - blue > 0.045) & (green > 0.085)
        structure = np.maximum(0.86 * rails, 0.93 * vines)
    elif role == "foliage":
        berries = (blue - green > 0.08) & (blue - red > 0.12)
        leaves = smoothstep(green - red, 0.02, 0.12) * smoothstep(green - blue, 0.03, 0.12)
        structure = np.maximum(0.83 * berries, 0.56 * leaves)
    elif role == "rubble":
        boards = (red - blue > 0.075) & (green - blue > 0.045)
        structure = np.maximum(0.76 * boards, 0.54 * metallic)
    else:
        return 0.0
    # Require a colour cluster of several adjacent source pixels, so isolated
    # highlights and cuts within the cluster cannot create a deep noisy pit.
    coherent = blur(structure * solid, 1.20) / np.maximum(blur(solid, 1.20), 0.14)
    return 0.17 * smoothstep(coherent, 0.24, 0.80)


def actor_or_single_height(prefix, role, pixels, solid):
    if prefix == "SKUL":
        # The red/yellow silhouette changes during attacks; keep the skull and
        # horns, using the exact palette colours to exclude outer flame.
        red, green, blue = pixels[:, :, :3].astype(np.int16).transpose(2, 0, 1)
        luminous_flame = (red - green > 45) & (red - blue > 93) & (blue < 47)
        solid &= ~luminous_flame
    relief, edge = volume(solid, role)
    return (relief + projected_hard_parts(pixels, solid, prefix, role)) * edge * solid


class SpriteRelief:
    def __init__(self, sprites, decoder, overridden=()):
        self.sprites = sprites
        self.decoder = decoder
        self.overridden = overridden
        self.loops = {}
        groups = defaultdict(list)
        for name in sprites:
            role, _ = self.classify(name)
            if role in STATIONARY_ROLES and len(name) == 6 and name[5] == "0":
                groups[name[:4]].append(name)
        self.groups = {prefix: sorted(names) for prefix, names in groups.items() if len(names) > 1}

    def classify(self, name):
        prefix = name[:4]
        if name in self.overridden and prefix in DBP50_ROLES:
            return DBP50_ROLES[prefix], None
        if prefix in ROLES:
            return ROLES[prefix], None
        if prefix in VIEWMODEL:
            return "viewmodel", None
        if name.startswith("MISLA"):
            return "rocket casing", None
        if prefix in EFFECTS:
            return None, "light, projectile or transient effect"
        if prefix in POOLS:
            return None, "flat blood pool decoration"
        return None, "sprite family has no structural profile"

    def solid(self, name, pixels, bounds):
        solid = fixture_solid(name[:4], pixels[:, :, 3] > 0, bounds)
        if name in self.overridden and name[:4] == "POL3":
            # Both streetlamp frames use this glass rectangle in patch-origin space.
            x = np.arange(bounds.width) - bounds.left
            y = bounds.top - np.arange(bounds.height)
            solid &= ~(((y >= 100) & (y <= 109))[:, None] & ((x >= -5) & (x <= 5))[None, :])
        return solid

    def stationary_height(self, prefix, role):
        if prefix in self.loops:
            return self.loops[prefix]
        names = self.groups[prefix]
        bounds = [PatchBounds.from_lump(self.sprites[name]) for name in names]
        left = max(bound.left for bound in bounds)
        right = max(bound.width - bound.left for bound in bounds)
        top = max(bound.top for bound in bounds)
        bottom = min(bound.top - bound.height for bound in bounds)
        common = np.ones((top - bottom, left + right), dtype=bool)
        for name, bound in zip(names, bounds):
            frame = np.zeros_like(common)
            frame[bound.window(left, top)] = self.solid(name, self.decoder.patch(name), bound)
            common &= frame
        relief, edge = volume(common, role)
        self.loops[prefix] = relief * edge * common, left, top
        return self.loops[prefix]

    def height(self, name, pixels):
        role, reason = self.classify(name)
        if reason is not None:
            return None, reason
        prefix = name[:4]
        bounds = PatchBounds.from_lump(self.sprites[name])
        if prefix in self.groups and name in self.groups[prefix]:
            field, left, top = self.stationary_height(prefix, role)
            field = field[bounds.window(left, top)]
        else:
            field = actor_or_single_height(prefix, role, pixels, self.solid(name, pixels, bounds))
        if not np.any(field >= 1.5 / 255.0):
            return None, "no stable solid interior"
        return np.uint8(np.rint(128.0 + np.clip(field, -0.40, 0.47) * 255.0)), role
