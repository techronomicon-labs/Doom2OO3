#include "actorinlines.h"
#include "a_dynlight.h"
#include "c_cvars.h"
#include "g_levellocals.h"
#include "p_local.h"
#include "r_utility.h"
#include "r_visualtime.h"
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
	// Eight convex hulls have 89 rim vertices and 146 triangles in total.
	// The capped volume cannot exceed 12 * (89 - 8) vertices per puppet.
	constexpr unsigned VerticesPerPuppet = 438;

	struct PuppetRing
	{
		FVector3 Center;
		float Radius;
	};

	template<size_t Sides, size_t RingCount>
	void AddHull(TArray<FVector3>& mesh, const std::array<PuppetRing, RingCount>& profile, float width, float length = 1.f)
	{
		static const auto directions = [] {
			std::array<FVector2, Sides> ring;
			for (size_t i = 0; i < Sides; ++i)
			{
				// Four-sided soles have flat sides along the forward and lateral axes.
				const float angle = float((i + (Sides == 4 ? 0.5 : 0.0)) * (2.0 * M_PI / Sides));
				ring[i] = FVector2(std::cos(angle), std::sin(angle));
			}
			return ring;
		}();
		std::array<std::array<FVector3, Sides>, RingCount> rings;
		for (size_t row = 0; row < RingCount; ++row)
			for (size_t i = 0; i < Sides; ++i)
			{
				const auto& radial = directions[i];
				rings[row][i] = profile[row].Center +
					FVector3(length * radial.X, 0.f, width * radial.Y) * profile[row].Radius;
			}

		const auto append = [&](const FVector3& a, const FVector3& b, const FVector3& c) {
			mesh.Push(a); mesh.Push(b); mesh.Push(c);
		};
		// Triangulate from existing rim vertices. Caps and side walls have
		// opposite edge winding, with no additional vertices on the caps.
		for (size_t i = 1; i + 1 < Sides; ++i)
		{
			append(rings.front()[0], rings.front()[i], rings.front()[i + 1]);
			append(rings.back()[0], rings.back()[i + 1], rings.back()[i]);
		}
		for (size_t row = 1; row < RingCount; ++row)
		{
			const auto& low = rings[row - 1];
			const auto& high = rings[row];
			for (size_t i = 0; i < Sides; ++i)
			{
				const size_t next = (i + 1) % Sides;
				append(low[i], high[i], high[next]);
				append(low[i], high[next], low[next]);
			}
		}
	}

	struct PuppetStep
	{
		uint32_t Actor = 0;
		FVector3 Base = {};
		float Phase = 0.f;
		float Strength = 0.f;
	};

	struct PuppetWalk
	{
		const FLevelLocals* Level = nullptr;
		uint64_t Generation = 0;
		uint64_t Frame = 0;
		double Tic = 0;
		std::array<PuppetStep, MaxCasters> Steps;
		unsigned Count = 0;
	};

	PuppetStep UpdateStep(const AActor& actor, FVector3 base, const PuppetWalk& previous, float elapsed)
	{
		PuppetStep current { actor.SpawnOrder, base };
		for (unsigned i = 0; i < previous.Count; ++i)
		{
			const auto& last = previous.Steps[i];
			if (last.Actor != actor.SpawnOrder)
				continue;
			const auto delta = base - last.Base;
			const float travelled = std::hypot(delta.X, delta.Z);
			// A warp or dropped simulation samples are not a walking stride.
			if (travelled > 8.f + elapsed * 12.f)
				break;
			const auto motion = actor.Pos() - actor.Prev;
			const float speed = float(std::hypot(motion.X, motion.Y));
			const float target = std::clamp((speed - 0.10f) / 1.30f, 0.f, 1.f);
			const float settle = 1.f - std::exp(-elapsed * (target > last.Strength ? 0.45f : 0.36f));
			current.Strength = last.Strength + (target - last.Strength) * settle;
			current.Phase = std::fmod(last.Phase + travelled * float(M_PI / 16.0), float(2.0 * M_PI));
			if (current.Strength < 0.02f && target == 0.f)
				current.Strength = 0.f;
			break;
		}
		return current;
	}

	void AddImpPuppet(TArray<FVector3>& mesh, const PuppetStep& step)
	{
		// Forward, height, lateral. The shoulders widen above a tapered waist.
		AddHull<6>(mesh, std::array { PuppetRing {{0, 18, 0}, 6.5f}, PuppetRing {{0, 34, 0}, 9.4f},
			PuppetRing {{0, 43, 0}, 7.7f} }, 1.4f);
		AddHull<5>(mesh, std::array { PuppetRing {{2, 39, 0}, 5.0f}, PuppetRing {{2, 48, 0}, 7.1f},
			PuppetRing {{0, 54, 0}, 4.9f} }, 1.07f);

		const float swing = std::cos(step.Phase) * step.Strength;
		const float lift = std::sin(step.Phase) * step.Strength;
		for (const float side : { -1.f, 1.f })
		{
			const float advance = swing * side;
			const float footLift = 2.2f * std::max(0.f, lift * side);
			const float ankle = 0.8f + 2.5f * side + 5.2f * advance;
			const float footSide = 5.5f * side;
			AddHull<5>(mesh, std::array { PuppetRing {{6.2f - 3.8f * advance, 27.f, 15.5f * side}, 3.4f},
				PuppetRing {{-0.8f, 39.f, 10.2f * side}, 5.0f} }, 0.9f);
			AddHull<5>(mesh, std::array { PuppetRing {{ankle, 3.2f + footLift, footSide}, 3.7f},
				PuppetRing {{0.f, 23.f, 4.5f * side}, 4.6f} }, 0.95f);
			AddHull<4>(mesh, std::array { PuppetRing {{ankle + 1.9f, footLift, footSide}, 4.5f},
				PuppetRing {{ankle + 0.8f, 4.8f + footLift, footSide}, 4.f} }, 1.12f, 1.8f);
		}
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

	// Keep only the previous presentation sample for the four selected actors.
	// Both backends see this same state, including across a live mode change.
	static thread_local PuppetWalk previous;
	const auto visualTime = RenderVisualTime::RuntimeClock().Snapshot();
	PuppetWalk current;
	current.Level = &level;
	current.Generation = visualTime.Generation;
	current.Frame = visualTime.MainFrame;
	current.Tic = level.time + std::clamp(view.TicFrac, 0.0, 1.0);
	current.Count = count;
	const float elapsed = float(current.Tic - previous.Tic);
	const bool continuous = previous.Level == current.Level && previous.Generation == current.Generation &&
		previous.Frame + 1 == current.Frame && elapsed >= 0.f && elapsed <= 4.f;
	scene.Triangles.Grow(count * VerticesPerPuppet);
	for (unsigned i = 0; i < count; ++i)
	{
		const auto& caster = casters[i];
		current.Steps[i] = continuous ? UpdateStep(*caster.Actor, caster.Base, previous, elapsed) :
			PuppetStep { caster.Actor->SpawnOrder, caster.Base };
		const unsigned first = scene.Triangles.Size();
		AddImpPuppet(scene.Triangles, current.Steps[i]);
		const auto angles = caster.Actor->InterpolatedAngles(view.TicFrac);
		const float cosine = float(angles.Yaw.Cos()), sine = float(angles.Yaw.Sin());
		for (unsigned j = first; j < scene.Triangles.Size(); ++j)
		{
			auto& vertex = scene.Triangles[j];
			vertex = caster.Base + FVector3(cosine * vertex.X - sine * vertex.Z, vertex.Y,
				sine * vertex.X + cosine * vertex.Z);
		}
	}
	previous = current;
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
