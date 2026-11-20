// SDVK-008: bounded, opt-in sprite-only shallow parallax occlusion mapping.
// Uses the *accepted* SDVK-007 final-quad world tangent and UV handedness.
// Do not treat this as geometry, sprite shadows, or changes to fragment depth.
#ifndef SDVK_MATERIAL_RELIEF_GLSL
#define SDVK_MATERIAL_RELIEF_GLSL

bool SDVKFinite(float v) { return !isnan(v) && !isinf(v); }
bool SDVKFinite(vec2 v) { return all(not(isnan(v))) && all(not(isinf(v))); }
bool SDVKFinite(vec3 v) { return all(not(isnan(v))) && all(not(isinf(v))); }
bool SDVKInsideReliefRect(vec2 uv, vec2 lo, vec2 hi)
{
	return all(greaterThanEqual(uv, lo)) && all(lessThanEqual(uv, hi));
}

// Returns the original coordinate for every unsupported or invalid case.
// The inherited material sampler is still the only source for final color.
vec2 SDVKResolveSpriteReliefUV(vec2 original, vec2 uvDx, vec2 uvDy, out bool applied)
{
	applied = false;
#if !defined(NO_LAYERS) && (defined(SHADERTYPE_DEFAULT) || defined(SHADERTYPE_SPECULAR) || defined(SHADERTYPE_PBR))
	float scale = uSpriteReliefParams.x;
	int quality = int(uSpriteReliefParams.y + 0.5);
	if (uSpriteReliefParams.w < 0.5 || uSpriteNormal.w < 0.5 ||
		uHeightTextureIndex < 0 || quality < 1 || quality > 3 ||
		scale <= 0.0 || scale > 0.0200 || !SDVKFinite(scale) ||
		!SDVKFinite(original) || !SDVKFinite(uvDx) || !SDVKFinite(uvDy) ||
		PALETTEMODE || TM_STENCIL || TM_OPAQUE || TM_INVERSE ||
		TM_INVERTOPAQUE || TM_ALPHATEXTURE || TM_FOGLAYER || TM_CLAMPY ||
		uNpotEmulation.y != 0.0)
		return original;

#ifdef PBR
	scale = min(scale * uPBRReliefDepth, 0.0200);
	if (scale <= 0.0)
		return original;
#endif

	// vTexCoord already includes TextureMatrix. Permit only axis-aligned,
	// positively scaled transforms; a rotated/skewed/negative-U matrix would
	// need a different material TBN and is explicitly unsupported.
	if (!SDVKFinite(TextureMatrix[0][0]) || !SDVKFinite(TextureMatrix[1][1]) ||
		TextureMatrix[0][0] <= 0.0 || TextureMatrix[1][1] <= 0.0 ||
		abs(TextureMatrix[1][0]) > 0.000001 || abs(TextureMatrix[0][1]) > 0.000001 ||
		abs(TextureMatrix[0][3]) > 0.000001 || abs(TextureMatrix[1][3]) > 0.000001 ||
		abs(TextureMatrix[3][3] - 1.0) > 0.000001 ||
		!SDVKFinite(uSpriteReliefBounds.xy) || !SDVKFinite(uSpriteReliefBounds.zw))
		return original;

	vec2 p0 = (TextureMatrix * vec4(uSpriteReliefBounds.xy, 0.0, 1.0)).xy;
	vec2 p1 = (TextureMatrix * vec4(uSpriteReliefBounds.zw, 0.0, 1.0)).xy;
	vec2 rectLo = min(p0, p1);
	vec2 rectHi = max(p0, p1);
	if (!SDVKFinite(rectLo) || !SDVKFinite(rectHi) ||
		any(lessThan(rectLo, vec2(0.0))) || any(greaterThan(rectHi, vec2(1.0))) ||
		any(lessThanEqual(rectHi - rectLo, vec2(0.00001))))
		return original;

	ivec2 heightDimensions = textureSize(uHeightTextureIndex, 0);
	ivec2 albedoDimensions = textureSize(tex, 0);
	if (any(lessThanEqual(heightDimensions, ivec2(0))) ||
		any(lessThanEqual(albedoDimensions, ivec2(0))))
		return original;
	vec2 dims = vec2(heightDimensions);
	float rho = max(length(uvDx*dims), length(uvDy*dims));
	float lod = clamp(log2(max(rho, 0.000001)), 0.0, 4.0);
	// Include the bilinear/mipmap filtering footprint, not only the center UV.
	// Oversized footprints disable relief instead of bleeding into an atlas.
	vec2 texelMax = max(1.0/dims, 1.0/vec2(albedoDimensions));
	vec2 pad = max(texelMax * (1.0 + exp2(lod)),
		2.0 * (abs(uvDx) + abs(uvDy)));
	vec2 safeLo = rectLo + pad;
	vec2 safeHi = rectHi - pad;
	if (!SDVKInsideReliefRect(original, safeLo, safeHi))
		return original;

	vec3 direction = uCameraPos.xyz - pixelpos.xyz;
	float distanceSq = dot(direction, direction);
	if (!SDVKFinite(direction) || !SDVKFinite(distanceSq) || distanceSq <= 1e-12)
		return original;
	direction *= inversesqrt(distanceSq);
	vec3 bitangent = cross(uSpriteNormal.xyz, uSpriteTangent.xyz) * uSpriteTangent.w;
	vec3 view = vec3(dot(direction,uSpriteTangent.xyz), dot(direction,bitangent), dot(direction,uSpriteNormal.xyz));
	if (!SDVKFinite(view) || view.z <= 0.20)
		return original;
	if (length(view.xy) <= 1e-8)
		return original;

	float fade = smoothstep(0.20, 0.32, view.z);
	vec2 ray = (scale * fade / view.z) * view.xy;
	float rayLength = length(ray);
	if (!SDVKFinite(ray) || !SDVKFinite(rayLength) || rayLength <= 1e-10)
		return original;
	if (rayLength > 0.0500) ray *= 0.0500/rayLength;

	int steps = quality == 1 ? 8 : (quality == 2 ? 12 : 20);
	int refinements = quality == 1 ? 1 : 2;
	// One original sample + up to 20 fixed march + two fixed refinements.
	float fLow = textureLod(uHeightTextureIndex, original, lod).r - 1.0;
	if (!SDVKFinite(fLow) || fLow < -1.0 || fLow > 0.0)
		return original;
	if (fLow >= 0.0) return original; // height 1 touches the front plane
	float dLow = 0.0;
	float dHigh = 1.0;
	float fHigh = 0.0;
	bool bracketed = false;
	for (int i = 1; i <= 20; ++i)
	{
		if (i > steps) break;
		float depth = float(i) / float(steps);
		vec2 uv = original - depth*ray;
		if (!SDVKInsideReliefRect(uv, safeLo, safeHi)) return original;
		float heightValue = textureLod(uHeightTextureIndex, uv, lod).r;
		if (!SDVKFinite(heightValue) || heightValue < 0.0 || heightValue > 1.0) return original;
		float f = depth + heightValue - 1.0;
		if (f >= 0.0)
		{
			dHigh = depth;
			fHigh = f;
			bracketed = true;
			break;
		}
		dLow = depth;
		fLow = f;
	}
	if (!bracketed) return original;
	for (int j = 0; j < 2; ++j)
	{
		if (j >= refinements) break;
		float mid = 0.5 * (dLow + dHigh);
		vec2 uv = original - mid*ray;
		if (!SDVKInsideReliefRect(uv, safeLo, safeHi)) return original;
		float h = textureLod(uHeightTextureIndex, uv, lod).r;
		if (!SDVKFinite(h) || h < 0.0 || h > 1.0) return original;
		float f = mid + h - 1.0;
		if (f >= 0.0) { dHigh = mid; fHigh = f; }
		else { dLow = mid; fLow = f; }
	}
	float denom = fHigh - fLow;
	float lerp = denom > 1e-12 ? clamp(-fLow / denom, 0.0, 1.0) : 0.5;
	float depth = mix(dLow, dHigh, lerp);
	vec2 resolved = original - depth*ray;
	if (!SDVKFinite(resolved) || !SDVKInsideReliefRect(resolved, safeLo, safeHi))
		return original;
	applied = true;
	return resolved;
#else
	return original;
#endif
}

