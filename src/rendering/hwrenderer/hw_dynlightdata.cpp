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
#include "hw_lightcompat.h"
#include"hw_cvars.h"
#include "v_video.h"
#include "hwrenderer/scene/hw_drawstructs.h"
#include "g_levellocals.h"
#include "sprites.h"
#include "texturemanager.h"
#include "textures.h"
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>

// If we want to share the array to avoid constant allocations it needs to be thread local unless it'd be littered with expensive synchronization.
thread_local FDynLightData lightdata;

//==========================================================================
//
// Light related CVARs
//
//==========================================================================

// These shouldn't be called 'gl...' anymore...
CVAR (Bool, gl_light_sprites, true, CVAR_ARCHIVE | CVAR_GLOBALCONFIG);
CVAR (Bool, gl_light_particles, true, CVAR_ARCHIVE | CVAR_GLOBALCONFIG);

CVAR (Bool, gl_light_shadow_nearest_dither, true, CVAR_ARCHIVE | CVAR_GLOBALCONFIG);
// Opt-in during qualification; the owner-facing visual profile enables this.
CVAR (Bool, gl_actor_light_shadows, false, CVAR_ARCHIVE | CVAR_GLOBALCONFIG);



// Shadow sampling uses an independently downsampled source *alpha* mask.
// It never changes the original sprite's texture/albedo or creates a decal.
// The light-facing sprite rotation and mirrored frame follow GetSpriteFrame.
extern TArray<spritedef_t> sprites;

