#include "doom_pbr_pick.h"

#include "doomstat.h"
#include "gamestate.h"
#include "g_levellocals.h"
#include "p_trace.h"
#include "r_utility.h"
#include "texturemanager.h"

namespace
{
FTextureID WallTexture(const FTraceResults& hit)
{
	if (!hit.Line || !hit.Line->sidedef[hit.Side])
		return {};

	auto side = hit.Line->sidedef[hit.Side];
	switch (hit.Tier)
	{
	case TIER_Upper: return side->GetTexture(side_t::top);
	case TIER_Lower: return side->GetTexture(side_t::bottom);
	case TIER_Middle: return side->GetTexture(side_t::mid);
	case TIER_FFloor:
		// A 3D floor can borrow the upper/lower texture of the hit side.
		if (!hit.ffloor || (hit.ffloor->flags & FF_FOG)) return {};
		if (hit.ffloor->flags & FF_UPPERTEXTURE) return side->GetTexture(side_t::top);
		if (hit.ffloor->flags & FF_LOWERTEXTURE) return side->GetTexture(side_t::bottom);
		if (auto master = hit.ffloor->master)
		{
			if (master->sidedef[0]) return master->sidedef[0]->GetTexture(side_t::mid);
		}
		break;
	}
	return {};
}
}

FGameTexture* PickPBRMaterial()
{
	if (gamestate != GS_LEVEL) return nullptr;

	auto& view = r_viewpoint;
	auto camera = players[consoleplayer].camera;
	if (!camera || view.camera != camera || view.ViewLevel != camera->Level ||
		view.IsOrtho() || view.IsAllowedOoB())
		return nullptr;

	auto sector = view.ViewLevel->PointInSector(view.Pos);
	if (!sector) return nullptr;

	FTraceResults hit{};
	// Use the last rendered eye and aim. Ignore actor bounds and gameplay-only
	// line blockers so this picks world surfaces without activating specials.
	Trace(view.Pos, sector, view.ViewVector3D, 8192.0, ActorFlags{}, 0, view.camera, hit, TRACE_NoSky);

	FTextureID id;
	switch (hit.HitType)
	{
	case TRACE_HitWall:
		id = WallTexture(hit);
		break;
	case TRACE_HitFloor:
	case TRACE_HitCeiling:
		// Straight up/down can find a plane without crossing a line.
		id = hit.HitTexture;
		if (id == skyflatnum) return nullptr;
		break;
	default:
		return nullptr;
	}

	// Use the effective animated texture, just as the wall and flat drawers do.
	return id.isValid() ? TexMan.GetGameTexture(id, true) : nullptr;
}
