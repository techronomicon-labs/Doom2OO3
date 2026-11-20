#pragma once

#include "vectors.h"
#include <array>

struct FDynamicLight;
struct FRenderViewpoint;

struct HWFlashlightPose
{
	const FDynamicLight* Light;
	DVector3 Position, Direction;
};

// One head transform for all spotlight lobes and both eyes. Render workers
// read this snapshot; the light actors and their simulation links stay intact.
class HWFlashlightView
{
public:
	explicit HWFlashlightView(const FRenderViewpoint* view);
	~HWFlashlightView();
	HWFlashlightView(const HWFlashlightView&) = delete;
	HWFlashlightView& operator=(const HWFlashlightView&) = delete;

private:
	friend const HWFlashlightPose* HWPresentedFlashlight(const FDynamicLight*);
	static const HWFlashlightView* Current;
	const HWFlashlightView* Previous;
	std::array<HWFlashlightPose, 5> Poses;
	unsigned Count = 0;
};

const HWFlashlightPose* HWPresentedFlashlight(const FDynamicLight* light);
DVector3 HWLightPosition(const FDynamicLight* light);
DVector3 HWLightPositionRelative(const FDynamicLight* light, int portalGroup);
DVector3 HWSpotDirection(const FDynamicLight* light);
