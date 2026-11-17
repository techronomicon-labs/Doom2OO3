"""Bounded local material-art interpretations; no engine/gameplay changes."""

from __future__ import annotations
import json
import material_generator as base

np = base.np
Image = base.Image

PAINTED_HARDWARE = frozenset((
    "STARTAN3", "TEKGREN1", "TEKGREN2", "TEKGREN3", "TEKGREN4", "TEKGREN5",
    "TEKWALL4", "TEKWALL6", "TEKBRON1", "TEKBRON2",
))
AGED_HARDWARE = frozenset(("BRONZE1", "BRONZE2", "BRONZE3", "BRONZE4", "PIPE2", "PIPE4"))
STEEL_HARDWARE = frozenset((
    "BIGDOOR1", "BIGDOOR2", "BIGDOOR3", "BIGDOOR4", "DOOR3", "DOORTRAK",
    "EXITDOOR", "SUPPORT2", "ZELDOOR",
))

# Finish, face roughness, sheltered roughness gain, polished ridge reduction,
# base metallic and additional metallic on exposed neutral metal.
STOCK_FLAT_FINISH = {
    "CEIL4_1": ("matte dark coating", 0.82, 0.09, 0.05, 0.0, 0.0),
    "CEIL4_2": ("coated ceiling screen", 0.68, 0.03, 0.15, 0.05, 0.0),
    "CEIL4_3": ("coated ceiling screen", 0.68, 0.03, 0.15, 0.05, 0.0),
    "CEIL5_1": ("matte coated ceiling", 0.79, 0.08, 0.035, 0.02, 0.0),
    "CEIL5_2": ("oxidized surface with exposed metal grains", 0.72, 0.11, 0.07, 0.04, 0.30),
    "CRATOP1": ("dry crate with diagonal grain", 0.78, 0.11, 0.085, 0.0, 0.0),
    "CRATOP2": ("dry crate with diagonal grain", 0.78, 0.11, 0.085, 0.0, 0.0),
    "FLAT1": ("worn galvanized steel with a folded seam", 0.60, 0.14, 0.09, 0.27, 0.21),
    "FLAT14": ("dry granular blue coating", 0.79, 0.13, 0.08, 0.0, 0.0),
    "FLAT19": ("fine concrete stipple", 0.85, 0.10, 0.06, 0.0, 0.0),
    "FLAT23": ("brushed satin steel", 0.52, 0.08, 0.055, 0.47, 0.0),
    "FLAT4": ("satin metal lattice", 0.54, 0.09, 0.06, 0.41, 0.10),
    "FLAT5": ("worn stone with rough recessed mortar", 0.73, 0.14, 0.05, 0.0, 0.0),
    "FLAT5_3": ("stained wood with shallow worn grain", 0.76, 0.11, 0.09, 0.0, 0.0),
    "FLAT5_4": ("dry timber and worn grain", 0.69, 0.15, 0.09, 0.0, 0.0),
    "FLOOR0_1": ("worn floor plates with dark seams", 0.64, 0.09, 0.06, 0.08, 0.14),
    "FLOOR0_3": ("worn floor panels with recessed parquet seams", 0.68, 0.14, 0.06, 0.08, 0.14),
    "FLOOR1_1": ("dry dyed flooring", 0.82, 0.06, 0.05, 0.0, 0.0),
    "FLOOR1_6": ("dry red floor coating", 0.82, 0.10, 0.065, 0.0, 0.0),
    "FLOOR4_1": ("oxidized cast metal vent", 0.58, 0.12, 0.055, 0.17, 0.19),
    "GATE3": ("cast frame with a matte printed seal", 0.58, 0.19, 0.03, 0.24, 0.21),
    "GRASS1": ("matte grass and soil", 0.90, 0.045, 0.04, 0.0, 0.0),
    "GRASS2": ("matte grass clumps and exposed soil", 0.87, 0.08, 0.055, 0.0, 0.0),
    "RROCK03": ("dry coarse aggregate", 0.86, 0.09, 0.055, 0.0, 0.0),
    "RROCK09": ("dry compacted gravel", 0.81, 0.09, 0.08, 0.0, 0.0),
    "RROCK20": ("mossy stone with dry raised faces", 0.87, 0.095, 0.06, 0.0, 0.0),
}
ENTRYWAY_MASONRY = frozenset(("ASHWALL3", "BROWNHUG", "CEMENT9", "STONE7", "STEP6"))
ENTRYWAY_BROWN_PANELS = frozenset(("BROWN1", "BROWN96", "BROWNGRN"))
ENTRYWAY_FRAMED_PANELS = frozenset((
    "MODWALL2", "MODWALL3", "SPACEW3", "SPACEW4", "COMPSPAN", "COMPWERD",
    "TEKWALL4", "TEKWALL6", "EXITDOOR", "LITE5", "EXITSIGN", "STEP2",
    "BRNSMAL1", "MIDBARS3",
))
ENTRYWAY_SWITCHES = frozenset((
    "SW1COMP", "SW2COMP", "SW1BRCOM", "SW2BRCOM",
    "SW1BRN1", "SW2BRN1", "SW1BRNGN", "SW2BRNGN",
))
REVIEWED_STONE = frozenset(("BIGBRIK1", "STONE4", "STONE5", "STUCCO"))
REVIEWED_METAL = frozenset((
    "PIPEWAL1", "PIPEWAL2", "SHAWN2", "SUPPORT3", "STARTAN3", "STARG1",
    "SPACEW2", "COMPTALL", "COMPSTA1", "COMPSTA2", "SPCDOOR2", "STEP1", "STEP4", "STEP5", "STEPLAD1",
    "METAL3", "METAL4", "DOORBLU2", "DOORRED2", "DOORYEL2",
    "MIDBARS1", "MIDGRATE", "MIDBRN1", "MIDBRONZ", "MIDSPACE",
    "BRNSMAL2", "BRNSMALR", "BRNSMALL", "BRNSMALC",
))