vec3 SDVKReliefGeometricNormal()
{
	return uWorldReliefParams.w > 0.0 ? uSpriteNormal.xyz : normalize(vWorldNormal.xyz);
}

vec3 SDVKReliefNormal(vec3 normal, vec3 geometricNormal, vec3 slope)
{
	if (dot(slope, slope) == 0.0)
		return normal;
	vec3 reliefNormal = normalize(geometricNormal - slope);
	// Rotate the original material normal with the virtual plane.
	vec3 axis = cross(geometricNormal, reliefNormal);
	vec3 tangent = cross(axis, normal);
	return normalize(normal + tangent + cross(axis, tangent) / (1.0 + dot(geometricNormal, reliefNormal)));
}

#if !defined(NO_LAYERS) && !defined(USE_LEVELMESH) && !defined(UBERSHADER) && \
	(defined(SHADERTYPE_PBR) || (defined(SHADERTYPE_DEFAULT) && !defined(SHADE_VERTEX)))
#define SDVK_STRUCTURAL_RELIEF
vec4 SDVKSampleStructuralRelief(vec2 uv, vec2 uvDx, vec2 uvDy, float alpha)
{
	float exaggeration = uWorldReliefParams.z;
#ifdef PBR
	exaggeration *= uPBRReliefDepth;
#endif
	if (exaggeration <= 0.0 || uHeightTextureIndex < 0)
		return vec4(0.0);

	float kind = uWorldReliefParams.w;
	bool sprite = kind > 0.0;
	bool hud = kind == 3.0 || kind == 4.0;
	bool fullbright = kind == 5.0 || kind == 6.0;
	bool expanded = kind == 2.0 || kind == 3.0 || kind == 6.0;
	bool orientationEnabled = uWorldReliefParams.y > 0.0;
	bool usesDirectLight = uLightIndex >= 0;
#if defined(PBR)
	bool usesRetainedFill = !sprite && orientationEnabled && STAGE_B_WORLD_LIGHTING &&
		(uStageBAmbient > 0.0 || uStageBAmbientSpecular > 0.0);
#else
	const bool usesRetainedFill = false;
#endif
	if (!usesDirectLight && !usesRetainedFill)
		return vec4(0.0);
#if !defined(PBR)
	if (!sprite)
		return vec4(0.0);
#endif
	if (sprite && (uSpriteNormal.w < 0.5 || (hud && uViewmodelSample.w < 0.5) ||
		PALETTEMODE || TM_STENCIL || TM_OPAQUE || TM_INVERSE || TM_INVERTOPAQUE ||
		TM_ALPHATEXTURE || TM_FOGLAYER || TM_CLAMPY || uNpotEmulation.y != 0.0 ||
		!SDVKFinite(uv) || !SDVKFinite(uvDx) || !SDVKFinite(uvDy)))
		return vec4(0.0);

	// Compute derivatives before any branch on alpha or texture coordinates.
	vec3 posDx = vec3(0.0), posDy = vec3(0.0);
	if (orientationEnabled && !hud)
	{
		posDx = dFdx(pixelpos.xyz);
		posDy = dFdy(pixelpos.xyz);
	}

	vec2 texel = vec2(0.0);
	float fade = 1.0;
	const float neutralHeight = 128.0 / 255.0;
	if (sprite)
	{
		ivec2 dimensions = textureSize(uHeightTextureIndex, 0);
		if (any(lessThanEqual(dimensions, ivec2(0))))
			return vec4(0.0);
		texel = 1.0 / vec2(dimensions);
		if (expanded)
		{
			// Expanded albedo has a one-source-texel border on every side.
			vec2 scale = vec2(1.0) + 2.0 * texel;
			uv = uv * scale - texel;
			uvDx *= scale;
			uvDy *= scale;
		}
		vec2 footprint = 0.5 * (abs(uvDx) + abs(uvDy));
		vec2 edgeDistance = min(uv, vec2(1.0) - uv);
		vec2 edgeFade = smoothstep(footprint, footprint + texel, edgeDistance);
		fade = edgeFade.x * edgeFade.y * smoothstep(0.55, 0.95, alpha);
		if (fade <= 0.0)
			return vec4(0.0);
		if (fullbright)
		{
			// Preserve authored emissive texels even beside a solid support.
			ivec2 center = min(ivec2(uv * vec2(dimensions)), dimensions - 1);
			float authoredHeight = texelFetch(uHeightTextureIndex, center, 0).r;
			fade *= smoothstep(1e-6, 0.045, abs(authoredHeight - neutralHeight));
			if (fade <= 0.0)
				return vec4(0.0);
		}
	}

	float displacement = 0.0;
	float centerHeight = neutralHeight;
	if ((usesDirectLight && uWorldReliefParams.x > 0.0) || fullbright)
	{
		// Code 128 is the exact neutral value in the linear 8-bit map.
		centerHeight = textureGrad(uHeightTextureIndex, uv, uvDx, uvDy).r;
		float height = centerHeight - neutralHeight;
		if (abs(height) > 1e-6)
			displacement = height * exaggeration * uWorldReliefParams.x;
		if (hud)
			displacement = clamp(displacement, -0.35, 0.35);
		displacement *= fade;
	}
	if (!orientationEnabled && (!fullbright || displacement == 0.0))
		return vec4(vec3(0.0), displacement);

	vec3 normal = SDVKReliefGeometricNormal();
	vec3 dualX = vec3(0.0), dualY = vec3(0.0);
	float determinant = 0.0;
	if (orientationEnabled && !hud)
	{
		dualX = cross(posDy, normal);
		dualY = cross(normal, posDx);
		determinant = dot(posDx, dualX);
		if (!SDVKFinite(determinant) || abs(determinant) <= max(1e-12, 1e-5 * length(posDx) * length(posDy)))
			return fullbright ? vec4(0.0) : vec4(vec3(0.0), displacement);
	}

	// Sample the same mip footprint on each side of an axis. The stencil
	// expands along minified axes so distant seams and grazing views stay stable.
	if (!sprite)
		texel = 1.0 / vec2(textureSize(uHeightTextureIndex, 0));
	vec2 stepUV = max(texel, 0.5 * (abs(uvDx) + abs(uvDy)));
	vec2 u = vec2(stepUV.x, 0.0);
	vec2 v = vec2(0.0, stepUV.y);
	vec2 rightUV = uv + u, leftUV = uv - u;
	vec2 topUV = uv + v, bottomUV = uv - v;
	if (sprite)
	{
		vec2 border = 0.5 * texel;
		rightUV = clamp(rightUV, border, 1.0 - border);
		leftUV = clamp(leftUV, border, 1.0 - border);
		topUV = clamp(topUV, border, 1.0 - border);
		bottomUV = clamp(bottomUV, border, 1.0 - border);
	}
	float rightHeight = textureGrad(uHeightTextureIndex, rightUV, uvDx, uvDy).r;
	float leftHeight = textureGrad(uHeightTextureIndex, leftUV, uvDx, uvDy).r;
	float topHeight = textureGrad(uHeightTextureIndex, topUV, uvDx, uvDy).r;
	float bottomHeight = textureGrad(uHeightTextureIndex, bottomUV, uvDx, uvDy).r;
	if (fullbright)
	{
		// A constant-height patch has no shape contrast at any depth setting.
		vec4 variation = abs(vec4(rightHeight, leftHeight, topHeight, bottomHeight) - centerHeight);
		float localVariation = max(max(variation.x, variation.y), max(variation.z, variation.w));
		if (localVariation <= 1e-6)
			return vec4(0.0);
		displacement *= smoothstep(1e-6, 0.025, localVariation);
	}
	if (!orientationEnabled)
		return vec4(vec3(0.0), displacement);
	vec2 slopeUV = vec2(rightHeight - leftHeight, topHeight - bottomHeight) / (2.0 * stepUV);

	vec3 slope;
	if (hud)
	{
		// HUD geometry is screen space. Its lighting uses a world-space basis
		// and a slope measured per source texel, independent of viewport size.
		vec3 tangent = uSpriteTangent.xyz;
		vec3 bitangent = cross(normal, tangent) * uSpriteTangent.w;
		slope = tangent * (slopeUV.x * texel.x) + bitangent * (slopeUV.y * texel.y);
	}
	else
	{
		// The UV-to-world derivative preserves tiling, scale, and mirrored UVs.
		slope = (dualX * dot(slopeUV, uvDx) + dualY * dot(slopeUV, uvDy)) / determinant;
	}
	slope *= exaggeration * uWorldReliefParams.y * fade;
	float slopeSquared = dot(slope, slope);
	if (!SDVKFinite(slopeSquared))
		return vec4(vec3(0.0), displacement);
	slope *= 1.5 * inversesqrt(max(2.25, slopeSquared));
	return vec4(slope, displacement);
}
#endif
#endif
