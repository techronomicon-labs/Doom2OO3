"""Structural-height profiles for the effective DBP50 walls and flats."""

import re

import numpy as np

from relief_wall_profiles import WallFeatures, blur, encode, mortar, panels, planks, smoothstep, switch_panel
from structural_relief import HeightTile, smooth_band


FLAT_FAMILIES = {
    "metal": "DBMET07 DBMET08 DBMET09 DBMET10 DBCL_M2 DB_1005 DB_1007 DB_1009 DB_1010 "
             "DBZARDI DB_1008 DKTX054F D26F60 D26F60A D28F073 D28F074 D_1001 D_1009",
    "painted technology": "D_4002 D_4003 D_4004 D_4009 D_4010 D_4012 D_4014 D_4018 D_4019",
    "brick / mortar": "DIAMOND4 DIAMOND6 DB0006 DB00O6 DB0008 DB0009 DB0010 DB0013 DB0014 "
                      "DB2863 DB2864 DB286E DBTITAN DBTIT4N DBFGE01 DBFGE03 DBKBFLA6 DBKBFL6 "
                      "D26F16 D26F32 D26F55 D28F119 D31F006 D2_FLAT2 D2_FLAT3 DB_FLT22 "
                      "D_1002 D_10O2 DBX0281 DBX028I DNOX DNOX1 DNOX2 DNOX3 DNOX4 "
                      "DGYPT DGYPT1 DGYPT2 DGYPT3 D_2000 DB_2000 DBOB3_7 DFBKV LEAFID",
    "wood": "DBCRT DB0002 DB00O2 DESKWOOD D_2010",
    "stone / concrete": "DBCTY5 DBR6_1 DBR7_1 DB_1004 DBDR2_1 DBDR2_2 DBDR22 "
                        "DB_10O4 DNSTON03 DNSTON04 D25QF32 D26F01 D26F10 D26F45",
}

WALL_FAMILIES = {
    "brick / mortar": "DBLD DBLD1 DBLD6 DBLD7 DBLD7A DBLD8 DBLD10 DBLD11 DBLD12 DB0WALL5 "
                      "DB0WALL6 D26W308 D26W310 D26W311 DPLU DPLU1 DMET DMET1 DMET2 "
                      "DBED2 DBED3 DBP_0072 DBP_0203 DBP_0204 DBP_0205 DEDBRK DEDBRK1 "
                      "DB_0102 DB_0112 DB_0113 DB_0114 DB_0126 DB_0127 DB_0128",
    "wood": "D20CRA5 D20CRA6 D20C555 D20CR55 DB29_043 DB29_044 DB29_045 DB29_046 "
             "DB29_047 DB29_048 DB29_049 DB29_050 DB29_051 DB29_052 DB29_053 DB29_058 "
             "DB29_059 DB29_096 DB29_097 DWOOD24 DWOOD25 DWOODA DWOODB DTREE DTREE1",
    "metal": "D26W022 D26W032 D26W127 D26W130 D26W132 D26W152 DWPZ DBCGMETL DBCGMET2 "
              "DBCGME33 DBCGMET3 DBCGMET4 DBCGPIPE DBINTLIT DBINTL1T DBOD1341 DBOD1345 "
              "DBPYP DBPYP1 DPYP DRKPIP DBGRG DBP_T000 DBP_T001 DBP_T002",
    "stone / concrete": "DBLD2 DBLD3 DCONC DCONC1 DBLIN DBLIN1 DB_0101 DB_0107 DB_0108 "
                        "DBPVC200 DBPVC201 DBP_C200 DBP_C201 DBP_C202 DBP_C213 DBP_C222 "
                        "DBP_C2O0 DBP_C2OO DBP_I105 DBP_I106 DBP_I109 DBP_I110 DBP_I111 "
                        "DBP_I112 DBP_I113 DBP_I407 DBP_I408 DBP_I409 DBP_I410",
}