def _smooth(a, lo, hi):
    x = np.clip((a - lo) / (hi - lo), 0, 1)
    return x * x * (3 - 2 * x)


def _mask(values, size):
    return (
        np.asarray(
            Image.fromarray(np.uint8(np.clip(values, 0, 1) * 255), "L").resize(
                size, Image.Resampling.BILINEAR
            ),
            dtype=np.float32,
        )
        / 255
    )


def _family(name, kind, original):
    if kind == "flat":
        if name == "GRNLITE1":
            return "molded plastic"
        if name in ("FLAT1_3", "FLAT1", "FLOOR0_5", "FLOOR0_7", "FLAT3"):
            return "metal"
        if name in ("FLAT20", "FLAT9", "FLAT18"):
            return "stone / concrete"
        return original
    if (
        name.startswith(("BIGDOOR5", "BIGDOOR6", "BIGDOOR7", "WOODMET"))
        or name == "DOOR1"
    ):
        return "wood"
    if name in ("EXITDOOR", "ZELDOOR", "PLAT1", "MIDBRN1", "MIDBRONZ", "ZZWOLF11"):
        return "metal"
    if name.startswith("CRAT"):
        return "painted panels"
    if name in ("BRWINDOW", "ZZWOLF10", "SP_HOT1"):
        return "brick / mortar"
    if name in (
        "GRAY1",
        "GRAY2",
        "GRAY4",
        "GRAY5",
        "GRAY7",
        "GRAYBIG",
        "GRAYTALL",
        "ZZWOLF1",
        "ZZWOLF2",
        "ZZWOLF9",
    ):
        return "stone / concrete"
    if name in ("ZZZFACE3", "ZZZFACE4", "ZZZFACE5"):
        return "organic"
    if name in ("ZZZFACE6", "ZZZFACE7", "ZZZFACE8", "ZZZFACE9") or name.startswith(
        ("TEKBRON", "TEKWALL", "SPACEW2")
    ):
        return "painted technology"
    if name in ("SW1METAL", "SW2METAL"):
        return "metal"
    return original


def _formed_normal(field, pixels, size):
    # The registered height lives at two samples per source texel. Resample
    # periodically to the PBR layer size so narrow folds remain well defined.
    h, w = field.shape
    padded = Image.fromarray(np.pad(field, 1, mode="wrap").astype(np.float32))
    fitted = np.asarray(padded.resize(size, Image.Resampling.BILINEAR, box=(1, 1, w + 1, h + 1)))
    dx = (np.roll(fitted, -1, 1) - np.roll(fitted, 1, 1)) * (0.28 * size[0] / pixels.shape[1])
    dy = (np.roll(fitted, -1, 0) - np.roll(fitted, 1, 0)) * (0.28 * size[1] / pixels.shape[0])
    return _normal_bytes(np.stack((-dx, dy, np.ones_like(dx)), axis=2))


