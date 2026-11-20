// PF-011: inherited renderer calibration. These are compatibility scalars,
// not photometric units; see PF-011-LIGHTING-COMPATIBILITY-CONTRACT.md.
const float LIGHT_COMPAT_SUN_ATTENUATION_RADIUS = 1000000.0;
const float LIGHT_COMPAT_PBR_BRIGHTNESS_SCALE = 2.5;
const float LIGHT_COMPAT_PBR_AMBIENT_SCALE = 2.25;
const float LIGHT_COMPAT_PBR_METAL_SPECULAR_SCALE = 0.40;

float distanceAttenuation(float dist, float radius, float strength, float linearity)
{
	if (LIGHT_ATTENUATION_INVERSE_SQUARE)
	{
		// The far-away sunlight proxy bypasses local-light falloff.
		if (radius >= LIGHT_COMPAT_SUN_ATTENUATION_RADIUS) return 1.0;
		float a = dist / radius;
		float b = clamp(1.0 - a * a * a * a, 0.0, 1.0);
		return mix((b * b) / (dist * dist + 1.0) * strength, clamp((radius - dist) / radius, 0.0, 1.0), linearity);
	}
	else
	{
		return clamp((radius - dist) / radius, 0.0, 1.0);
	}
}

bool UsePackedLight(DynLightInfo light)
{
	return (light.flags & LIGHTINFO_STAGE_B_EMITTER) == 0 ||
		(STAGE_B_WORLD_LIGHTING && uStageBIntensity > 0.0);
}

bool UseStructuralRelief(DynLightInfo light)
{
	return (light.flags & (LIGHTINFO_FLASHLIGHT | LIGHTINFO_SUN)) == LIGHTINFO_FLASHLIGHT ||
		(STAGE_B_WORLD_LIGHTING && (light.flags & LIGHTINFO_STAGE_B_EMITTER) != 0);
}

#if !defined(SIMPLE)
float MapLightVisibility(DynLightInfo light, vec3 position, bool flashlight)
{
	// Trace from the geometric receiver, before relief/normal mapping.
	float coordinateScale = max(max(abs(position.x), abs(position.y)), abs(position.z));
	float bias = max(1.0 / 64.0, coordinateScale * 2.3841858e-7);
	// Unlit sprite normals may be zero or undefined after normalization.
	vec3 normal = flashlight && LIGHT_NONORMALS ? vec3(0.0) : vWorldNormal.xyz;
	if (flashlight && dot(normal, light.pos.xyz - position) < 0.0)
		normal = -normal; // Either face of a masked wall can receive the beam.
	vec3 origin = position + normal * bias;
	vec3 toLight = light.pos.xyz - origin;
	float dist = length(toLight);
	if (dist <= 2.0 * bias) return 1.0;
	vec3 dir = toLight / dist;
	return TraceMapHit(origin, dir, dist - bias, light.shadowIndex, flashlight) ? 0.0 : 1.0;
}
#endif

#if !defined(SHADOW_PUPPET_VERTEX_STAGE) && !defined(SIMPLE)
#include <shaders/scene/shadowpuppet_depth.glsl>

// The beam lobes normally share an optical origin. Trace once per fragment
// at that origin and keep the sprite silhouette test independent.
float cachedMapVisibility = -1.0;
vec3 cachedMapOrigin;
int cachedMapGroup;
float cachedPuppetVisibility = -1.0;

