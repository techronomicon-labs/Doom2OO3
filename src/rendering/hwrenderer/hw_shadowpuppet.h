#pragma once

#include "matrix.h"
#include "hw_shadowpuppetmesh.h"
#include <array>
#include <unordered_set>

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
	FVector2 DepthRange; // nearest caster axial distance and perspective depth coefficient
	VSMatrix LightProjection = VSMatrix::identity();
	HWShadowPuppetMesh Mesh;
	std::unordered_set<const AActor*> Casters;
};

bool BuildShadowPuppetScene(HWDrawInfo& di, HWShadowPuppetScene& scene, bool stencil);
VSMatrix ShadowPuppetVulkanProjection(const VSMatrix& projection, const VSMatrix& view);

extern thread_local HWShadowPuppetLightSet HWShadowPuppetFlashlight;