def _normal_bytes(normal):
    normal /= np.linalg.norm(normal, axis=2, keepdims=True)
    return np.uint8(np.rint(np.clip(normal * 127 + 128, 0, 255)))


def _registered_wall_normal(name, pixels, family, context, normal):
    from relief_wall_profiles import formed_hardware, height_map, masked_wall_field

    formed = formed_hardware(name, pixels.shape[:2])
    if formed is None:
        encoded, _ = height_map({"name": name, "pixels": pixels}, family, context)
        if encoded is None:
            field = masked_wall_field(name, pixels)
            if field is None:
                return None
        else:
            field = (encoded.astype(np.float32) - 128) / 255
    else:
        field, _ = formed

    return _formed_normal(field, pixels, (normal.shape[1], normal.shape[0]))


def _stone_normal(surface, detail, strength):
    tangent = (surface.astype(np.float32) - 128) / 127
    tangent[:, :, :2] += strength * (detail[:, :, :2].astype(np.float32) - 128) / 127
    return _normal_bytes(tangent)


def _entryway_wall_finish(name, pixels, family, context, normal, lum, neutral, metal, rough):
    surface = _registered_wall_normal(name, pixels, family, context, normal)
    if surface is None:
        return None
    if name in ENTRYWAY_MASONRY:
        # Retain a little mineral grain over the registered joints and fractures.
        surface = _stone_normal(surface, normal, 0.18)
        return surface, np.zeros_like(lum), 0.89 - 0.13 * lum, "dry mineral face and recessed joints"
    if name in ENTRYWAY_BROWN_PANELS:
        rows = (np.arange(normal.shape[0], dtype=np.float32)[:, None] + 0.5) * pixels.shape[0] / normal.shape[0]
        band = 18 if name == "BROWN1" else 32
        trim = 1 - _smooth(rows, band - 3, band + 2)
        return (surface, trim * (0.08 + 0.26 * neutral),
                0.87 - 0.08 * lum - 0.22 * trim, "weathered panels with separate folded trim")
    if name in ENTRYWAY_SWITCHES:
        return surface, 0.77 * metal, np.maximum(rough, 0.49), "switch housing and dry painted backing"
    if name in ("BRNSMAL1", "MIDBARS3"):
        return surface, 0.22 + 0.24 * neutral, 0.62 - 0.13 * lum, "oxidized steel rails and bevels"

    steel = neutral * _smooth(lum, 0.035, 0.25)
    if name in ("LITE5", "EXITDOOR"):
        steel *= 1 - _smooth(lum, 0.56, 0.83)
    return (surface, 0.53 * steel, 0.82 - 0.24 * steel - 0.07 * lum,
            "satin frames and matte equipment faces")


def _stock_wall_finish(name, pixels, family, context, normal, lum, neutral):
    surface = _registered_wall_normal(name, pixels, family, context, normal)
    if surface is None:
        return None
    if name in REVIEWED_STONE:
        return (_stone_normal(surface, normal, 0.14), np.zeros_like(lum), 0.90 - 0.16 * lum,
                "dry masonry with recessed joints")
    if name in ("PIPEWAL1", "PIPEWAL2", "SPACEW2", "SUPPORT3"):
        return surface, 0.27 + 0.20 * neutral, 0.66 - 0.15 * lum, "oxidized fittings and satin metal"
    if name == "SHAWN2":
        return surface, 0.54 + 0.09 * neutral, 0.59 - 0.16 * lum, "lightly brushed steel"
    steel = neutral * _smooth(lum, 0.035, 0.28)
    if name == "SPCDOOR2":
        steel *= 1 - _smooth(lum, 0.65, 0.87)
    return surface, 0.45 * steel, 0.81 - 0.26 * steel - 0.055 * lum, "satin metal and dry painted insets"


