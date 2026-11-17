#pragma once

#include "matrix.h"
#include "tarray.h"
#include <array>

class AActor;
struct FDynamicLight;
struct HWDrawInfo;

struct HWShadowPuppetLightSet
{
	// The local flashlight add-on uses up to five spots at one optical origin.
	static constexpr unsigned MaxBeams = 5;
	std::array<const FDynamicLight*, MaxBeams> Beams{};
	unsigned Count = 0;

	bool Contains(const FDynamicLight* light) const
	{
		for (unsigned i = 0; i < Count; ++i)
			if (Beams[i] == light) return true;
		return false;
	}
};

struct HWShadowPuppetScene
{
	HWShadowPuppetLightSet Flashlight;
	FVector3 Origin;
	VSMatrix LightProjection = VSMatrix::identity();
	// Opaque sprite caps face the light. Edge endpoint pairs follow their winding.
	TArray<FVector3> Triangles;
	TArray<FVector3> Edges;
	TArray<const AActor*> Casters;
};

bool BuildShadowPuppetScene(HWDrawInfo& di, HWShadowPuppetScene& scene);
VSMatrix ShadowPuppetVulkanProjection(const VSMatrix& projection, const VSMatrix& view);

extern thread_local HWShadowPuppetLightSet HWShadowPuppetFlashlight;
