#include "actorinlines.h"
#include "a_dynlight.h"
#include "c_cvars.h"
#include "g_levellocals.h"
#include "p_local.h"
#include "r_utility.h"
#include "hw_shadowpuppet.h"

#include <algorithm>
#include <array>
#include <cmath>

CVAR(Int, gl_shadow_puppets, 0, CVAR_ARCHIVE | CVAR_GLOBALCONFIG);
CVAR(Int, gl_shadow_puppets_active, 0, 0);

thread_local const FDynamicLight* HWShadowPuppetFlashlight = nullptr;

namespace
{
	constexpr unsigned MaxCasters = 4;
	constexpr unsigned Sides = 6;

	void AddPrimitive(TArray<FVector3>& mesh, FVector3 bottom, FVector3 top, float bottomRadius, float topRadius)
	{
		std::array<FVector3, Sides> low, high;
		for (unsigned i = 0; i < Sides; ++i)
		{
			const float angle = float(i * (2.0 * M_PI / Sides));
			const FVector3 radial(std::cos(angle), 0.f, std::sin(angle));
			low[i] = bottom + radial * bottomRadius;
			high[i] = top + radial * topRadius;
		}
		for (unsigned i = 0; i < Sides; ++i)
		{
			const unsigned next = (i + 1) % Sides;
			mesh.Push(bottom); mesh.Push(low[i]); mesh.Push(low[next]);
			mesh.Push(top); mesh.Push(high[next]); mesh.Push(high[i]);
			mesh.Push(low[i]); mesh.Push(high[i]); mesh.Push(high[next]);
			mesh.Push(low[i]); mesh.Push(high[next]); mesh.Push(low[next]);
		}
	}

	const TArray<FVector3>& ImpPuppet()
	{
		static const TArray<FVector3> mesh = [] {
			TArray<FVector3> vertices;
			// Forward, height, lateral. A neutral asymmetrical stance reads in motion.
			AddPrimitive(vertices, {0, 19, 0}, {-1, 43, 0}, 8, 11);
			AddPrimitive(vertices, {0, 39, 0}, {2, 54, 0}, 7, 6);
			AddPrimitive(vertices, {5, 26, -16}, {-1, 39, -9}, 3.5f, 5);
			AddPrimitive(vertices, {8, 28, 15}, {-1, 39, 9}, 3.5f, 5);
			AddPrimitive(vertices, {4, 0, -5}, {0, 23, -4}, 4.5f, 5);
			AddPrimitive(vertices, {-5, 0, 5}, {1, 23, 4}, 4.5f, 5);
			return vertices;
		}();
		return mesh;
	}

	FVector3 RenderPosition(const DVector3& point)
	{
		return { float(point.X), float(point.Z), float(point.Y) };
	}
}

VSMatrix ShadowPuppetVulkanProjection(const VSMatrix& projection, const VSMatrix& view)
{
	VSMatrix clip = VSMatrix::identity();
	clip.translate(0.f, 0.f, 0.5f);
	clip.scale(1.f, 1.f, 0.5f);
	clip.multMatrix(projection);
	clip.multMatrix(view);
	return clip;
}

bool BuildShadowPuppetScene(const FRenderViewpoint& view, HWShadowPuppetScene& scene)
{
	if (!view.camera || !view.sector || !view.camera->player || view.camera != view.camera->player->mo)
		return false;
	auto& level = *view.camera->Level;
	// A proxy from another portal group does not belong in the root geometry pass.
	if (view.sector->PortalGroup != 0 || level.linePortals.Size() != 0)
		return false;
	for (auto& sector : level.sectors)
	{
		if (sector.PortalIsLinked(sector_t::floor) || sector.PortalIsLinked(sector_t::ceiling) ||
			sector.e->XFloor.ffloors.Size() != 0 || sector.GetHeightSec())
			return false;
	}

	const FDynamicLight* beam = nullptr;
	for (auto* candidate = level.lights; candidate; candidate = candidate->next)
	{
		if (!candidate->IsActive() || !candidate->IsLocalFlashlight() || candidate->target->master != view.camera)
			continue;
		// The flashlight can represent an elliptical beam with several spots.
		if (beam)
			return false;
		beam = candidate;
	}
	if (!beam || !beam->Sector || beam->Sector->PortalGroup != 0 || beam->GetRadius() <= 0.f)
		return false;

	const float radius = beam->GetRadius();
	const DAngle yaw = beam->target->Angles.Yaw;
	const DAngle pitch = *beam->pPitch;
	const FVector3 forward(float(yaw.Cos() * pitch.Cos()), float(-pitch.Sin()), float(yaw.Sin() * pitch.Cos()));
	const FVector3 origin = RenderPosition(beam->Pos);
	struct Caster { AActor* Actor; FVector3 Base; float Distance; };
	std::array<Caster, MaxCasters> casters {};
	unsigned count = 0;
	auto actors = level.GetThinkerIterator<AActor>(FName("DoomImp"));
	while (auto* actor = actors.Next())
	{
		if (actor == view.camera || actor->health <= 0 || actor->Alpha <= 0 || actor->renderflags & RF_INVISIBLE ||
			!actor->Sector || actor->Sector->PortalGroup != 0)
			continue;
		const FVector3 base = RenderPosition(actor->InterpolatedPosition(view.TicFrac));
		const FVector3 relative = base + FVector3(0, 26, 0) - origin;
		const float distance = relative.Length();
		if (distance > radius + 32 || (relative | forward) < -32 ||
			(count == MaxCasters && distance >= casters.back().Distance) ||
			!P_CheckSight(beam->target.Get(), actor, SF_IGNOREVISIBILITY))
			continue;
		unsigned slot = std::min(count++, MaxCasters - 1);
		while (slot > 0 && casters[slot - 1].Distance > distance)
		{
			casters[slot] = casters[slot - 1];
			--slot;
		}
		casters[slot] = { actor, base, distance };
		count = std::min(count, MaxCasters);
	}
	if (!count)
		return false;

	const auto& mesh = ImpPuppet();
	for (unsigned i = 0; i < count; ++i)
	{
		const auto& caster = casters[i];
		const auto angles = caster.Actor->InterpolatedAngles(view.TicFrac);
		const float cosine = float(angles.Yaw.Cos()), sine = float(angles.Yaw.Sin());
		for (const auto& vertex : mesh)
			scene.Triangles.Push(caster.Base + FVector3(cosine * vertex.X - sine * vertex.Z, vertex.Y,
				sine * vertex.X + cosine * vertex.Z));
	}
	const FVector3 aim = origin + forward;
	const FVector3 up = std::abs(forward.Y) < 0.98f ? FVector3(0, 1, 0) : FVector3(0, 0, 1);
	VSMatrix lightView = VSMatrix::identity(), projection = VSMatrix::identity();
	lightView.lookAt(origin.X, origin.Y, origin.Z, aim.X, aim.Y, aim.Z, up.X, up.Y, up.Z);
	projection.perspective(float(2.0 * beam->pSpotOuterAngle->Degrees()), 1.f, 1.f, radius + 32.f);
	scene.LightProjection = ShadowPuppetVulkanProjection(projection, lightView);
	scene.Flashlight = beam;
	scene.Origin = origin;
	return true;
}