def _hardware_finish(name, kind, pixels, normal, lum, neutral, metal, context):
    from relief_wall_profiles import formed_hardware

    size = normal.shape[1], normal.shape[0]
    if kind == "flat" and name == "GRNLITE1":
        from relief_flat_profiles import height_map

        plastic = height_map(name, pixels)
        if plastic is None:
            return None
        field = (plastic[0].astype(np.float32) - 128.0) / 255.0
        return (_formed_normal(field, pixels, size), np.zeros_like(lum),
                0.75 + 0.05 * (1 - lum), "matte plastic ceiling and molded covers")
    if kind == "flat" and name in STOCK_FLAT_FINISH and not context.get("pattern_changed"):
        from relief_flat_profiles import height_map

        encoded = height_map(name, pixels)
        if encoded is None or encoded[0] is None:
            return None
        field = (encoded[0].astype(np.float32) - 128.0) / 255.0
        profile, face, sheltered, polished, alloy, exposed = STOCK_FLAT_FINISH[name]
        depth = _mask(field + 0.5, size) - 0.5
        valleys = _smooth(-depth, 0.01, 0.10)
        crests = _smooth(depth, 0.012, 0.11)
        rough = face + sheltered * valleys - polished * crests
        metal = alloy + exposed * neutral
        if name == "GATE3":
            metal *= 1 - _smooth(-depth, 0.02, 0.125)
        return _formed_normal(field, pixels, size), metal, rough, profile
    if kind != "wall":
        return None
    if name in PAINTED_HARDWARE:
        metal, rough = 0.10 * neutral, 0.61 + 0.07 * (1 - lum) - 0.07 * neutral
        profile = "dry painted steel with a satin finish"
    elif name in AGED_HARDWARE:
        metal, rough = 0.24 + 0.15 * metal, 0.60 + 0.035 * (1 - lum) - 0.085 * metal
        profile = "oxidized bronze and pipes with brighter formed edges"
    elif name in STEEL_HARDWARE:
        metal, rough = 0.18 + 0.28 * neutral, 0.60 + 0.04 * (1 - lum) - 0.11 * neutral
        profile = "satin steel with dry painted insets"
        if name == "BIGDOOR1":
            # Give the gray stamped steel a tighter highlight while retaining
            # the dry finish of the colored UAC stripe and logo.
            exposed_steel = _smooth(neutral, 0.45, 0.95)
            metal += 0.02 * exposed_steel
            rough -= 0.025 * exposed_steel
            profile = "lightly polished steel with a dry painted UAC stripe"
    else:
        return None
    formed = formed_hardware(name, pixels.shape[:2])
    if formed is not None:
        normal = _formed_normal(formed[0], pixels, size)
        if name in AGED_HARDWARE:
            tangent = (normal[:, :, :2].astype(np.float32) - 128) / 127
            slope = np.hypot(tangent[:, :, 0], tangent[:, :, 1])
            rough -= 0.105 * metal * _smooth(slope, 0.035, 0.18)
    else:
        # Dense circuitry and printed wear lack a single fitted plate shape.
        # Subdue the varying micro-normal so its sheen stays with the surface.
        micro = (normal.astype(np.float32) - 128.0) / 127.0
        micro[:, :, :2] *= 0.20
        normal = _normal_bytes(micro)
    return normal, metal, rough, profile