def _names_by_family(groups):
    return {name: family for family, names in groups.items() for name in names.split()}


FLAT_FAMILY = _names_by_family(FLAT_FAMILIES)
WALL_FAMILY = _names_by_family(WALL_FAMILIES)


def family_of(name, kind, default):
    """Return the DBP50 backing material for its effective palette and artwork."""
    if kind == "flat":
        if name in FLAT_FAMILY:
            return FLAT_FAMILY[name]
        if name.startswith(("DBNAT", "DBNA", "DB_GR", "DBAF_GR", "DBNT", "DBGRUND", "DBGROUND")):
            return "vegetation"
    else:
        if name in WALL_FAMILY:
            return WALL_FAMILY[name]
        if name.startswith(("RSKY", "SKY")):
            return "sky / static artwork"
        if name.startswith(("WFALL", "SFALL", "BFALL")):
            return "liquid / static sample"
        if name.startswith(("DBPOST", "DPOST", "DBCITSG", "DBCITSNN", "DBSIGN", "DLIQ", "D27PIC", "D27PI")):
            return "printed artwork"
        if name.startswith(("D26DOR", "SUPP", "DBRAIL", "DB22TEK", "D26LIT")):
            return "metal"
        if name.startswith(("DBBRK", "DB_BST", "DBCITBL", "DCINDR")):
            return "brick / mortar"
        if name.startswith(("DB22NAT", "DBPVIN", "DBLEAF", "DB40TX", "DBGNATR", "DBGRAS", "DBTREE", "DBCOV")):
            return "vegetation"
    return default


def neutral_reason(row):
    name, family, pixels = row["name"], row["family"], row["pixels"]
    if row["placeholder"]:
        return "Texture table placeholder"
    if family == "sky / static artwork":
        return "Sky image"
    if family == "liquid / static sample" or re.fullmatch(
        r"(?:DBRAIN|BLODGR|BLODRIP|SLADRIP|GSTFONT|FIRE|ROCKRED)[A-Z0-9]+", name
    ):
        return "Liquid or animated effect without stationary geometry"
    if family == "printed artwork" or name.startswith(("ALPHA", "DBGRAFI", "DBGRF")):
        return "Printed or painted flat image"
    if not np.all(pixels[:, :, 3] == 255):
        return "Masked wall silhouette"
    if np.max(np.ptp(pixels[:, :, :3], axis=(0, 1))) <= 2:
        return "Uniform source art"
    return None


def _fitted_floor(name):
    if name in ("DIAMOND4", "DIAMOND6"):
        # The two palette variants draw joints at the same 16-texel
        # diagonal repeat. Use the center of the actual dark source pixels.
        tile = HeightTile(64, 64)
        plus, minus = (8.65, 0.35) if name == "DIAMOND6" else (9.0, 0.0)
        rising = np.abs(tile.wrapped_offset(tile.u + tile.v, plus, 16))
        falling = np.abs(tile.wrapped_offset(tile.u - tile.v, minus, 16))
        tile.values -= 0.42 * smooth_band(np.minimum(rising, falling), 0.38, 2.9)
        return tile.values, "Diamond tile bevels and diagonal grout"
    if name == "DNOX":
        tile = HeightTile(64, 64)
        tile.joints((0, 32), (31.35, 63.35), depth=0.42, width=2.4)
        return tile.values, "Aligned large stone floor joints"
    if name in ("DBFGE01", "DBFGE03"):
        tile = HeightTile(64, 64)
        joints = (15.5, 31.5, 47.5, 63.5)
        tile.joints(joints, joints, depth=0.34, width=1.8)
        return tile.values, "Mossed square paving joints"
    return None


def _foliage(features):
    # Moss and ivy are local broad color groups. Avoid embossing the noise
    # inside a leaf or adding relief to an overall green color grade.
    red, blue = features.hue.transpose(2, 0, 1)
    green = smoothstep(np.minimum(-red, -blue), 0.012, 0.18)
    cover = smoothstep(blur(green, 2), 0.13, 0.69)
    growth = np.maximum(cover - 0.65 * blur(cover, 5), 0.0)
    return 0.32 * growth + 0.25 * features.terrain()


