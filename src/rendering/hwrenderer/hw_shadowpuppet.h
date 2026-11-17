#pragma once

#include "matrix.h"
#include "tarray.h"

struct FDynamicLight;
struct FRenderViewpoint;

struct HWShadowPuppetScene
{
	const FDynamicLight* Flashlight = nullptr;
	FVector3 Origin;
	VSMatrix LightProjection = VSMatrix::identity();
	TArray<FVector3> Triangles;
};

bool BuildShadowPuppetScene(const FRenderViewpoint& view, HWShadowPuppetScene& scene);
VSMatrix ShadowPuppetVulkanProjection(const VSMatrix& projection, const VSMatrix& view);

extern thread_local const FDynamicLight* HWShadowPuppetFlashlight;
