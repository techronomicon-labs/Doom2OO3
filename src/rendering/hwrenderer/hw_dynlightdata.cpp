// 
//---------------------------------------------------------------------------
//
// Copyright(C) 2002-2018 Christoph Oelckers
// All rights reserved.
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Lesser General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU Lesser General Public License for more details.
//
// You should have received a copy of the GNU Lesser General Public License
// along with this program.  If not, see http://www.gnu.org/licenses/
//
//--------------------------------------------------------------------------
//
/*
** gl_dynlight1.cpp
** dynamic light application
**
**/

#include "actorinlines.h"
#include "a_dynlight.h"
#include "hw_dynlightdata.h"
#include "hw_flashlight.h"
#include "hw_lightcompat.h"
#include "hw_shadowselection.h"
#include "hw_shadowpuppet.h"
#include"hw_cvars.h"
#include "v_video.h"
#include "hwrenderer/scene/hw_drawstructs.h"
#include "g_levellocals.h"
#include "quaternion.h"
#include "r_utility.h"
#include "types.h"

// If we want to share the array to avoid constant allocations it needs to be thread local unless it'd be littered with expensive synchronization.
thread_local FDynLightData lightdata;

const HWFlashlightView* HWFlashlightView::Current = nullptr;

HWFlashlightView::HWFlashlightView(const FRenderViewpoint* view) : Previous(Current)
{
	Current = nullptr;
	if (!view || view->showviewer || !view->sector || !view->camera ||
		view->camera != players[consoleplayer].mo || view->camera != players[consoleplayer].camera)
		return;

	// Older flashlight packages have a complete simulation pose but no
	// head-local mount. Continue using their original actor and angles.
	static const FName beamName("SDVKLocalFlashlightBeam"), offsetName("HeadOffset"), directionName("HeadDirection");
	auto* beamClass = PClass::FindClass(beamName);
	if (!beamClass) return;
	auto* offset = dyn_cast<PField>(beamClass->FindSymbol(offsetName, true));
	auto* direction = dyn_cast<PField>(beamClass->FindSymbol(directionName, true));
	if (!offset || !direction || offset->Type != TypeVector3 || direction->Type != TypeVector3 ||
		((offset->Flags | direction->Flags) & VARF_Meta))
		return;

	const auto rotation = DQuaternion::FromAngles(view->Angles.Yaw, view->Angles.Pitch, view->Angles.Roll);
	for (auto* light = view->ViewLevel->lights; light; light = light->next)
	{
		const auto* beam = light->target.Get();
		if (!beam || beam->master != view->camera || !light->IsActive() || !light->IsSpot() ||
			!beam->IsKindOf(beamClass) || !light->Sector || light->Sector->PortalGroup != view->sector->PortalGroup)
			continue;
		const auto* data = reinterpret_cast<const uint8_t*>(beam);
		const auto& localDir = *reinterpret_cast<const DVector3*>(data + direction->Offset);
		if (!(std::abs(localDir.LengthSquared() - 1.0) <= 1e-5)) continue;
		const auto& localPos = *reinterpret_cast<const DVector3*>(data + offset->Offset);
		const DVector3 origin = view->Pos + rotation * localPos;
		if (!std::isfinite(origin.X) || !std::isfinite(origin.Y) || !std::isfinite(origin.Z) ||
			view->ViewLevel->PointInRenderSubsector(origin)->sector->PortalGroup != light->Sector->PortalGroup)
			continue;
		Poses[Count++] = { light, origin, rotation * localDir };
		if (Count == Poses.size()) break;
	}
	if (Count) Current = this;
}

HWFlashlightView::~HWFlashlightView()
{
	Current = Previous;
}

const HWFlashlightPose* HWPresentedFlashlight(const FDynamicLight* light)
{
	const auto* view = HWFlashlightView::Current;
	if (view)
		for (unsigned i = 0; i < view->Count; ++i)
			if (view->Poses[i].Light == light) return &view->Poses[i];
	return nullptr;
}

DVector3 HWLightPosition(const FDynamicLight* light)
{
	if (auto* pose = HWPresentedFlashlight(light)) return pose->Position;
	return light->Pos;
}

