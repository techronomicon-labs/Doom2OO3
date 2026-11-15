
// Check if light is in shadow

float ActorOccluderRayVisibility(vec3 lightPos, vec3 receiver, ActorShadowCaster caster)
{
	// Genuine line-of-light blocker. The blocker is bounded in height and
	// must lie strictly between the actual emitting light and the fragment.
	vec3 ray = receiver - lightPos;
	vec2 d = ray.xz;
	vec2 c = lightPos.xz - caster.center.xz;
	float a = dot(d, d);
	if (a <= 0.0001 || caster.radius <= 0.0 || caster.bottom >= caster.top)
		return 1.0;
	float halfB = dot(c, d);
	float discriminant = halfB * halfB - a * (dot(c, c) - caster.radius * caster.radius);
	if (discriminant <= 0.0)
		return 1.0;
	float root = sqrt(discriminant);
	float entry = max((-halfB - root) / a, 0.002);
	float exit = min((-halfB + root) / a, 0.998);
	if (exit <= entry)
		return 1.0;
	// Do not shadow an actor's own material merely because its surface lies
	// within this coarse geometric blocker; visible sprite shading stays intact.
	vec2 receiverXY = receiver.xz - caster.center.xz;
	if (dot(receiverXY, receiverXY) <= caster.radius * caster.radius &&
		receiver.y >= caster.bottom && receiver.y <= caster.top)
		return 1.0;
	if (lightPos.y >= caster.bottom && lightPos.y <= caster.top &&
		dot(c, c) <= caster.radius * caster.radius)
		return 1.0;
	float y0 = lightPos.y + ray.y * entry;
	float y1 = lightPos.y + ray.y * exit;
	if (max(y0, y1) <= caster.bottom || min(y0, y1) >= caster.top)
		return 1.0;
	return 0.0;
}

float ActorLightShadowVisibility(DynLightInfo light)
{
	if (light.actorShadowCount <= 0 || (light.flags & LIGHTINFO_SUN) != 0)
		return 1.0;
	int count = min(light.actorShadowCount, 4);
	for (int i = 0; i < count; ++i)
	{
		if (ActorOccluderRayVisibility(light.pos.xyz, SDVK_LIGHTING_POSITION,
			light.actorShadowCasters[i]) < 0.5)
			return 0.0;
	}
	return 1.0;
}


#include <shaders/scene/light_trace.glsl> // needed always to do per-pixel tracing of lightmap lights for sprites


#define shadowAttenuationRaytrace(lightpos, shadowIndex, softShadowRadius, flags) traceShadow(lightpos, softShadowRadius)


float shadowDirToU(vec2 dir)
{
	if (abs(dir.y) > abs(dir.x))
	{
		float x = dir.x / dir.y * 0.125;
		if (dir.y >= 0.0)
			return 0.125 + x;
		else
			return (0.50 + 0.125) + x;
	}
	else
	{
		float y = dir.y / dir.x * 0.125;
		if (dir.x >= 0.0)
			return (0.25 + 0.125) - y;
		else
			return (0.75 + 0.125) - y;
	}
}

vec2 shadowUToDir(float u)
{
	u *= 4.0;
	vec2 raydir;
	switch (int(u))
	{
	case 0: raydir = vec2(u * 2.0 - 1.0, 1.0); break;
	case 1: raydir = vec2(1.0, 1.0 - (u - 1.0) * 2.0); break;
	case 2: raydir = vec2(1.0 - (u - 2.0) * 2.0, -1.0); break;
	case 3: raydir = vec2(-1.0, (u - 3.0) * 2.0 - 1.0); break;
	}
	return raydir;
}

float sampleShadowmap(vec3 planePoint, float v)
{
	float bias = 1.0;
	float negD = dot(vWorldNormal.xyz, planePoint);

	vec3 ray = planePoint;

	vec2 isize = textureSize(ShadowMap, 0);
	float scale = float(isize.x) * 0.25;

	// Snap to shadow map texel grid
	if (abs(ray.z) > abs(ray.x))
	{
		ray.y = ray.y / abs(ray.z);
		ray.x = ray.x / abs(ray.z);
		ray.x = (floor((ray.x + 1.0) * 0.5 * scale) + 0.5) / scale * 2.0 - 1.0;
		ray.z = sign(ray.z);
	}
	else
	{
		ray.y = ray.y / abs(ray.x);
		ray.z = ray.z / abs(ray.x);
		ray.z = (floor((ray.z + 1.0) * 0.5 * scale) + 0.5) / scale * 2.0 - 1.0;
		ray.x = sign(ray.x);
	}

	float t = negD / dot(vWorldNormal.xyz, ray) - bias;
	vec2 dir = ray.xz * t;

	float u = shadowDirToU(dir);
	float dist2 = dot(dir, dir);
	return step(dist2, texture(ShadowMap, vec2(u, v)).x);
}

float sampleShadowmapPCF(vec3 planePoint, float v)
{
	float bias = 1.0;
	float negD = dot(vWorldNormal.xyz, planePoint);

	vec3 ray = planePoint;

	if (abs(ray.z) > abs(ray.x))
		ray.y = ray.y / abs(ray.z);
	else
		ray.y = ray.y / abs(ray.x);

	vec2 isize = textureSize(ShadowMap, 0);
	float scale = float(isize.x);
	float texelPos = floor(shadowDirToU(ray.xz) * scale);

	float sum = 0.0;
	float step_count = SHADOWMAP_FILTER;

	texelPos -= step_count + 0.5;
	for (float x = -step_count; x <= step_count; x++)
	{
		float u = fract(texelPos / scale);
		vec2 dir = shadowUToDir(u);

		ray.x = dir.x;
		ray.z = dir.y;
		float t = negD / dot(vWorldNormal.xyz, ray) - bias;
		dir = ray.xz * t;

		float dist2 = dot(dir, dir);
		sum += step(dist2, texture(ShadowMap, vec2(u, v)).x);
		texelPos++;
	}
	return sum / (SHADOWMAP_FILTER * 2.0 + 1.0);
}

float shadowmapAttenuation(vec3 lightpos, float shadowIndex)
{
	vec3 planePoint = SDVK_LIGHTING_POSITION - lightpos.xyz;
	planePoint += 0.01; // nudge light position slightly as Doom maps tend to have their lights perfectly aligned with planes

	if (dot(planePoint.xz, planePoint.xz) < 1.0)
		return 1.0; // Light is too close

	float v = (shadowIndex + 0.5) / 1024.0;
	
	if (SHADOWMAP_FILTER == 0)
		return sampleShadowmap(planePoint, v);
	else
		return sampleShadowmapPCF(planePoint, v);
}

float shadowAttenuationShadowMap(vec3 lightpos, int shadowIndex, float softShadowRadius, int flags)
{
	if (shadowIndex >= 1024)
		return 1.0; // No shadowmap available for this light
	return shadowmapAttenuation(lightpos, float(shadowIndex));
}

float shadowAttenuation(vec3 lightpos, int shadowIndex, float softShadowRadius, int flags)
{
	if(USE_RAYTRACE || (flags & LIGHTINFO_TRACE) > 0)
	{
		return shadowAttenuationRaytrace(lightpos, shadowIndex, softShadowRadius, flags);
	}
	else if(USE_SHADOWMAP)
	{
		return shadowAttenuationShadowMap(lightpos, shadowIndex, softShadowRadius, flags);
	}
	else
	{
		return 1.0;
	}
}
