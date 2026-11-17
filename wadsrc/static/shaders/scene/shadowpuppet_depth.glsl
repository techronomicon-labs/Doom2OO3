float ShadowPuppetDepthVisibility(DynLightInfo light, vec3 position, int image)
{
	// Keep the contact offset in world units and sample the geometric receiver.
	vec3 toLight = light.pos.xyz - position;
	vec3 biased = position + toLight * min(1.0, 0.30 / max(length(toLight), 1e-4));
	vec4 clip = ShadowPuppetProjection * vec4(biased, 1.0);
	if (clip.w <= 0.0) return 1.0;
	vec3 projected = clip.xyz / clip.w;
	if (any(greaterThanEqual(abs(projected.xy), vec2(1.0))) || projected.z < 0.0 || projected.z > 1.0)
		return 1.0;

	ivec2 size = textureSize(textures[nonuniformEXT(image)], 0);
	vec2 texelPosition = (projected.xy * 0.5 + 0.5) * vec2(size);
	ivec2 center = clamp(ivec2(texelPosition), ivec2(0), size - 1);
	float centerDepth = texelFetch(textures[nonuniformEXT(image)], center, 0).r;
	float hardVisibility = step(projected.z, centerDepth);
	float softness = clamp(uShadowPuppetSoftness, 0.0, 2.0);
	if (softness == 0.0) return hardVisibility;

	// A receiver plane remains planar in projected coordinates. Project its
	// tangent directions so taps compare against the right depth on a slope.
	vec3 normal = vWorldNormal.xyz;
	vec3 axis = abs(normal.y) < 0.95 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0);
	vec3 tangent = cross(normal, axis);
	vec4 tangentClip = ShadowPuppetProjection * vec4(tangent, 0.0);
	vec4 bitangentClip = ShadowPuppetProjection * vec4(cross(normal, tangent), 0.0);
	vec3 plane = cross(tangentClip.xyz - projected * tangentClip.w,
		bitangentClip.xyz - projected * bitangentClip.w);
	if (abs(plane.z) <= max(1e-7, length(plane) * 1e-5)) return hardVisibility;
	vec2 depthPerTexel = (-2.0 * plane.xy / plane.z) / vec2(size);
	// At extreme grazing angles the tap footprint spans too much scene depth.
	softness *= 1.0 - smoothstep(0.00075, 0.002, max(abs(depthPerTexel.x), abs(depthPerTexel.y)));
	if (softness == 0.0) return hardVisibility;

	// Search on both sides of an edge, including when the centre ray is lit.
	// Each comparison uses this fragment's receiver plane. Keep the closest
	// covered tap in image space, so unrelated blocker layers aren't averaged.
	uint covered = 0u;
	float nearestSquared = 1e10, depthGap = 0.0;
	for (int y = -2; y <= 2; ++y)
	{
		for (int x = -2; x <= 2; ++x)
		{
			ivec2 tap = center + ivec2(x, y);
			if (any(lessThan(tap, ivec2(0))) || any(greaterThanEqual(tap, size))) continue;
			vec2 offset = vec2(tap) + 0.5 - texelPosition;
			float receiverDepth = projected.z + dot(depthPerTexel, offset);
			float blockerDepth = (x == 0 && y == 0) ? centerDepth : texelFetch(textures[nonuniformEXT(image)], tap, 0).r;
			if (blockerDepth >= receiverDepth || receiverDepth > 1.0) continue;
			covered |= 1u << uint((y + 2) * 5 + (x + 2));
			float d2 = dot(offset, offset);
			if (d2 < nearestSquared)
			{
				nearestSquared = d2;
				depthGap = receiverDepth - blockerDepth;
			}
		}
	}
	if (covered == 0u) return 1.0;
	if (covered == 0x1ffffffu) return 0.0;

	// Perspective depth = A + B / lightViewDistance. The light origin's
	// clip-space z is B, so depthGap / -B is 1/blockerZ - 1/receiverZ.
	// A finite flashlight aperture then subtends this many map texels.
	const float apertureRadius = 0.4; // world units
	float minusB = -(ShadowPuppetProjection * vec4(light.pos.xyz, 1.0)).z;
	// The first row's spatial length is cot(FOV/2) even after view rotation.
	// This is the enclosing shadow projection, shared by every flashlight lobe.
	float focalTexels = 0.5 * float(size.x) * length(transpose(ShadowPuppetProjection)[0].xyz);
	float penumbra = apertureRadius * focalTexels * depthGap / max(minusB, 1e-4);
	float radius = min(2.5, 0.5 + softness * (0.5 + penumbra));
	float shadowWeight = 0.0, sumWeights = 0.0;
	for (int y = -2; y <= 2; ++y)
	{
		for (int x = -2; x <= 2; ++x)
		{
			vec2 offset = vec2(center + ivec2(x, y)) + 0.5 - texelPosition;
			vec2 weights = max(radius - abs(offset), 0.0);
			float weight = weights.x * weights.y;
			if ((covered & (1u << uint((y + 2) * 5 + (x + 2)))) != 0u) shadowWeight += weight;
			sumWeights += weight;
		}
	}
	return sumWeights > 0.0 ? 1.0 - shadowWeight / sumWeights : hardVisibility;
}