DVector3 HWLightPositionRelative(const FDynamicLight* light, int portalGroup)
{
	return HWLightPosition(light) + light->Level->Displacements.getOffset(light->Sector->PortalGroup, portalGroup);
}

DVector3 HWSpotDirection(const FDynamicLight* light)
{
	if (auto* pose = HWPresentedFlashlight(light)) return pose->Direction;
	const auto pitch = *light->pPitch;
	return { light->target->Angles.Yaw.ToVector(pitch.Cos()), -pitch.Sin() };
}

//==========================================================================
//
// Light related CVARs
//
//==========================================================================

// These shouldn't be called 'gl...' anymore...
CVAR (Bool, gl_light_sprites, true, CVAR_ARCHIVE | CVAR_GLOBALCONFIG);
CVAR (Bool, gl_light_particles, true, CVAR_ARCHIVE | CVAR_GLOBALCONFIG);

CVAR (Bool, gl_light_shadow_nearest_dither, true, CVAR_ARCHIVE | CVAR_GLOBALCONFIG);

bool FDynamicLight::IsLocalFlashlight() const
{
	// Both variants of the existing flashlight inherit the same beam actor.
	static const FName beamClass("SDVKLocalFlashlightBeam");
	const auto actor = target.Get();
	return IsSpot() && actor && actor->IsKindOf(beamClass);
}

bool FDynamicLight::IsStageBEmitter() const
{
	static const FName pointClass("SDVKStageBPointEmitter");
	const auto actor = target.Get();
	return actor && (actor->IsKindOf(pointClass) || IsStageBDirectional());
}

bool FDynamicLight::IsStageBDirectional() const
{
	static const FName directionalClass("SDVKStageBDirectionalEmitter");
	const auto actor = target.Get();
	return actor && actor->IsKindOf(directionalClass);
}

bool StageBEmitterAllowed(const FDynLightData& dld, const FDynamicLight* light, const sector_t* receiver)
{
	// A receiver shares the emitter's authored sector, even across closed doors.
	if (!receiver || light->Sector != receiver || !screen->mShadowMap->Enabled() ||
		light->mShadowmapIndex < 0 || light->mShadowmapIndex >= static_cast<int>(HWShadowMapLightCapacity))
		return false;
	unsigned emitters = 0;
	for (auto& packed : dld.arrays[LIGHTARRAY_NORMAL])
		if (packed.flags & LIGHTINFO_STAGE_B_EMITTER) ++emitters;
	// A corridor can have nine authored wall strips on the same floor receiver.
	return emitters < 12;
}

//==========================================================================
//
// Sets up the parameters to render one dynamic light onto one plane
//
//==========================================================================
bool GetLight(FDynLightData& dld, int group, Plane & p, FDynamicLight * light, bool checkside, const sector_t* emitterReceiver)
{
	if (light->IsStageBEmitter() && !StageBEmitterAllowed(dld, light, emitterReceiver)) return false;
	DVector3 pos = HWLightPositionRelative(light, group);
	float radius = (light->GetRadius());

	auto dist = fabs(p.DistToPoint((float)pos.X, (float)pos.Z, (float)pos.Y));

	if (radius <= 0.f) return false;
	if (dist > radius) return false;
	if (checkside && p.PointOnSide((float)pos.X, (float)pos.Z, (float)pos.Y))
	{
		return false;
	}

	AddLightToList(dld, group, light, false, false);
	return true;
}