float WorldLightVisibility(DynLightInfo light, vec3 position, ivec2 pixel)
{
	float visibility = 1.0;
	if ((light.flags & (LIGHTINFO_POINT_MAP_SHADOW | LIGHTINFO_FLASHLIGHT_MAP_SHADOW)) != 0)
	{
		bool flashlight = (light.flags & LIGHTINFO_FLASHLIGHT_MAP_SHADOW) != 0;
		if (flashlight && cachedMapVisibility >= 0.0 && cachedMapGroup == light.shadowIndex &&
			all(equal(cachedMapOrigin, light.pos.xyz)))
		{
			visibility = cachedMapVisibility;
		}
		else
		{
			visibility = MapLightVisibility(light, position, flashlight);
			if (!flashlight) return visibility;
			cachedMapVisibility = visibility;
			cachedMapGroup = light.shadowIndex;
			cachedMapOrigin = light.pos.xyz;
		}
	}

	if (visibility == 0.0 || (light.flags & LIGHTINFO_SHADOW_PUPPET) == 0 ||
		data[uDataIndex].uShadowPuppetReceiver == 0 || uShadowPuppetTexture <= 0)
		return visibility;

	if (cachedPuppetVisibility < 0.0)
	{
		int image = uShadowPuppetTexture;
		if (uShadowPuppetMode == 1)
		{
			ivec2 size = textureSize(textures[nonuniformEXT(image)], 0);
			if (any(lessThan(pixel, ivec2(0))) || any(greaterThanEqual(pixel, size))) return visibility;
			cachedPuppetVisibility = texelFetch(textures[nonuniformEXT(image)], pixel, 0).r;
		}
		else
		{
			cachedPuppetVisibility = ShadowPuppetDepthVisibility(light, position, image);
		}
	}
	return visibility * cachedPuppetVisibility;
}
#endif

float PackedLightFalloff(DynLightInfo light, float lightDistance)
{
	if ((light.flags & LIGHTINFO_STAGE_B_EMITTER) == 0)
		return distanceAttenuation(lightDistance, light.radius, light.strength, light.linearity);
	if ((light.flags & LIGHTINFO_STAGE_B_DIRECTIONAL) != 0)
		return uStageBIntensity * (1.0 - smoothstep(0.8 * light.radius, light.radius, lightDistance));
	float reach = clamp(1.0 - lightDistance / light.radius, 0.0, 1.0);
	return uStageBIntensity * mix(reach * reach, reach, light.linearity);
}

#ifdef SDVK_STRUCTURAL_RELIEF
float SDVKFullbrightReliefScale(vec4 relief)
{
	if (uLightIndex < 0 || all(equal(relief, vec4(0.0))))
		return 1.0;

	vec3 normal = uSpriteNormal.xyz;
	vec3 displacedNormal = normalize(normal - relief.xyz);
	vec3 position = SDVK_LIGHTING_POSITION;
	vec3 displacedPosition = position + normal * relief.w;
	float contrast = 0.0;
	ivec4 range = getLightRange();
	for (int i = range.x; i < range.y; ++i)
	{
		DynLightInfo light = getLights()[i];
		if ((light.flags & (LIGHTINFO_FLASHLIGHT | LIGHTINFO_SPOT | LIGHTINFO_SUN)) !=
			(LIGHTINFO_FLASHLIGHT | LIGHTINFO_SPOT))
			continue;
		vec3 toLight = light.pos.xyz - position;
		float baseDistance = length(toLight);
		if (baseDistance <= 1e-4 || baseDistance >= light.radius)
			continue;
		vec3 lightDir = toLight / baseDistance;
		float beam = smoothstep(light.spotOuterAngle, light.spotInnerAngle, dot(lightDir, light.spotDir.xyz));
		if (beam <= 0.0)
			continue;
#if !defined(SHADOW_PUPPET_VERTEX_STAGE) && !defined(SIMPLE)
		beam *= WorldLightVisibility(light, pixelpos.xyz, ivec2(gl_FragCoord.xy));
#endif

		vec3 toDisplacedLight = light.pos.xyz - displacedPosition;
		float displacedDistance = length(toDisplacedLight);
		if (displacedDistance <= 1e-4)
			continue;
		if ((light.flags & LIGHTINFO_SHADOWMAPPED) != 0)
			beam *= shadowAttenuation(light.pos.xyz, light.shadowIndex, light.softShadowRadius, light.flags);

		float flatDiffuse = clamp(dot(normal, lightDir), 0.0, 1.0) *
			distanceAttenuation(baseDistance, light.radius, light.strength, light.linearity);
		float displacedDiffuse = clamp(dot(displacedNormal, toDisplacedLight / displacedDistance), 0.0, 1.0) *
			distanceAttenuation(displacedDistance, light.radius, light.strength, light.linearity);
		float strength = dot(light.color.rgb, vec3(0.2126, 0.7152, 0.0722));
		contrast += beam * strength * (displacedDiffuse - flatDiffuse);
	}

	// Fullbright sprites retain their authored light level plus bounded relief contrast.
	return 1.0 + clamp(1.65 * contrast, -0.45, 0.32);
}
#endif

