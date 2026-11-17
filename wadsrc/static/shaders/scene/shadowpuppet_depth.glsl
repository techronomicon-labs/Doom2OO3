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

	// Compare before weighting. A texel-wide tent gives bilinear PCF at the
	// default setting and fades taps in continuously as the footprint grows.
	float radius = 0.5 + 0.5 * softness;
	float visibility = 0.0, sumWeights = 0.0;
	for (int y = -1; y <= 1; ++y)
	{
		for (int x = -1; x <= 1; ++x)
		{
			ivec2 tap = center + ivec2(x, y);
			vec2 weights = max(radius - abs(vec2(tap) + 0.5 - texelPosition), 0.0);
			float weight = weights.x * weights.y;
			if (weight == 0.0) continue;
			tap = clamp(tap, ivec2(0), size - 1);
			float receiverDepth = clamp(projected.z + dot(depthPerTexel, vec2(tap) + 0.5 - texelPosition), 0.0, 1.0);
			float blockerDepth = texelFetch(textures[nonuniformEXT(image)], tap, 0).r;
			visibility += weight * step(receiverDepth, blockerDepth);
			sumWeights += weight;
		}
	}
	return sumWeights > 0.0 ? visibility / sumWeights : hardVisibility;
}
