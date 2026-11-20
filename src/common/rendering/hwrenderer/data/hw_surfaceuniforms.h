
#pragma once

#include "vectors.h"
#include <array>
#include <cstddef>

struct SurfaceUniforms
{
	FVector4 uObjectColor;
	FVector4 uObjectColor2;
	FVector4 uDynLightColor;
	FVector4 uAddColor;
	FVector4 uTextureAddColor;
	FVector4 uTextureModulateColor;
	FVector4 uTextureBlendColor;
	FVector4 uFogColor;
	float uDesaturationFactor;
	float uInterpolationFactor;
	float timer;
	int useVertexData;
	FVector4 uVertexColor;
	FVector4 uVertexNormal;

	FVector4 uGlowTopPlane;
	FVector4 uGlowTopColor;
	FVector4 uGlowBottomPlane;
	FVector4 uGlowBottomColor;

	FVector4 uGradientTopPlane;
	FVector4 uGradientBottomPlane;

	FVector4 uSplitTopPlane;
	FVector4 uSplitBottomPlane;

	FVector4 uDetailParms;
	FVector4 uNpotEmulation;

	FVector2 uClipSplit;
	FVector2 uSpecularMaterial;

	float uLightLevel;
	float uFogDensity;
	float uLightFactor;
	float uLightDist;

	float uAlphaThreshold;
	int uTextureIndex;
	int uColormapIndex;
	int uLightProbeIndex;
	FVector3 uActorCenter;
	float uDepthFadeThreshold;

	// SDVK-005 semantic descriptor index, relative to uTextureIndex. Appended
	// so the established SurfaceUniforms field offsets remain unchanged.
	int uHeightTextureIndex = -1;
	int uStageBWorld = 0;
	float uPBRReliefDepth = 1.0f;
	int uMaterialSemanticPad2;

	// SDVK-007/v1: per-draw sprite-only world TBN. Normal.W = 1 iff
	// explicit; tangent.W = +/-1 handedness. Appended after SDVK-005.
	FVector4 uSpriteTangent = {};
	FVector4 uSpriteNormal = {};

	// SDVK-008: opt-in bounded per-sprite relief contract. Depth (UV units),
	// quality [0,3], candidate enable; raw signed quad UV endpoints.
	// Only authored height and a valid SDVK-007 basis can activate shading.
	FVector4 uSpriteReliefParams = {};  // scale, quality, 0, candidate-enable
	FVector4 uSpriteReliefBounds = {};  // ul, vt, ur, vb (before TextureMatrix)
	// SDVK-011 shader-world lighting sample; W enables enhanced HUD lighting.
	FVector4 uViewmodelSample = {};
	FVector4 uViewmodelMode = {}; // requested, effective, fallback, HUD marker (1 card, 2 model)
	// Flashlight depth, orientation, height multiplier (0 disables), surface kind.
	// W: world = 0, sprite = 1/2, enhanced viewmodel = 3/4, fullbright sprite = 5/6.
	// Modes 2, 3 and 6 have padded albedo.
	FVector4 uWorldReliefParams = {};
	FVector4 uPBRMaterialFactors = { 0.f, 0.f, 1.f, 1.f }; // roughness, metallic, normal, AO

	void SetPBRMaterialTuning(const std::array<float, 5>& values)
	{
		uPBRMaterialFactors = { values[0], values[1], values[2], values[3] };
		uPBRReliefDepth = values[4];
	}
};

static_assert(offsetof(SurfaceUniforms, uPBRReliefDepth) == 408);
static_assert(offsetof(SurfaceUniforms, uPBRMaterialFactors) == 528);
static_assert(sizeof(SurfaceUniforms) == 544);

struct SurfaceLightUniforms
{
	FVector4 uVertexColor;
	float uDesaturationFactor;
	float uLightLevel;
	int padding0;
	int padding1;

	void SetColor(float r, float g, float b, float a = 1.f, int desat = 0)
	{
		uVertexColor = { r, g, b, a };
		uDesaturationFactor = desat * (1.0f / 255.0f);
	}

	void SetColor(PalEntry pe, int desat = 0)
	{
		const float scale = 1.0f / 255.0f;
		uVertexColor = { pe.r * scale, pe.g * scale, pe.b * scale, pe.a * scale };
		uDesaturationFactor = desat * (1.0f / 255.0f);
	}

	void SetColorAlpha(PalEntry pe, float alpha = 1.f, int desat = 0)
	{
		const float scale = 1.0f / 255.0f;
		uVertexColor = { pe.r * scale, pe.g * scale, pe.b * scale, alpha };
		uDesaturationFactor = desat * (1.0f / 255.0f);
	}

	void ResetColor()
	{
		uVertexColor = { 1.0f, 1.0f, 1.0f, 1.0f };
		uDesaturationFactor = 0.0f;
	}

	void SetSoftLightLevel(int llevel, int blendfactor = 0)
	{
		if (blendfactor == 0) uLightLevel = llevel / 255.f;
		else uLightLevel = -1.f;
	}

	void SetNoSoftLightLevel()
	{
		uLightLevel = -1.f;
	}
};
