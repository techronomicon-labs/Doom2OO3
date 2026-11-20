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
#include "doom_levelmesh.h"
#include "hwrenderer/diagnostics/hw_sdvkdiagnostics.h"
#include "hwrenderer/scene/hw_drawinfo.h"
#include "hwrenderer/scene/hw_drawstructs.h"
#include "g_levellocals.h"
#include "p_trace.h"
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
	DVector3 lastMount, clippedOrigin;
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
		if (Count == 0 || localPos != lastMount)
		{
			clippedOrigin = P_ClipFlashlightMount(view->Pos, view->sector, rotation * localPos);
			lastMount = localPos;
		}
		Poses[Count++] = { light, clippedOrigin, rotation * localDir };
		if (Count == Poses.size()) break;
	}
	if (!Count) return;
	Current = this;
	if (!gl_flashlight_hotspot && !gl_flashlight_unevenness) return;

	// Symmetric outer lobes average to the trimmed optical axis of the lamp.
	// Use head-local up so rolling or aiming vertically cannot rotate the lens pattern.
	DVector3 axis(0, 0, 0);
	for (unsigned i = 0; i < Count; ++i) axis += Poses[i].Direction;
	const auto right = (axis.Unit() ^ (rotation * DVector3(0, 0, 1))).Unit();
	const auto up = (right ^ axis).Unit();
	double halfWidth = 0, halfHeight = 0;
	for (unsigned i = 0; i < Count; ++i)
	{
		const auto& pose = Poses[i];
		const double cone = pose.Light->pSpotOuterAngle->Radians();
		halfWidth = std::max(halfWidth, cone + std::asin(std::min(1., std::abs(pose.Direction | right))));
		halfHeight = std::max(halfHeight, cone + std::asin(std::min(1., std::abs(pose.Direction | up))));
	}
	if (!(halfWidth > 0 && halfHeight > 0 && halfWidth < M_PI / 2 && halfHeight < M_PI / 2)) return;
	const auto horizontal = right / std::sin(halfWidth), vertical = up / std::sin(halfHeight);
	LensRight = {float(horizontal.X), float(horizontal.Z), float(horizontal.Y), gl_flashlight_hotspot / 100.f};
	LensUp = {float(vertical.X), float(vertical.Z), float(vertical.Y), gl_flashlight_unevenness / 100.f};
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

const HWFlashlightView* HWFlashlightView::ProfileFor(const FDynamicLight* light)
{
	if (!Current || (Current->LensRight.W == 0 && Current->LensUp.W == 0)) return nullptr;
	return HWPresentedFlashlight(light) ? Current : nullptr;
}

