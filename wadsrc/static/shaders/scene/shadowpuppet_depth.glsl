// The sprite depth image contains only sprite blockers. Each displaced aperture ray
// still ends at this receiver, at the same light-view depth, even on a riser.
float PuppetNearestDepth(int image, vec2 uv)
{
	if (any(lessThan(uv, vec2(0.0))) || any(greaterThanEqual(uv, vec2(1.0)))) return 1.0;
	vec4 depths = textureGather(textures[nonuniformEXT(image)], uv);
	return min(min(depths.x, depths.y), min(depths.z, depths.w));
}

float PuppetDiskVisibility(int image, vec2 uv, vec2 size, float receiverDepth)
{
	if (any(lessThan(uv, vec2(0.0))) || any(greaterThanEqual(uv, vec2(1.0)))) return 1.0;
	vec4 depths = textureGather(textures[nonuniformEXT(image)], uv);
	vec4 visible = step(vec4(receiverDepth), depths);
	vec2 f = fract(uv * size - 0.5);
	// GLSL gather order is (lower x, upper y), (upper x, upper y),
	// (upper x, lower y), (lower x, lower y).
	return mix(mix(visible.w, visible.z, f.x), mix(visible.x, visible.y, f.x), f.y);
}

float ShadowPuppetDepthVisibility(DynLightInfo light, vec3 position, int image)
{
	vec3 toLight = light.pos.xyz - position;
	vec3 biased = position + toLight * min(1.0, 0.30 / max(length(toLight), 1e-4));
	vec4 clip = ShadowPuppetProjection * vec4(biased, 1.0);
	if (clip.w <= 0.0) return 1.0;
	vec3 projected = clip.xyz / clip.w;
	if (any(greaterThanEqual(abs(projected.xy), vec2(1.0))) || projected.z < 0.0 || projected.z > 1.0)
		return 1.0;

	ivec2 size = textureSize(textures[nonuniformEXT(image)], 0);
	vec2 uv = projected.xy * 0.5 + 0.5;
	ivec2 center = clamp(ivec2(uv * vec2(size)), ivec2(0), size - 1);
	float centerDepth = texelFetch(textures[nonuniformEXT(image)], center, 0).r;
	float hardVisibility = step(projected.z, centerDepth);
	float softness = clamp(uShadowPuppetSoftness, 0.0, 2.0);
	if (softness == 0.0) return hardVisibility;

	// For perspective depth z = A + B/d, (zReceiver-zBlocker)/-B
	// is (1/dBlocker - 1/dReceiver). A disk source of world radius R thus
	// covers R * focalTexels * (zReceiver-zBlocker)/-B shadow texels.
	float minusB = uShadowPuppetDepthRange.y;
	float focalTexels = 0.5 * float(size.x) * length(transpose(ShadowPuppetProjection)[0].xyz);
	float aperture = 3.0 * softness * focalTexels;
	float texelsPerDepth = aperture / minusB;
	// Bound the search by the closest submitted card. A fixed texel cap
	// makes the penumbra stop expanding when a blocker approaches the lamp.
	float maxRadius = min(length(vec2(size)), aperture * max(1.0 / uShadowPuppetDepthRange.x - 1.0 / clip.w, 0.0));
	float radius = clamp((projected.z - centerDepth) * texelsPerDepth, 0.0, maxRadius);
	if (hardVisibility > 0.0)
	{
		// A lit centre can still see an occluder across part of the aperture.
		// Stagger the search directions between rings and gather four texels
		// per probe to find narrow limbs. The outer rings may find a depth
		// beyond the filter radius; only the disk below decides visibility.
		const vec2 probes[20] = vec2[20](
			vec2(1,0), vec2(0,1), vec2(5,2), vec2(-2,5),
			vec2(12,0), vec2(8,8), vec2(0,12), vec2(-8,8),
			vec2(18,8), vec2(8,18), vec2(-8,18), vec2(-18,8),
			vec2(28,0), vec2(20,20), vec2(0,28), vec2(-20,20),
			vec2(34,14), vec2(14,34), vec2(-14,34), vec2(-34,14));
		for (int i = 0; i < 20; ++i)
		{
			// Preserve close probes for contact shadows and spread outer rings when
			// a near caster subtends a large part of the light image.
			vec2 probe = probes[i];
			float stretch = max(maxRadius / 24.0 - 1.0, 0.0);
			probe *= 1.0 + stretch * min(dot(probe, probe) / (34.0 * 34.0), 1.0);
			vec2 offset = probe / vec2(size);
			float blocker = min(PuppetNearestDepth(image, uv + offset), PuppetNearestDepth(image, uv - offset));
			if (blocker >= projected.z) continue;
			float candidate = min((projected.z - blocker) * texelsPerDepth, maxRadius);
			if (length(probe) > candidate + 1.5) continue;
			radius = candidate;
			break;
		}
		if (radius == 0.0) return 1.0;
	}
	if (radius <= 0.5)
		return mix(hardVisibility, PuppetDiskVisibility(image, uv, vec2(size), projected.z), radius * 2.0);

	// Equal-area disk strata in antipodal pairs. Their orientation stays in
	// light space during camera motion and the symmetric weights keep the
	// silhouette centred. Bilinear comparisons keep subtexel motion smooth.
	float sum = 0.0;
	const int pairs = 16;
	const float goldenAngle = 2.39996323;
	for (int i = 0; i < pairs; ++i)
	{
		float angle = float(i) * goldenAngle;
		vec2 direction = vec2(cos(angle), sin(angle));
		float distance = sqrt((float(i) + 0.5) / float(pairs)) * radius;
		vec2 offset = direction * distance / vec2(size);
		sum += PuppetDiskVisibility(image, uv + offset, vec2(size), projected.z);
		sum += PuppetDiskVisibility(image, uv - offset, vec2(size), projected.z);
	}
	return sum / float(pairs * 2);
}