namespace
{
struct ActorShadowCacheEntry
{
	const FDynamicLight* light = nullptr;
	const FLevelLocals* level = nullptr;
	int group = 0;
	uint64_t timestamp = 0;
	int count = 0;
	FActorShadowCaster casters[MaxActorShadowCastersPerLight] = {};
};

struct ActorMaskCacheEntry
{
	const FGameTexture* texture = nullptr;
	const FLevelLocals* level = nullptr;
	uint64_t timestamp = 0;
	bool valid = false;
	uint32_t words[ActorShadowMaskWords] = {};
};

thread_local std::array<ActorShadowCacheEntry, 64> actorShadowCache;
thread_local size_t actorShadowCacheNext = 0;
thread_local std::array<ActorMaskCacheEntry, 64> actorMaskCache;
thread_local size_t actorMaskCacheNext = 0;

bool SourceAlphaMask(const FLevelLocals* level, uint64_t timestamp,
	FGameTexture* texture, uint32_t (&words)[ActorShadowMaskWords])
{
	for (const auto& cached : actorMaskCache)
	{
		if (cached.texture == texture && cached.level == level &&
			cached.timestamp == timestamp)
		{
			if (cached.valid)
				for (int w = 0; w < ActorShadowMaskWords; ++w) words[w] = cached.words[w];
			return cached.valid;
		}
	}

	ActorMaskCacheEntry entry;
	entry.texture = texture;
	entry.level = level;
	entry.timestamp = timestamp;
	if (texture && texture->GetTexture() && texture->GetTexelWidth() > 0 &&
		texture->GetTexelHeight() > 0 && texture->GetTexelWidth() <= 2048 &&
		texture->GetTexelHeight() <= 2048)
	{
		// Real image data, not a procedural solid silhouette. This operation
		// is cached across different lights selecting the same animated frame.
		auto source = texture->GetTexture()->CreateTexBuffer(0);
		const int width = source.mWidth, height = source.mHeight;
		if (source.mBuffer && width > 0 && width <= 2048 &&
			height > 0 && height <= 2048)
		{
			int onPixels = 0;
			for (int y = 0; y < ActorShadowMaskHeight; ++y)
			{
				int py = std::min(height - 1, (2 * y + 1) * height / (2 * ActorShadowMaskHeight));
				for (int x = 0; x < ActorShadowMaskWidth; ++x)
				{
					int px = std::min(width - 1, (2 * x + 1) * width / (2 * ActorShadowMaskWidth));
					const uint8_t a = source.mBuffer[4 * (py * width + px) + 3];
					if (a >= 96)
					{
						entry.words[y / 2] |= uint32_t(1) << ((y % 2) * ActorShadowMaskWidth + x);
						++onPixels;
					}
				}
			}
			entry.valid = onPixels > 0;
		}
	}
	actorMaskCache[actorMaskCacheNext++ % actorMaskCache.size()] = entry;
	if (entry.valid)
		for (int w = 0; w < ActorShadowMaskWords; ++w) words[w] = entry.words[w];
	return entry.valid;
}

bool BuildActorSilhouette(FActorShadowCaster& caster, AActor* actor,
	const DVector3& origin, const DVector3& pos, const FLevelLocals* level,
	uint64_t timestamp)
{
	// The authored source-alpha renderer can only reproduce upright facesprites
	// at present; models, wall/flat sprites and picnum overrides need their own
	// source-relative geometry contracts rather than solid fake blockers.
	if ((actor->renderflags & RF_SPRITETYPEMASK) != RF_FACESPRITE ||
		actor->sprite < 0 || actor->sprite >= int(sprites.Size()))
		return false;

	const DVector2 toActor(pos.X - origin.X, pos.Y - origin.Y);
	const double distance = toActor.Length();
	if (distance < 1.0 || !std::isfinite(distance))
		return false;
	bool mirror = false;
	const DAngle lightFacing = actor->GetSpriteAngle(toActor.Angle(), 0.0);
	const FTextureID pic = sprites[actor->sprite].GetSpriteFrame(
		actor->frame, -1, lightFacing, &mirror, !!(actor->renderflags & RF_SPRITEFLIP));
	if (!pic.isValid()) return false;
	FGameTexture* texture = TexMan.GetGameTexture(pic, false);
	if (!texture || !texture->isValid() || !texture->GetTexture()) return false;

	uint32_t alpha[ActorShadowMaskWords] = {};
	if (!SourceAlphaMask(level, timestamp, texture, alpha))
		return false;

	auto rect = texture->GetSpritePositioning(true).GetSpriteRect();
	const DVector2 scale = actor->InterpolatedScale(0.0);
	const float sx = float(scale.X), sy = float(scale.Y);
	if (!std::isfinite(sx) || !std::isfinite(sy) || sx <= 0.0f || sy <= 0.0f ||
		sx > 8.0f || sy > 8.0f)
		return false;
	// Match the real sprite quad's offset and display size, not collision radius.
	const bool flipX = mirror ^ bool(actor->renderflags & RF_XFLIP) ^
		bool(actor->renderflags & RF_SPRITEFLIP);
	const bool flipY = !!(actor->renderflags & RF_YFLIP);
	if (flipX) rect.left = -rect.width - rect.left;
	rect.Scale(sx, sy);
	const float top = float(pos.Z + actor->WorldOffset.Z) - rect.top;
	const float bottom = top - rect.height;
	const float left = -rect.left - rect.width;
	const float right = -rect.left;
	if (!std::isfinite(top) || !std::isfinite(bottom) || bottom >= top ||
		!std::isfinite(left) || !std::isfinite(right) || left >= right)
		return false;

	caster.x = float(pos.X + actor->WorldOffset.X);
	caster.y = float(pos.Z + actor->WorldOffset.Z);
	caster.z = float(pos.Y + actor->WorldOffset.Y);
	caster.radius = float(actor->radius);
	caster.bottom = bottom;
	caster.top = top;
	caster.planeNx = float(toActor.X / distance);
	caster.planeNz = float(toActor.Y / distance);
	caster.left = left;
	caster.right = right;
	caster.mirrorX = flipX ? 1.0f : 0.0f;
	caster.mirrorY = flipY ? 1.0f : 0.0f;
	for (int w = 0; w < ActorShadowMaskWords; ++w) caster.alphaWords[w] = alpha[w];
	return true;
}

void CollectActorShadowCasters(FDynLightInfo& info, FDynamicLight* light, int group)
{
	if (!gl_actor_light_shadows || !light || !light->Level || light->GetRadius() <= 0 ||
		light->GetRadius() >= HWLightCompat::SunProxyRadius)
		return;
	const auto frameTimestamp = uint64_t(screen->FrameTime);
	for (const auto& cached : actorShadowCache)
	{
		if (cached.light == light && cached.level == light->Level && cached.group == group &&
			cached.timestamp == frameTimestamp)
		{
			info.actorShadowCount = cached.count;
			for (int i = 0; i < cached.count; ++i) info.actorShadowCasters[i] = cached.casters[i];
			return;
		}
	}

	ActorShadowCacheEntry fresh;
	fresh.light = light;
	fresh.level = light->Level;
	fresh.group = group;
	fresh.timestamp = frameTimestamp;
	float ranks[MaxActorShadowCastersPerLight];
	for (float& rank : ranks) rank = std::numeric_limits<float>::infinity();
	const DVector3 origin = light->PosRelative(group);
	const float reach = float(light->GetRadius());
	auto iter = light->Level->GetThinkerIterator<AActor>();
	for (AActor* candidate = iter.Next(); candidate != nullptr; candidate = iter.Next())
	{
		if (candidate == light->target || !candidate->Sector ||
			candidate->Sector->PortalGroup != group || !(candidate->flags & MF_SHOOTABLE))
			continue;
		const float radius = float(candidate->radius);
		const float height = float(candidate->Height);
		if (!std::isfinite(radius) || !std::isfinite(height) || radius <= 0.0f ||
			height <= 0.0f || radius > 128.0f || height > 512.0f)
			continue;
		const DVector3 pos = candidate->PosRelative(group);
		const float x = float(pos.X);
		const float y = float(pos.Z) + height * 0.5f;
		const float z = float(pos.Y);
		const float dx = float(origin.X) - x;
		const float dy = float(origin.Z) - y;
		const float dz = float(origin.Y) - z;
		const float dist2 = dx*dx + dy*dy + dz*dz;
		const float range = reach + radius;
		if (!(dist2 < range*range))
			continue;

		FActorShadowCaster caster = {};
		if (!BuildActorSilhouette(caster, candidate, origin, pos,
			light->Level, frameTimestamp))
			continue;
		for (int i = 0; i < MaxActorShadowCastersPerLight; ++i)
		{
			if (dist2 < ranks[i])
			{
				for (int j = MaxActorShadowCastersPerLight - 1; j > i; --j)
				{
					ranks[j] = ranks[j - 1];
					fresh.casters[j] = fresh.casters[j - 1];
				}
				ranks[i] = dist2;
				fresh.casters[i] = caster;
				if (fresh.count < MaxActorShadowCastersPerLight) ++fresh.count;
				break;
			}
		}
	}
	actorShadowCache[actorShadowCacheNext++ % actorShadowCache.size()] = fresh;
	info.actorShadowCount = fresh.count;
	for (int i = 0; i < fresh.count; ++i) info.actorShadowCasters[i] = fresh.casters[i];
}
} // namespace

//==========================================================================
//
// Sets up the parameters to render one dynamic light onto one plane
//
//==========================================================================
bool GetLight(FDynLightData& dld, int group, Plane & p, FDynamicLight * light, bool checkside)
{
	DVector3 pos = light->PosRelative(group);
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

	int i = LIGHTARRAY_NORMAL;

	DVector3 pos = light->PosRelative(group);
	
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

	if(light->shadowmapped && screen->mShadowMap->Enabled())
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

		info.spotInnerAngle = (float)light->pSpotInnerAngle->Cos();
		info.spotOuterAngle = (float)light->pSpotOuterAngle->Cos();

		DAngle negPitch = -*light->pPitch;
		DAngle Angle = light->target->Angles.Yaw;
		double xzLen = negPitch.Cos();
		info.spotDirX = float(-Angle.Cos() * xzLen);
		info.spotDirY = float(-negPitch.Sin());
		info.spotDirZ = float(-Angle.Sin() * xzLen);
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

	CollectActorShadowCasters(info, light, group);
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
