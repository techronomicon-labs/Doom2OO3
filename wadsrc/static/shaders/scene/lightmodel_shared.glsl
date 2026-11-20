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
float FlashlightShadowVisibility(float visibility)
{
	return max(0.0, mix(1.0, visibility, uFlashlightShadowDarkness));
}

bool MapSegmentBlocked(vec3 start, vec3 end, float bias, int group, bool includeMasked)
{
	vec3 ray = end - start;
	float dist = length(ray);
	return dist > 2.0 * bias && TraceMapHit(start, ray / dist, dist - bias, group, includeMasked);
}

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
	vec3 lamp = light.pos.xyz;
	if (!flashlight || uFlashlightMapShadowRadius <= 0.0)
		return MapSegmentBlocked(origin, lamp, bias, light.shadowIndex, flashlight) ? 0.0 : 1.0;

	// The disk follows the head mount. Aim trims steer the beam lobes within
	// that frame. All primary rays meet at the receiver, giving a hard contact.
	mat3 cameraAxes = transpose(mat3(ViewMatrix));
	vec3 right = normalize(cameraAxes[0]);
	vec3 up = normalize(cameraAxes[1] - right * dot(cameraAxes[1], right));
	right *= uFlashlightMapShadowRadius;
	up *= uFlashlightMapShadowRadius;
	vec3 ray = lamp - origin;
	float dist = length(ray);
	if (dist <= 2.0 * bias) return 1.0;
	// Shorten every ray by the same fraction, preserving the disk and avoiding
	// coincident light-endpoint hits. The receiver was already biased above.
	float fraction = 1.0 - bias / dist;
	if (uFlashlightMapShadowStyle == 2) return SmoothMapVisibility(origin, lamp, right, up, fraction, light.shadowIndex);
	vec3 diskCenter = origin + ray * fraction;
	int activeMask = mapDiskMask, blocked = 0;
	do
	{
		blocked ^= TraceMapDisk(origin, diskCenter, right * fraction, up * fraction, light.shadowIndex, activeMask);
		if (activeMask != mapDiskMask) break;

		// A mixed edge can include samples on the other side of a wall or
		// grate from the mount. A second packet folds those samples back to
		// the centre. It only needs the taps that disagree with the centre.
		activeMask = (blocked & 1) == 0 ? blocked : (mapDiskMask ^ blocked);
		origin = diskCenter = lamp;
		fraction = 1.0;
	} while (activeMask != 0);
	if (uFlashlightMapShadowStyle == 1) return blocked == 0 ? 1.0 : 0.0;
	return 1.0 - float(bitCount(blocked)) / 13.0;
}
#endif

#if !defined(SHADOW_PUPPET_VERTEX_STAGE) && !defined(SIMPLE)
#include <shaders/scene/shadowpuppet_depth.glsl>

// All lobes at one mount share the aperture visibility for this receiver.
float cachedMapVisibility = -1.0;
vec3 cachedMapOrigin;
int cachedMapGroup;
float cachedPuppetVisibility = -1.0;

float WorldLightVisibility(DynLightInfo light, vec3 position, ivec2 pixel)
{
	if ((light.flags & (LIGHTINFO_SHADOW_PUPPET | LIGHTINFO_FLASHLIGHT_MAP_SHADOW)) == 0)
		return (light.flags & LIGHTINFO_POINT_MAP_SHADOW) != 0 ? MapLightVisibility(light, position, false) : 1.0;
	if (uFlashlightShadowDarkness == 0.0) return 1.0;
	float visibility = 1.0;
	if ((light.flags & LIGHTINFO_FLASHLIGHT_MAP_SHADOW) != 0)
	{
		if (cachedMapVisibility >= 0.0 && cachedMapGroup == light.shadowIndex &&
			all(equal(cachedMapOrigin, light.pos.xyz)))
		{
			visibility = cachedMapVisibility;
		}
		else
		{
			visibility = MapLightVisibility(light, position, true);
			cachedMapVisibility = visibility;
			cachedMapGroup = light.shadowIndex;
			cachedMapOrigin = light.pos.xyz;
		}
	}

	if (visibility == 0.0 || (light.flags & LIGHTINFO_SHADOW_PUPPET) == 0 ||
		data[uDataIndex].uShadowPuppetReceiver == 0 || uShadowPuppetTexture <= 0)
		return FlashlightShadowVisibility(visibility);

	if (cachedPuppetVisibility < 0.0)
	{
		int image = uShadowPuppetTexture;
		if (uShadowPuppetMode == 1)
		{
			ivec2 size = textureSize(textures[nonuniformEXT(image)], 0);
			if (any(lessThan(pixel, ivec2(0))) || any(greaterThanEqual(pixel, size))) return FlashlightShadowVisibility(visibility);
			cachedPuppetVisibility = texelFetch(textures[nonuniformEXT(image)], pixel, 0).r;
		}
		else
		{
			cachedPuppetVisibility = ShadowPuppetDepthVisibility(light, position, image);
		}
	}
	return FlashlightShadowVisibility(visibility * cachedPuppetVisibility);
}
#endif

float FlashlightProfileGain(vec3 fromLamp)
{
	// The same angular coordinates modulate every cone in an elliptical beam.
	// These smooth reflector patches are fixed in the lens, including during motion.
	vec2 uv = vec2(dot(fromLamp, uFlashlightLensRight.xyz), dot(fromLamp, uFlashlightLensUp.xyz));
	float core = max(0.0, 1.0 - 3.0 * dot(uv, uv));
	vec2 a = uv - vec2(-0.30, 0.25), b = uv - vec2(0.41, -0.18);
	float bright = max(0.0, 1.0 - dot(a*a, vec2(2.5, 6.0)));
	float shade = max(0.0, 1.0 - dot(b*b, vec2(7.0, 2.5)));
	return (1.0 + uFlashlightLensRight.w * (1.1 * core*core - 0.25)) *
		(1.0 + uFlashlightLensUp.w * (0.32 * bright*bright - 0.48 * shade*shade));
}

float PackedLightFalloff(DynLightInfo light, float lightDistance)
{
	if ((light.flags & LIGHTINFO_STAGE_B_EMITTER) == 0)
	{
		float falloff = distanceAttenuation(lightDistance, light.radius, light.strength, light.linearity);
		if ((light.flags & LIGHTINFO_FLASHLIGHT_PROFILE) != 0)
		{
			vec3 ray = SDVK_LIGHTING_POSITION - light.pos.xyz;
			falloff *= FlashlightProfileGain(ray * inversesqrt(max(dot(ray, ray), 1e-12)));
		}
		return falloff;
	}
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
		if ((light.flags & LIGHTINFO_FLASHLIGHT_PROFILE) != 0)
			beam *= FlashlightProfileGain(-lightDir);
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

