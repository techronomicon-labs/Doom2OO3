#pragma once

#include "matrix.h"
#include <cstddef>

struct HWDrawInfo;

enum class ELightBlendMode : uint8_t
{
	CLAMP = 0,
	CLAMP_COLOR = 1,
	NOCLAMP = 2,

	DEFAULT = CLAMP,
};

enum class ELightAttenuationMode : uint8_t
{
	LINEAR = 0,
	INVERSE_SQUARE = 1,

	DEFAULT = LINEAR,
};

struct HWViewpointUniforms
{
	static constexpr int EmitterLighting = 1 << 24;
	VSMatrix mProjectionMatrix;
	VSMatrix mViewMatrix;
	VSMatrix mNormalViewMatrix;
	FVector4 mCameraPos;
	FVector4 mClipLine;
	
	int mViewOffsetX = 0;
	int mViewOffsetY = 0;

	float mGlobVis = 1.f;
	int mPalLightLevels = 0;
	int mViewHeight = 0;
	float mClipHeight = 0.f;
	float mClipHeightDirection = 0.f;

	int mLightTilesWidth = 0;

	FVector3 SunDir;
	float StageBAmbient = 0.0f;
	FVector3 SunColor;
	float SunIntensity = 0.0f;

	FVector3 mCameraNormal;
	float StageBIntensity = 0.0f;
	float StageBAmbientSpecular = 0.0f;
	int ShadowPuppetTexture = 0;
	int ShadowPuppetMode = 0;
	float ShadowPuppetSoftness = 1.0f;
	VSMatrix ShadowPuppetProjection = VSMatrix::identity();
	alignas(16) FVector2 ShadowPuppetDepthRange{0, 0};

	void CalcDependencies()
	{
		mNormalViewMatrix.computeNormalMatrix(mViewMatrix);
	}
};

static_assert(offsetof(HWViewpointUniforms, StageBAmbient) == 268);
static_assert(offsetof(HWViewpointUniforms, StageBIntensity) == 300);
static_assert(offsetof(HWViewpointUniforms, StageBAmbientSpecular) == 304);
static_assert(offsetof(HWViewpointUniforms, ShadowPuppetProjection) == 320);
static_assert(offsetof(HWViewpointUniforms, ShadowPuppetDepthRange) == 384);
static_assert(sizeof(HWViewpointUniforms) == 400);