float HWFlashlightView::ProfileGain(const FVector3& fromLamp) const
{
	// Keep CPU-lit sprites and the weapon sample consistent with the scene shader.
	const float u = fromLamp | LensRight.XYZ(), v = fromLamp | LensUp.XYZ();
	const float core = std::max(0.f, 1.f - 3.f * (u * u + v * v));
	const FVector2 brightOffset(u + .30f, v - .25f), shadeOffset(u - .41f, v + .18f);
	const float bright = std::max(0.f, 1.f - 2.5f * brightOffset.X * brightOffset.X - 6.f * brightOffset.Y * brightOffset.Y);
	const float shade = std::max(0.f, 1.f - 7.f * shadeOffset.X * shadeOffset.X - 2.5f * shadeOffset.Y * shadeOffset.Y);
	return (1.f + LensRight.W * (1.1f * core * core - .25f)) *
		(1.f + LensUp.W * (.32f * bright * bright - .48f * shade * shade));
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

int HWFlashlightMapGroup(const HWDrawInfo* view, const FDynamicLight* light, int portalGroup, const sector_t* receiver)
{
	if (!view || !view->UsesFlashlightMapShadows() || !receiver || !light->IsLocalFlashlight() ||
		light->target->master != view->Viewpoint.camera || !light->Sector || light->Sector->PortalGroup != portalGroup)
		return 0;

	const auto& groups = view->Level->levelMesh->sectorGroup;
	const int group = groups[receiver->Index()];
	return group == groups[light->Sector->Index()] ? group : 0;
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

bool StageBEmitterAllowed(const FDynLightData& dld, const FDynamicLight* light, const sector_t* receiver, bool traceAcrossSectors)
{
	if (!receiver || (light->Sector != receiver && !traceAcrossSectors) || !screen->mShadowMap->Enabled() ||
		light->mShadowmapIndex < 0 || light->mShadowmapIndex >= static_cast<int>(HWShadowMapLightCapacity))
		return false;
	unsigned emitters = 0, neighboring = 0;
	for (auto& packed : dld.arrays[LIGHTARRAY_NORMAL])
	{
		if (!(packed.flags & LIGHTINFO_STAGE_B_EMITTER)) continue;
		++emitters;
		if (packed.flags & LIGHTINFO_POINT_MAP_SHADOW) ++neighboring;
	}
	// Reserve room for the receiver's own fixtures and bound the geometry traces per pixel.
	if (traceAcrossSectors && neighboring >= 4) return false;
	// A corridor can have nine authored wall strips on the same floor receiver.
	return emitters < 12;
}

//==========================================================================
//
// Sets up the parameters to render one dynamic light onto one plane
//
//==========================================================================
bool GetLight(FDynLightData& dld, int group, Plane & p, FDynamicLight * light, bool checkside,
	const sector_t* emitterReceiver, HWDrawInfo* worldView, const sector_t* mapReceiver)
{
	DVector3 pos = HWLightPositionRelative(light, group);
	float radius = light->GetViewRadius(worldView && worldView->UsesEmitterLighting());

	auto dist = fabs(p.DistToPoint((float)pos.X, (float)pos.Z, (float)pos.Y));

	if (radius <= 0.f) return false;
	if (dist > radius) return false;
	if (checkside && p.PointOnSide((float)pos.X, (float)pos.Z, (float)pos.Y))
	{
		return false;
	}

	int mapGroup = HWFlashlightMapGroup(worldView, light, group, mapReceiver);
	int mapShadowFlag = mapGroup ? LIGHTINFO_FLASHLIGHT_MAP_SHADOW : 0;
	const bool emitter = light->IsStageBEmitter();
	const bool neighboringFixture = emitter && emitterReceiver && emitterReceiver != light->Sector
		&& !light->IsStageBDirectional() && (light->Level->flags3 & LEVEL3_STAGEBLAYOUT);
	if (worldView && worldView->DrawingOpaqueMapShadows && mapReceiver && light->Sector->PortalGroup == group
		&& !light->IsSpot() && !light->DontShadowmap()
		&& (neighboringFixture || (gl_projectile_map_shadows && light->IsProjectileLight())))
	{
		// Portal links can put a light on a disconnected receiver even when both have portal group zero.
		const auto& groups = worldView->Level->levelMesh->sectorGroup;
		if (groups[mapReceiver->Index()] == groups[light->Sector->Index()])
		{
			mapGroup = groups[mapReceiver->Index()];
			mapShadowFlag = LIGHTINFO_POINT_MAP_SHADOW;
		}
	}
	if (emitter && !StageBEmitterAllowed(dld, light, emitterReceiver, mapShadowFlag != 0)) return false;
	AddLightToList(dld, group, light, radius, false, false, mapShadowFlag, mapGroup);
	if (mapShadowFlag && SdvkDiagnostics::StateEnabled())
	{
		if (mapShadowFlag == LIGHTINFO_FLASHLIGHT_MAP_SHADOW) ++worldView->FlashlightMapShadowLinks;
		else if (!emitter && light->GetProjectileLightScale() > 0) ++worldView->ProjectileMapShadowLinks;
	}
	return true;
}

//==========================================================================
//
// Add one dynamic light to the light data list
//
//==========================================================================
void AddLightToList(FDynLightData &dld, int group, FDynamicLight * light, float radius, bool forceAttenuate, bool doTrace,
	int mapShadowFlag, int mapGroup)
{
	FDynLightInfo info = {};
	const bool emitter = light->IsStageBEmitter();

	int i = LIGHTARRAY_NORMAL;

	DVector3 pos = HWLightPositionRelative(light, group);
	
	info.radius = radius;

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

	cs *= (float)light->GetLightDefIntensity() * light->GetProjectileLightScale();
	if (emitter)
	{
		cs *= light->Sector->StageBFixtureOutput();
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

	if (mapShadowFlag && cs > 0)
	{
		info.flags |= mapShadowFlag;
		info.shadowIndex = mapGroup;
	}
	else if ((light->shadowmapped || emitter) && screen->mShadowMap->Enabled())
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
		if (HWFlashlightView::ProfileFor(light)) info.flags |= LIGHTINFO_FLASHLIGHT_PROFILE;
		if (HWShadowPuppetFlashlight.Contains(light)) info.flags |= LIGHTINFO_SHADOW_PUPPET;
		if ((gl_world_relief || gl_sprite_lighting_relief || gl_emitter_lighting) && light->IsLocalFlashlight()) info.flags |= LIGHTINFO_FLASHLIGHT;

		info.spotInnerAngle = (float)light->pSpotInnerAngle->Cos();
		info.spotOuterAngle = (float)light->pSpotOuterAngle->Cos();

		const auto direction = HWSpotDirection(light);
		info.spotDirX = float(-direction.X);
		info.spotDirY = float(-direction.Z);
		info.spotDirZ = float(-direction.Y);
	}

	if (light->Trace() && doTrace && !mapShadowFlag)
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