def build_channels(pixels, name, kind, original_family, context=None):
    """Return five PIL auxiliary maps and honest profile/mask metadata.

    Optional native-resolution switch_mask is the composited device-patch alpha;
    paired_pixels is the matching SW1/SW2 state. Reviewed device patches may
    supply switch_alloy='bronze'. Neither changes source albedo.
    """
    context = context or {}
    name = name.upper()
    family = _family(name, kind, original_family)
    maps, interpretation, properties = base.maps_for(pixels, family)
    size = maps["normal"].size
    rgba = (
        np.asarray(
            Image.fromarray(pixels).resize(size, Image.Resampling.BICUBIC),
            dtype=np.float32,
        )
        / 255
    )
    rgb = rgba[:, :, :3]
    lum = rgb[:, :, 0] * 0.2126 + rgb[:, :, 1] * 0.7152 + rgb[:, :, 2] * 0.0722
    maximum, minimum = rgb.max(2), rgb.min(2)
    chroma = (maximum - minimum) / np.maximum(maximum, 0.04)
    visible = rgba[:, :, 3] > 0.5
    neutral = (1 - _smooth(chroma, 0.16, 0.42)) * _smooth(maximum, 0.025, 0.11)
    # This hue mask is consumed only by reviewed bronze profiles. Normalizing
    # the hue differences keeps shaded copper/bronze from turning dielectric;
    # the small near-black gate still excludes actual black holes/background.
    copper = (
        _smooth((rgb[:, :, 0] - rgb[:, :, 2]) / np.maximum(maximum, 0.01), 0.10, 0.35)
        * _smooth((rgb[:, :, 1] - rgb[:, :, 2]) / np.maximum(maximum, 0.01), 0.04, 0.18)
        * _smooth(maximum, 0.01, 0.05)
    )
    colored_paint = _smooth(chroma, 0.35, 0.65)
    metal = np.asarray(maps["metallic"], dtype=np.float32) / 255
    rough = np.asarray(maps["roughness"], dtype=np.float32) / 255
    hardware = np.zeros_like(lum)
    actuator = np.zeros_like(lum)
    profile = family
    correction = "Base family-guided interpretation retained"
    switch = kind == "wall" and name.startswith(("SW1", "SW2"))
    if switch:
        native_mask = context.get("switch_mask")
        partner = context.get("paired_pixels")
        if native_mask is not None:
            hardware = _mask(native_mask, size)
        elif partner is not None and partner.shape == pixels.shape:
            changed = np.any(pixels != partner, axis=2)
            yy, xx = np.where(changed)
            if len(xx):
                margin = max(3, round(min(pixels.shape[:2]) * 0.07))
                native_mask = np.zeros(pixels.shape[:2], dtype=np.float32)
                native_mask[
                    max(0, yy.min() - margin) : yy.max() + margin + 1,
                    max(0, xx.min() - margin) : xx.max() + margin + 1,
                ] = 1
                hardware = _mask(native_mask, size)
        if partner is not None and partner.shape == pixels.shape:
            actuator = _mask(np.any(pixels != partner, axis=2).astype(np.float32), size)
        bronze_relief = context.get("switch_alloy") == "bronze" or any(
            token in name[3:] for token in ("GARG", "LION", "SATYR")
        )
        # Copper-colored bronze is not paint when source-device ownership has
        # qualified that alloy. Paired changed actuator pixels always override
        # this exception, so colored eyes/buttons cannot become metal by tint.
        qualified_copper = copper if bronze_relief else np.zeros_like(copper)
        actuator = np.maximum(
            actuator, colored_paint * hardware * (1 - qualified_copper)
        )
        if any(token in name[3:] for token in ("SKIN", "SKULL")):
            metal[:] = 0
            profile = "organic / bone switch; nonmetal"
            correction = (
                "Flesh/bone switch art stays dielectric; no blanket metal overlay"
            )
        else:
            substrate = np.maximum(neutral, copper if bronze_relief else 0)
            if family != "metal":
                metal[:] = 0
            else:
                metal = 0.96 * neutral
            plate = hardware * substrate * (1 - actuator)
            metal = np.maximum(metal * (1 - actuator), 0.94 * plate)
            polish = 0.24 + 0.16 * (1 - lum) + 0.13 * (1 - substrate)
            rough = rough * (1 - plate) + polish * plate
            rough = rough * (1 - actuator) + (0.38 + 0.12 * (1 - lum)) * actuator
            profile = "source-masked switch housing + dielectric actuator"
            correction = "Actual switch patch/paired state localizes metal housing; shaded steel remains metal and colored/changed actuator pixels remain dielectric"
            if native_mask is None:
                correction += (
                    "; no switch localization available, conservatively retain backing"
                )
    elif kind == "wall" and (
        name.startswith(("BIGDOOR5", "BIGDOOR6", "BIGDOOR7", "WOODMET"))
        or name == "DOOR1"
    ):
        # Gray iron straps/rims contrast with warm brown wood in these reviewed
        # source textures. No name-only whole-leaf metal fill is introduced.
        hardware = neutral
        metal = 0.93 * hardware
        rough = rough * (1 - hardware) + (0.28 + 0.22 * (1 - lum)) * hardware
        profile = "wood leaf with neutral iron hardware"
        correction = "Warm wood stays dielectric; existing gray straps/rims get rough metal response"
    elif name == "BRWINDOW" and kind == "wall":
        y = np.linspace(0, 1, size[1])[:, None]
        hardware = neutral * _smooth(y, 0.42, 0.60)
        metal = 0.90 * hardware
        rough = rough * (1 - hardware) + (0.27 + 0.22 * (1 - lum)) * hardware
        profile = "brick backing / lower neutral window grille"
        correction = (
            "Brick remains dielectric; only lower neutral grille colors receive metal"
        )
    elif family == "metal":
        bronze = name.startswith(("BRONZE", "MIDBRONZ", "TEKBRON")) or name == "FLAT1_3"
        body = np.maximum(neutral, copper if bronze else 0)
        # Bare dark steel remains metal; highly colored stripes/labels are paint.
        # Oxide/dirt may remain nonmetal. Copper tint is explicitly profile-gated.
        metal = 0.96 * body
        rough = 0.23 + 0.23 * (1 - lum) + 0.17 * (1 - body)
        hardware = body
        profile = "bare metal body / dielectric paint and oxidation"
        correction = "Metal body is independent of high brightness; low-chroma steel and explicit bronze receive spatially varying polish"
    elif kind == "wall" and (
        name.startswith(("TEKBRON", "TEKWALL", "SPACEW2"))
        or name in ("ZZZFACE6", "ZZZFACE7", "ZZZFACE8", "ZZZFACE9")
    ):
        body = np.maximum(neutral, copper if name.startswith("TEKBRON") else 0)
        hardware = body
        metal = 0.91 * body
        rough = 0.29 + 0.23 * (1 - lum) + 0.19 * (1 - body)
        profile = "machinery / dielectric screens and colored insulation"
        correction = "Neutral machinery and explicit bronze are metal; colored screen/insulation art stays dielectric"
    elif kind == "wall" and name.startswith("CRAT"):
        edge = np.abs(lum - base.blur(lum, max(1, min(size) / 80)))
        hardware = neutral * _smooth(edge, 0.018, 0.075)
        metal = 0.88 * hardware
        rough = rough * (1 - hardware) + (0.31 + 0.19 * (1 - lum)) * hardware
        profile = "painted industrial crate / exposed neutral frame detail"
        correction = "Crate panels are painted dielectrics, not wood; neutral frame/edge details may expose metal"
    elif family in (
        "stone / concrete",
        "carved stone",
        "brick / mortar",
        "wood",
        "organic",
        "fabric",
        "vegetation",
        "lava crust",
        "sky / static artwork",
        "liquid / static sample",
    ):
        metal[:] = 0
    normal = np.asarray(maps["normal"]).copy()
    ao = np.asarray(maps["ao"]).copy()
    finish = None
    if kind == "wall" and not context.get("pattern_changed") and (
        name in ENTRYWAY_MASONRY or name in ENTRYWAY_BROWN_PANELS or
        name in ENTRYWAY_FRAMED_PANELS or name in ENTRYWAY_SWITCHES
    ):
        finish = _entryway_wall_finish(name, pixels, family, context, normal, lum, neutral, metal, rough)
    elif kind == "wall" and not context.get("pattern_changed"):
        if name in REVIEWED_STONE or name in REVIEWED_METAL:
            finish = _stock_wall_finish(name, pixels, family, context, normal, lum, neutral)
        elif switch and native_mask is not None and 0 < native_mask.mean() <= 0.55:
            # Composite switches use the same independent case geometry for
            # both their height and normal. Pair colours never carve the face.
            surface = _registered_wall_normal(name, pixels, family, context, normal)
            if surface is not None:
                normal = surface
    if finish is None:
        finish = _hardware_finish(name, kind, pixels, normal, lum, neutral, metal, context)
    if finish is not None:
        normal, metal, rough, profile = finish
        ao = np.uint8(np.rint(0.33 * ao + 0.67 * 255.0))
        correction = "Calibrated surface finish retains diffuse response and follows the authored relief"
    metal = np.clip(metal, 0, 0.97)
    rough = np.clip(rough, 0.20, 0.96)
    metal[~visible] = 0
    rough[~visible] = 1
    normal[~visible] = (128, 128, 255)
    ao[~visible] = 255
    maps["normal"] = Image.fromarray(normal, "RGB")
    maps["ao"] = Image.fromarray(ao, "L")
    maps["metallic"] = Image.fromarray(np.uint8(metal * 255), "L")
    maps["roughness"] = Image.fromarray(np.uint8(rough * 255), "L")
    spec = np.clip(0.12 + 0.50 * metal + 0.12 * (1 - rough), 0.08, 0.80)
    spec[~visible] = 0.08
    maps["specular"] = Image.fromarray(np.uint8(spec * 255), "L")
    selected = metal[visible]
    stats = dict(
        mean_metallic=round(float(selected.mean()), 4) if selected.size else 0,
        mean_roughness=round(float(rough[visible].mean()), 4) if selected.size else 1,
        metallic_fraction=(
            round(float((selected > 0.5).mean()), 4) if selected.size else 0
        ),
        hardware_fraction=(
            round(float((hardware[visible] > 0.5).mean()), 4) if selected.size else 0
        ),
        actuator_fraction=(
            round(float((actuator[visible] > 0.5).mean()), 4) if selected.size else 0
        ),
        mask_source=(
            "composited source patch alpha"
            if context.get("switch_mask") is not None
            else (
                "paired SW1/SW2 bounds"
                if context.get("paired_pixels") is not None
                else "reviewed profile/color features"
            )
        ),
    )
    if switch:
        stats["switch_alloy"] = (
            "bronze" if bronze_relief else "neutral steel / unspecified"
        )
    return maps, dict(
        family=family,
        profile=profile,
        mask_stats=stats,
        mean_metallic=stats["mean_metallic"],
        mean_roughness=stats["mean_roughness"],
        normal_extent=list(size),
        interpretation=interpretation + "; " + correction,
        limitation="Procedural semantic/feature interpretation, not recovered artist segmentation",
    )


