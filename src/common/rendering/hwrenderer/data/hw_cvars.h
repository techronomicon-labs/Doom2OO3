#pragma once


#include "c_cvars.h"

EXTERN_CVAR(Bool,gl_enhanced_nightvision)
EXTERN_CVAR(Int, screenblocks);
EXTERN_CVAR(Int, gl_texture_filter)
EXTERN_CVAR(Float, gl_texture_filter_anisotropic)
EXTERN_CVAR(Int, gl_texture_format)
EXTERN_CVAR(Bool, gl_usefb)

EXTERN_CVAR(Int, gl_weaponlight)

EXTERN_CVAR (Bool, gl_light_sprites);
EXTERN_CVAR (Bool, gl_light_particles);
EXTERN_CVAR (Int, gl_light_shadows);
EXTERN_CVAR (Int, gl_light_shadow_filter);
EXTERN_CVAR (Int, gl_light_shadow_max_quality);
EXTERN_CVAR (Int, gl_shadowmap_quality);

EXTERN_CVAR(Int, gl_fogmode)
EXTERN_CVAR(Bool,gl_mirror_envmap)

EXTERN_CVAR(Bool,gl_mirrors)
EXTERN_CVAR(Bool,gl_mirror_envmap)
EXTERN_CVAR(Bool, gl_seamless)

EXTERN_CVAR(Float, gl_mask_threshold)
EXTERN_CVAR(Float, gl_mask_sprite_threshold)

EXTERN_CVAR(Int, gl_multisample)

EXTERN_CVAR(Bool, gl_bloom)
EXTERN_CVAR(Float, gl_bloom_amount)
EXTERN_CVAR(Int, gl_bloom_kernel_size)
EXTERN_CVAR(Int, gl_tonemap)
EXTERN_CVAR(Float, gl_exposure)
EXTERN_CVAR(Bool, gl_lens)
EXTERN_CVAR(Float, gl_lens_k)
EXTERN_CVAR(Float, gl_lens_kcube)
EXTERN_CVAR(Float, gl_lens_chromatic)
EXTERN_CVAR(Int, gl_ssao)
EXTERN_CVAR(Int, gl_ssao_portals)
EXTERN_CVAR(Float, gl_ssao_strength)
EXTERN_CVAR(Int, gl_ssao_debug)
EXTERN_CVAR(Bool, gl_shownormals)
EXTERN_CVAR(Float, gl_ssao_bias)
EXTERN_CVAR(Float, gl_ssao_radius)
EXTERN_CVAR(Float, gl_ssao_blur_amount)

EXTERN_CVAR(Int, gl_debug_level)
EXTERN_CVAR(Bool, gl_debug_breakpoint)

EXTERN_CVAR(Bool, gl_brightfog)
EXTERN_CVAR(Bool, gl_lightadditivesurfaces)
EXTERN_CVAR(Bool, gl_notexturefill)

EXTERN_CVAR(Bool, r_radarclipper)
EXTERN_CVAR(Bool, r_dithertransparency)

EXTERN_CVAR(Bool, gl_strict_gldefs)
EXTERN_CVAR(Int, gl_wireframe)
EXTERN_CVAR(Color, gl_wireframecolor)

int get_gl_spritelight();

EXTERN_CVAR(Bool, gl_fakemodellight)
EXTERN_CVAR(Float, gl_fakemodellightintensity)



EXTERN_CVAR(Bool, lm_dynlights)

EXTERN_CVAR(Bool, gl_world_relief)
EXTERN_CVAR(Bool, gl_emitter_lighting)
EXTERN_CVAR(Bool, gl_projectile_map_shadows)
EXTERN_CVAR(Bool, gl_flashlight_map_shadows)
EXTERN_CVAR(Float, gl_flashlight_map_shadow_radius)
EXTERN_CVAR(Int, gl_flashlight_map_shadow_spread)
EXTERN_CVAR(Int, gl_flashlight_map_shadow_style)
EXTERN_CVAR(Int, gl_flashlight_shadow_darkness)
EXTERN_CVAR(Float, gl_emitter_ambient)
EXTERN_CVAR(Float, gl_emitter_ambient_specular)
EXTERN_CVAR(Float, gl_emitter_intensity)
EXTERN_CVAR(Float, gl_shadow_puppet_softness)
EXTERN_CVAR(Float, gl_world_relief_depth)
EXTERN_CVAR(Float, gl_world_relief_orientation)
EXTERN_CVAR(Float, gl_world_relief_exaggeration)
EXTERN_CVAR(Bool, gl_sprite_lighting_relief)
EXTERN_CVAR(Int, gl_flashlight_hotspot)
EXTERN_CVAR(Int, gl_flashlight_unevenness)
EXTERN_CVAR(Float, gl_sprite_lighting_relief_depth)
EXTERN_CVAR(Float, gl_sprite_lighting_relief_orientation)
EXTERN_CVAR(Float, gl_sprite_lighting_relief_exaggeration)

