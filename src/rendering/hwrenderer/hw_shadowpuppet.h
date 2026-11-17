#pragma once

#include "matrix.h"
#include "tarray.h"

class AActor;
struct FDynamicLight;
struct HWDrawInfo;

struct HWShadowPuppetScene
{
	const FDynamicLight* Flashlight = nullptr;
	FVector3 Origin;
	VSMatrix LightProjection = VSMatrix::identity();
	// Opaque sprite caps face the light. Edge endpoint pairs follow their winding.
	TArray<FVector3> Triangles;
	TArray<FVector3> Edges;
	TArray<const AActor*> Casters;
};

bool BuildShadowPuppetScene(HWDrawInfo& di, HWShadowPuppetScene& scene);
VSMatrix ShadowPuppetVulkanProjection(const VSMatrix& projection, const VSMatrix& view);

extern thread_local const FDynamicLight* HWShadowPuppetFlashlight;