def _fine_aggregate(features):
    # DBOB3_7 uses a narrow dark palette. Coherent clusters survive the
    # first blur, while isolated palette stipple has no reliable relief.
    tone = features.tone
    low, high = np.percentile(tone, (8, 92))
    local = blur(tone, 1)
    curvature = (local - blur(local, 2)) / max(0.054, high - low)
    ridges = smoothstep(curvature, 0.033, 0.16)
    cavities = smoothstep(-curvature, 0.044, 0.20)
    return blur(0.17 * ridges - 0.14 * cavities, 1)


def _profile(row, context, stock_profile):
    name, family, pixels = row["name"], row["family"], row["pixels"]
    reason = neutral_reason(row)
    if reason:
        return None, reason, "neutral"
    if not row["pattern_changed"]:
        return stock_profile(row, family, context)

    fitted = _fitted_floor(name) if row["kind"] == "flat" and pixels.shape[:2] == (64, 64) else None
    if fitted is not None:
        height, label = fitted
        return encode(height), label, "DBP50 authored height"

    features = WallFeatures(pixels, context.get("paired_pixels"))
    if row["kind"] == "flat" and name == "DBOB3_7":
        height, label = _fine_aggregate(features), "Coherent shallow aggregate in the dark floor"
    elif row["kind"] == "wall" and name.startswith(("SW1", "SW2", "SW01", "SW02")):
        height, label = switch_panel(features, context), "Switch housing and shared backing seams"
    elif family == "brick / mortar":
        height, label = mortar(features), "Masonry courses with recessed joints"
    elif family == "wood":
        height, label = planks(features, name) + 0.17 * features.terrain(), "Timber joints and worn grain"
    elif family in ("metal", "painted panels", "painted technology"):
        height, label = panels(features, rails=True) + 0.15 * features.terrain(), "Panel joins, fittings and recesses"
    elif family == "vegetation":
        height, label = _foliage(features), "Raised contiguous foliage and surface contours"
    elif family in ("stone / concrete", "carved stone", "organic"):
        height = 0.66 * mortar(features) + 0.34 * features.terrain()
        label = "Mineral contours and coherent surface joins"
    else:
        height = 0.83 * panels(features, rails=True) + 0.30 * features.terrain()
        label = "Coherent recessed seams and formed surface contours"

    if np.count_nonzero(np.abs(height - np.median(height)) >= 0.026) < max(12, height.size // 450):
        return None, "No coherent structural detail in effective artwork", "neutral"
    return encode(height), label, "DBP50 material profile"


def _switch_partner(name):
    if name in ("SW01", "SW02"):
        return "SW02" if name == "SW01" else "SW01"
    if name.startswith(("SW1", "SW2")):
        return "SW" + ("2" if name[2] == "1" else "1") + name[3:]
    return None


def height_profiles(rows, contexts, stock_profile):
    """Resolve every effective material with identical geometry for switch states."""
    by_key = {(row["kind"], row["name"]): row for row in rows}
    result = {}
    for key, row in by_key.items():
        if key in result:
            continue
        context = contexts.get(key, {})
        partner_key = ("wall", _switch_partner(row["name"]))
        partner = by_key.get(partner_key) if row["kind"] == "wall" else None
        if (partner is not None and partner_key not in result and neutral_reason(row) is None
                and neutral_reason(partner) is None and row["pixels"].shape == partner["pixels"].shape):
            if partner["pattern_changed"] and not row["pattern_changed"]:
                row, partner = partner, row
                context = contexts.get(partner_key, {})
            context = dict(context, paired_pixels=partner["pixels"])
            result[key] = result[partner_key] = _profile(row, context, stock_profile)
        else:
            result[key] = _profile(row, context, stock_profile)
    return result