def cpu_controls():
    pixels = np.full((32, 32, 4), (32, 32, 32, 255), dtype=np.uint8)
    pixels[:, 16:] = (80, 6, 6, 255)
    context = {"switch_mask": np.ones((32, 32), dtype=np.float32)}
    maps, _ = build_channels(pixels, "SW1METAL", "wall", "mixed switch panel", context)
    m = np.asarray(maps["metallic"])
    assert m[:, : m.shape[1] // 2 - 4].mean() > 180
    assert m[:, m.shape[1] // 2 + 4 :].max() < 5
    for family, name in (
        ("wood", "WOOD1"),
        ("stone / concrete", "STONE2"),
        ("organic", "SKIN2"),
    ):
        maps, _ = build_channels(pixels, name, "wall", family)
        assert np.asarray(maps["metallic"]).max() == 0, name
    wood = np.full((32, 32, 4), (110, 65, 30, 255), dtype=np.uint8)
    wood[:, 8:12] = (80, 80, 80, 255)
    maps, _ = build_channels(wood, "WOODMET1", "wall", "wood")
    m = np.asarray(maps["metallic"])
    assert m[:, :20].max() < 5 and m[:, 36:44].mean() > 180
    transparent = pixels.copy()
    transparent[:16, :, 3] = 0
    maps, _ = build_channels(transparent, "DOOR3", "wall", "metal")
    assert np.asarray(maps["metallic"])[:50].max() == 0
    bronze = np.full((32, 32, 4), (120, 75, 30, 255), dtype=np.uint8)
    bronze[:, 20:] = (160, 12, 12, 255)
    pair = bronze.copy()
    pair[:, 20:] = (12, 160, 12, 255)
    ctx = {"switch_mask": np.ones((32, 32), dtype=np.float32), "paired_pixels": pair}
    maps, _ = build_channels(bronze, "SW1WOOD", "wall", "wood", ctx)
    assert np.asarray(maps["metallic"])[:, :60].max() == 0
    ctx["switch_alloy"] = "bronze"
    maps, _ = build_channels(bronze, "SW1WOOD", "wall", "wood", ctx)
    m = np.asarray(maps["metallic"])
    assert m[:, :60].mean() > 200
    assert m[:, 90:].max() == 0
    dark_bronze = np.full((32, 32, 4), (24, 15, 5, 255), dtype=np.uint8)
    maps, _ = build_channels(
        dark_bronze,
        "SW1WOOD",
        "wall",
        "wood",
        {"switch_mask": np.ones((32, 32)), "switch_alloy": "bronze"},
    )
    assert np.asarray(maps["metallic"]).mean() > 225
    maps, _ = build_channels(dark_bronze, "WOOD1", "wall", "wood")
    assert np.asarray(maps["metallic"]).max() == 0
    for image in maps.values():
        image.load()
    n = np.asarray(maps["normal"]).astype(float)
    length = np.linalg.norm((n - 128) / 127, axis=2)
    assert np.all((length > 0.98) & (length < 1.02))
    return {
        "status": "PASS",
        "controls": [
            "dark gray switch housing metal",
            "dark red button dielectric",
            "wood/stone/flesh nonmetal",
            "wood leaf versus iron band",
            "transparent exterior conservative",
            "bronze requires reviewed alloy context",
            "paired red/green actuator remains dielectric on bronze housing",
            "dark bronze stays metal under qualified alloy",
            "same dark brown hue stays nonmetal wood without alloy context",
            "normal finite/unit within quantization",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(cpu_controls(), indent=2))