//==========================================================================
//
// Add one dynamic light to the light data list
//
//==========================================================================
void AddLightToList(FDynLightData &dld, int group, FDynamicLight * light, bool forceAttenuate, bool doTrace)
{
	FDynLightInfo info = {};
	const bool emitter = light->IsStageBEmitter();

	int i = LIGHTARRAY_NORMAL;

	DVector3 pos = HWLightPositionRelative(light, group);
	
	info.radius = light->GetRadius();

	float cs;
	if (light->IsAdditive()) 
	{
		cs = HWLightCompat::AdditiveGpuColorScale;
		i = LIGHTARRAY_ADDITIVE;
	}
	else 
	{
		cs = 1.0f;
	}

	if (light->target && (light->target->renderflags2 & RF2_LIGHTMULTALPHA))
		cs *= (float)light->target->Alpha;

	// Multiply intensity from GLDEFS
	cs *= (float)light->GetLightDefIntensity();
	if (emitter)
	{
		const int intensity = light->GetSecondaryIntensity();
		cs *= intensity == 0 ? 1.f : clamp(intensity, 0, 200) * 0.01f;
		info.radius = std::min(info.radius, 512.f);
		info.flags |= LIGHTINFO_STAGE_B_EMITTER;
		if (light->IsStageBDirectional())
		{
			const auto& angles = light->target->Angles;
			info.flags |= LIGHTINFO_STAGE_B_DIRECTIONAL;
			info.spotDirX = float(-angles.Yaw.Cos() * angles.Pitch.Cos());
			info.spotDirY = float(angles.Pitch.Sin());
			info.spotDirZ = float(-angles.Yaw.Sin() * angles.Pitch.Cos());
		}
	}

	info.r = HWLightCompat::NormalizeColorChannel(light->GetRed()) * cs;
	info.g = HWLightCompat::NormalizeColorChannel(light->GetGreen()) * cs;
	info.b = HWLightCompat::NormalizeColorChannel(light->GetBlue()) * cs;

	if (light->IsSubtractive())
	{
		DVector3 v(info.r, info.g, info.b);
		float length = (float)v.Length();
		
		info.r = length - info.r;
		info.g = length - info.g;
		info.b = length - info.b;
		i = LIGHTARRAY_SUBTRACTIVE;
	}

	if((light->shadowmapped || emitter) && screen->mShadowMap->Enabled())
	{
		info.flags |= LIGHTINFO_SHADOWMAPPED;
		info.shadowIndex = light->mShadowmapIndex;
	}
	else
	{
		info.shadowIndex = 1024;
	}

	// Store attenuate flag in the sign bit of the float.
	if (light->IsAttenuated() || forceAttenuate)
	{
		info.flags |= LIGHTINFO_ATTENUATED;
	}

	if (light->IsSpot())
	{
		info.flags |= LIGHTINFO_SPOT;
		if (HWShadowPuppetFlashlight.Contains(light)) info.flags |= LIGHTINFO_SHADOW_PUPPET;
		if ((gl_world_relief || gl_sprite_lighting_relief || gl_emitter_lighting) && light->IsLocalFlashlight()) info.flags |= LIGHTINFO_FLASHLIGHT;

		info.spotInnerAngle = (float)light->pSpotInnerAngle->Cos();
		info.spotOuterAngle = (float)light->pSpotOuterAngle->Cos();

		const auto direction = HWSpotDirection(light);
		info.spotDirX = float(-direction.X);
		info.spotDirY = float(-direction.Z);
		info.spotDirZ = float(-direction.Y);
	}

	if(light->Trace() && doTrace)
	{
		info.flags |= (LIGHTINFO_TRACE | LIGHTINFO_SHADOWMAPPED);
	}

	info.x = float(pos.X);
	info.z = float(pos.Y);
	info.y = float(pos.Z);

	info.softShadowRadius = (gl_light_shadow_filter == 0 && !gl_light_shadow_nearest_dither)? 0 : light->GetSoftShadowRadius();

	info.linearity = HWLightCompat::ClampLinearity(light->GetLinearity());

	info.strength = light->GetStrength();

	dld.arrays[i].Push(info);
}

void AddSunLightToList(FDynLightData& dld, float x, float y, float z, const FVector3& sundir, const FVector3& suncolor, bool doTrace)
{
	FDynLightInfo info = {};

	// Cheap way of faking a directional light. These are compatibility proxy
	// values rather than photometric units; PF-011 owns their documented meaning.
	float dist = HWLightCompat::SunProxyDistance;
	info.radius = HWLightCompat::SunProxyRadius;
	info.x = x + sundir.X * dist;
	info.z = y + sundir.Y * dist;
	info.y = z + sundir.Z * dist;
	info.r = suncolor.X;
	info.g = suncolor.Y;
	info.b = suncolor.Z;
	info.flags = LIGHTINFO_ATTENUATED | (doTrace ? (LIGHTINFO_TRACE | LIGHTINFO_SUN) : 0);
	info.strength = HWLightCompat::SunProxyStrength;

	dld.arrays[LIGHTARRAY_NORMAL].Push(info);
}
