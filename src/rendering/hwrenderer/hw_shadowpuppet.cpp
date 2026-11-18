#include "actorinlines.h"
#include "a_dynlight.h"
#include "bitmap.h"
#include "c_cvars.h"
#include "doom_levelmesh.h"
#include "g_levellocals.h"
#include "hw_cvars.h"
#include "hw_flashlight.h"
#include "hw_shadowpuppet.h"
#include "hwrenderer/scene/hw_drawcontext.h"
#include "hwrenderer/scene/hw_drawinfo.h"
#include "hwrenderer/scene/hw_drawstructs.h"
#include "hwrenderer/scene/hw_visualtime.h"
#include "p_local.h"
#include "r_state.h"
#include "r_visualtime.h"
#include "texturemanager.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <map>
#include <vector>

CVAR(Int, gl_shadow_puppets, 0, CVAR_ARCHIVE | CVAR_GLOBALCONFIG);
CVAR(Int, gl_shadow_puppets_active, 0, 0);
EXTERN_CVAR(Int, gl_spriteclip);

thread_local HWShadowPuppetLightSet HWShadowPuppetFlashlight;

namespace
{
	// Stock Spider Mastermind death frames reach 5,867 merged caps and edges.
	constexpr unsigned MaxMaskPieces = 8192;

	struct PixelRect
	{
		int Left, Top, Right, Bottom;
	};

	struct PixelEdge
	{
		int FromX, FromY, ToX, ToY;
	};

	struct SpriteMask
	{
		int Width = 0, Height = 0, Cutoff = -1;
		std::vector<PixelRect> Rectangles;
		std::vector<PixelEdge> Edges;

		size_t Bytes() const { return Rectangles.capacity() * sizeof(PixelRect) + Edges.capacity() * sizeof(PixelEdge); }
	};

	// Pixel coordinates are patch edges, with +Y down. Caps and contours
	// both wind clockwise in that space. Internal edges between horizontal
	// runs must never extrude, even if the next row has a different length.
	SpriteMask ReadMask(FTexture& texture, int cutoff)
	{
		SpriteMask mask;
		mask.Cutoff = cutoff;
		if (!texture.GetImage() || texture.GetWidth() > 4096 || texture.GetHeight() > 4096)
			return mask;

		const auto bitmap = texture.GetBgraBitmap(nullptr);
		const auto* pixels = bitmap.GetPixels();
		const int w = bitmap.GetWidth(), h = bitmap.GetHeight(), pitch = bitmap.GetPitch();
		if (!pixels || w <= 0 || h <= 0)
			return mask;
		mask.Width = w;
		mask.Height = h;
		const auto solid = [&](int x, int y) {
			return x >= 0 && y >= 0 && x < w && y < h && pixels[y * pitch + x * 4 + 3] >= cutoff;
		};

		// Merge identical runs on adjacent rows. This keeps flat areas cheap
		// to rasterize and retains one-pixel claws, horns and enclosed holes.
		std::vector<size_t> previous, current;
		for (int y = 0; y < h; ++y)
		{
			current.clear();
			size_t last = 0;
			for (int x = 0; x < w;)
			{
				if (!solid(x, y)) { ++x; continue; }
				const int left = x++;
				while (x < w && solid(x, y)) ++x;
				while (last < previous.size() && mask.Rectangles[previous[last]].Left < left) ++last;
				if (last < previous.size() && mask.Rectangles[previous[last]].Left == left &&
					mask.Rectangles[previous[last]].Right == x)
				{
					mask.Rectangles[previous[last]].Bottom = y + 1;
					current.push_back(previous[last]);
				}
				else
				{
					if (mask.Rectangles.size() >= MaxMaskPieces) return SpriteMask{0, 0, cutoff};
					current.push_back(mask.Rectangles.size());
					mask.Rectangles.push_back({left, y, x, y + 1});
				}
			}
			previous.swap(current);
		}

		// A boundary exists only where opacity changes across a texel edge.
		// Merge collinear edges of the same orientation, including hole rims.
		for (bool vertical : {false, true})
		{
			const int lines = vertical ? w : h, length = vertical ? h : w;
			for (int line = 0; line <= lines; ++line)
			{
				const auto direction = [&](int i) {
					return vertical ? int(solid(line - 1, i)) - int(solid(line, i)) :
						int(solid(i, line)) - int(solid(i, line - 1));
				};
				for (int i = 0; i < length;)
				{
					const int sign = direction(i);
					const int begin = i++;
					if (!sign) continue;
					while (i < length && direction(i) == sign) ++i;
					const int from = sign > 0 ? begin : i, to = sign > 0 ? i : begin;
					if (mask.Rectangles.size() + mask.Edges.size() >= MaxMaskPieces)
						return SpriteMask{0, 0, cutoff};
					mask.Edges.push_back(vertical ? PixelEdge{line, from, line, to} : PixelEdge{from, line, to, line});
				}
			}
		}
		return mask;
	}

	const SpriteMask& CachedMask(FTexture& texture, int cutoff)
	{
		static thread_local std::map<FTexture*, SpriteMask> masks;
		static thread_local uint64_t generation = 0;
		static thread_local size_t retainedBytes = 0;
		const auto now = RenderVisualTime::RuntimeClock().Snapshot().Generation;
		// Budget actual contour storage: a room of small animated sprites can
		// reuse far more frames than one with large, intricate replacements.
		if (now != generation || ((retainedBytes >= 16 * 1024 * 1024 || masks.size() >= 2048) && !masks.count(&texture)))
		{
			masks.clear();
			retainedBytes = 0;
			generation = now;
		}
		auto& mask = masks[&texture];
		if (mask.Cutoff != cutoff)
		{
			retainedBytes -= mask.Bytes();
			mask = ReadMask(texture, cutoff);
			retainedBytes += mask.Bytes();
		}
		return mask;
	}

	struct LightSprite
	{
		AActor* Actor = nullptr;
		FGameTexture* Texture = nullptr;
		FVector3 TopLeft, Across, Down; // complete untrimmed source image
	};

	bool IsFlashlightBlocker(const AActor& actor)
	{
		if (actor.player || actor.flags & (MF_MISSILE | MF_SPECIAL) || actor.IsKindOf(NAME_Inventory))
			return false;
		// Use the effective flags after DeHackEd replacements and state actions.
		// A dying actor still blocks while solid. A visible Spectre or Lost Soul
		// contributes its sprite silhouette regardless of its display blend.
		return (actor.flags & MF_SOLID) || (actor.health > 0 && (actor.flags3 & MF3_ISMONSTER));
	}

	bool ResolveLightSprite(HWDrawInfo& di, HWSprite& sprite, const FVector3& light, LightSprite& card)
	{
		auto& actor = *sprite.actor;
		card.Actor = &actor;
		const bool forcedTilt = (actor.renderflags & RF_FORCEXYBILLBOARD) && sprite.RenderSurface.xyBillboard;
		const bool cameraOffset = (actor.renderflags2 & RF2_BILLBOARDFACECAMERA) && sprite.RenderSurface.facesCamera &&
			(sprite.offx != 0 || sprite.offy != 0);
		if ((actor.renderflags & (RF_SPRITETYPEMASK | RF_ROLLSPRITE)) != RF_FACESPRITE ||
			(actor.renderflags2 & RF2_ISOMETRICSPRITES) || forcedTilt || cameraOffset)
		{
			// These modes rotate, translate or deform the artwork out of the
			// upright frame. Use their submitted transform and its matching UVs.
			const float du = sprite.ur - sprite.ul, dv = sprite.vb - sprite.vt;
			const int w = sprite.texture->GetTexture()->GetWidth(), h = sprite.texture->GetTexture()->GetHeight();
			if (!du || !dv || w <= 0 || h <= 0) return false;
			FVector3 quad[4];
			sprite.CalculateVertices(&di, quad, &di.Viewpoint.Pos);
			const int border = sprite.texture->expandSprites() ? 1 : 0;
			const FVector3 dx = (quad[1] - quad[0]) / (du * (w + 2 * border));
			const FVector3 dy = (quad[2] - quad[0]) / (dv * (h + 2 * border));
			card.Texture = sprite.texture;
			card.Across = dx * float(w);
			card.Down = dy * float(h);
			card.TopLeft = quad[0] + dx * (border - sprite.ul * (w + 2 * border)) +
				dy * (border - sprite.vt * (h + 2 * border));
			return true;
		}

		// Billboard axes in the main view are camera-relative. The blocker
		// is observed from the lamp, with its upright axis anchored to gravity.
		const DVector2 toActor(sprite.x - light.X, sprite.y - light.Z);
		const double distance = toActor.Length();
		if (distance < 0.001) return false; // a vertical card is edge-on directly above or below
		const FVector3 right(float(toActor.Y / distance), 0.f, float(-toActor.X / distance));
		auto* texture = sprite.texture;
		bool mirrorX = sprite.RenderSurface.uvMirrorX;
		if (!actor.picnum.isValid())
		{
			bool frameMirror = false;
			const auto angle = actor.GetSpriteAngle(toActor.Angle(), di.Viewpoint.TicFrac);
			const auto patch = sprites[actor.sprite].GetSpriteFrame(actor.frame, -1, angle, &frameMirror,
				!!(actor.renderflags & RF_SPRITEFLIP));
			if (!patch.isValid()) return false;
			texture = TexMan.GetGameTexture(patch, false);
			if (!texture || !texture->isValid() || !texture->GetTexture()) return false;
			mirrorX ^= frameMirror != sprite.RenderSurface.frameMirrored;
		}

		const double fraction = HWVisualInterpolationFraction(di.drawctx->portalState.RenderContext, di.Viewpoint.TicFrac);
		const auto actorScale = actor.InterpolatedScale(fraction);
		auto scale = actorScale;
		if ((actor.renderflags2 & RF2_SQUAREPIXELS) && !(actor.renderflags2 & RF2_STRETCHPIXELS))
		{
			const double stretch = std::sqrt(di.Level->pixelstretch);
			scale.X *= stretch;
			scale.Y /= stretch;
		}
		if (!scale.X || !scale.Y) return false;
		const auto& positioning = texture->GetSpritePositioning(1);
		HWSprite clip{};
		const auto rect = positioning.GetSpriteRect();
		clip.z1 = sprite.z - float(scale.Y * rect.top);
		clip.z2 = clip.z1 - float(scale.Y * rect.height);
		const float spriteHeight = float(actorScale.Y * (clip.z1 - clip.z2));
		// The camera's anamorphic clipping mode (-1) keeps a physical
		// floor anchor for the lamp; its view-dependent warp is display-only.
		if (spriteHeight > 0 && (gl_spriteclip > 0 || gl_spriteclip == -1))
			clip.PerformSpriteClipAdjustment(&actor, actor.InterpolatedPosition(di.Viewpoint.TicFrac).XY(), spriteHeight);
		const float clipOffset = clip.z1 - (sprite.z - float(scale.Y * rect.top));

		// Native placement uses the authored texture origin before GPU border
		// expansion and trimming. Mirroring about that origin keeps the feet
		// registered when adjacent rotations have different sizes or offsets.
		card.Texture = texture;
		const float horizontal = float(scale.X) * (mirrorX ? -1.f : 1.f);
		card.Across = right * (horizontal * texture->GetDisplayWidth());
		card.Down = FVector3(0.f, -float(scale.Y) * texture->GetDisplayHeight(), 0.f);
		card.TopLeft = FVector3(sprite.x, sprite.z + clipOffset + sprite.offy, sprite.y)
			- right * (sprite.offx + horizontal * texture->GetDisplayLeftOffset(r_spriteadjustHW));
		card.TopLeft.Y += float(scale.Y) * texture->GetDisplayTopOffset(r_spriteadjustHW);
		if (sprite.RenderSurface.uvMirrorY)
		{
			// HWSprite swaps V within its trimmed quad, retaining that quad's bounds.
			card.TopLeft.Y = clip.z1 + clip.z2 + 2.f * sprite.offy - card.TopLeft.Y;
			card.Down = -card.Down;
		}
		return true;
	}

	void AddSpriteMask(const LightSprite& card, const FVector3& light, HWShadowPuppetScene& scene, bool stencil)
	{
		const float threshold = std::clamp(float(gl_mask_sprite_threshold), 0.f, 1.f);
		const int cutoff = std::max(1, int(std::ceil(255.f * threshold)));
		const auto& mask = CachedMask(*card.Texture->GetTexture(), cutoff);
		if (mask.Rectangles.empty()) return;
		const FVector3 dx = card.Across / float(mask.Width), dy = card.Down / float(mask.Height);
		const FVector3 origin = card.TopLeft;
		const float facing = (dx ^ dy) | (light - origin);
		if (std::abs(facing) < 1e-8f) return;
		const bool reverse = facing < 0;
		const auto position = [&](int x, int y) { return origin + dx * float(x) + dy * float(y); };

		auto& mesh = scene.Mesh;
		mesh.Triangles.Grow(unsigned(mask.Rectangles.size()) * 6);
		for (const auto& r : mask.Rectangles)
		{
			const auto a = position(r.Left, r.Top), b = position(r.Right, r.Top);
			const auto c = position(r.Right, r.Bottom), d = position(r.Left, r.Bottom);
			mesh.Triangles.Push(a); mesh.Triangles.Push(reverse ? d : b); mesh.Triangles.Push(c);
			mesh.Triangles.Push(a); mesh.Triangles.Push(c); mesh.Triangles.Push(reverse ? b : d);
		}
		if (stencil)
		{
			mesh.Edges.Grow(unsigned(mask.Edges.size()) * 2);
			for (const auto& edge : mask.Edges)
			{
				const auto from = position(edge.FromX, edge.FromY), to = position(edge.ToX, edge.ToY);
				mesh.Edges.Push(reverse ? to : from);
				mesh.Edges.Push(reverse ? from : to);
			}
			// Each closed card contributes at most one to the final winding
			// count per sample. Resolve before an 8-bit count can wrap to zero.
			if (scene.Casters.size() % 255 == 0) mesh.StencilBatches.Push(HWShadowPuppetMesh::BatchEnd{});
			mesh.StencilBatches.Last() = { mesh.Triangles.Size(), mesh.Edges.Size() };
		}
		scene.Casters.insert(card.Actor);
	}

	FVector3 RenderPosition(const DVector3& point)
	{
		return { float(point.X), float(point.Z), float(point.Y) };
	}

	struct FlashlightCone
	{
		FVector3 Direction;
		float Radius, Sin, Cos;

		bool Reaches(const FVector3& relative, float distance, float extent) const
		{
			const float axial = relative | Direction;
			const float radial = (relative - Direction * axial).Length();
			return distance <= Radius + extent && axial >= -extent && radial * Cos - axial * Sin <= extent;
		}
	};
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

bool BuildShadowPuppetScene(HWDrawInfo& di, HWShadowPuppetScene& scene, bool sprites, bool stencil, bool mapGeometry)
{
	const auto& view = di.Viewpoint;
	if (!view.camera || !view.sector || !view.camera->player || view.camera != view.camera->player->mo)
		return false;
	auto& level = *view.camera->Level;
	// A sprite from another portal group does not belong in the root geometry pass.
	if (view.sector->PortalGroup != 0 || level.linePortals.Size() != 0)
		return false;
	// The add-on models a noncircular beam with several cones. All rays
	// originate at the same point, so all lobes share one visibility pass.
	auto& lights = scene.Flashlight;
	std::array<FlashlightCone, HWShadowPuppetLightSet::MaxBeams> cones;
	FVector3 forward(0, 0, 0);
	float radius = 0.f;
	for (auto* candidate = level.lights; candidate; candidate = candidate->next)
	{
		if (!candidate->IsActive() || !candidate->IsLocalFlashlight() || candidate->target->master != view.camera)
			continue;
		if (!candidate->Sector || candidate->Sector->PortalGroup != 0 || candidate->GetRadius() <= 0.f ||
			lights.Count == lights.MaxBeams || (lights.Count && HWLightPosition(candidate) != HWLightPosition(lights.Beams[0])))
			return false;
		const DAngle outer = *candidate->pSpotOuterAngle;
		const FVector3 direction = RenderPosition(HWSpotDirection(candidate));
		cones[lights.Count] = { direction, candidate->GetRadius(), float(outer.Sin()), float(outer.Cos()) };
		lights.Beams[lights.Count++] = candidate;
		forward += direction;
		radius = std::max(radius, candidate->GetRadius());
	}
	if (!lights.Count) return false;
	for (auto& sector : level.sectors)
	{
		if (sector.PortalIsLinked(sector_t::floor) || sector.PortalIsLinked(sector_t::ceiling))
			return false;
		if (sector.e->XFloor.ffloors.Size() != 0)
			sprites = false;
	}
	const auto* beam = lights.Beams[0];
	double halfAngle = beam->pSpotOuterAngle->Degrees();
	if (lights.Count > 1)
	{
		if (forward.LengthSquared() < 1e-6f) return false;
		forward.MakeUnit();
		for (unsigned i = 0; i < lights.Count; ++i)
		{
			const auto& axis = cones[i].Direction;
			const double angle = VecToAngle(forward | axis, (forward ^ axis).Length()).Degrees();
			halfAngle = std::max(halfAngle, angle + lights.Beams[i]->pSpotOuterAngle->Degrees());
		}
	}
	// One perspective depth image requires every covered ray to face forward.
	if (!(halfAngle > 0.0 && halfAngle < 90.0))
		return false;

	const FVector3 origin = RenderPosition(HWLightPosition(beam));
	const FVector3 aim = origin + forward;
	const FVector3 up = std::abs(forward.Y) < 0.98f ? FVector3(0, 1, 0) : FVector3(0, 0, 1);
	VSMatrix lightView = VSMatrix::identity(), projection = VSMatrix::identity();
	lightView.lookAt(origin.X, origin.Y, origin.Z, aim.X, aim.Y, aim.Z, up.X, up.Y, up.Z);
	projection.perspective(float(2.0 * halfAngle), 1.f, 1.f, radius + 32.f);
	scene.LightProjection = ShadowPuppetVulkanProjection(projection, lightView);
	scene.Origin = origin;
	if (mapGeometry && level.levelMesh)
		level.levelMesh->CollectFlashlightCasters(scene.LightProjection, *beam->Sector, scene.Mesh.MapTriangles);
	if (!sprites)
		return scene.Mesh.MapTriangles.Size() != 0;

	const auto* presented = HWPresentedFlashlight(beam);
	// The submitted sprite is authoritative. A cosmetic floor shadow has
	// index -1. Opaque wall sprites share the models list with actual models.
	for (auto list : {GLDL_TRANSLUCENT, GLDL_MODELS})
	{
		for (auto* sprite : di.drawlists[list].sprites)
		{
			auto* actor = sprite->actor;
			if (!actor || sprite->index == -1 || !IsFlashlightBlocker(*actor) ||
				sprite->modelframe || !sprite->texture || !sprite->texture->GetTexture() ||
				sprite->RenderSurface.throughPortalMode || !actor->Sector || actor->Sector->PortalGroup != 0 ||
				scene.Casters.count(actor))
				continue;
			LightSprite card;
			if (!ResolveLightSprite(di, *sprite, origin, card)) continue;
			const FVector3 span = card.Across + card.Down;
			const float extent = span.Length() * 0.5f;
			const FVector3 relative = card.TopLeft + span * 0.5f - origin;
			const float distance = relative.Length();
			if (std::none_of(cones.begin(), cones.begin() + lights.Count,
				[&](const FlashlightCone& cone) { return cone.Reaches(relative, distance, extent); }))
				continue;
			const bool visible = presented
				? P_CheckSightFromRenderPoint(presented->Position, actor, {sprite->x, sprite->y, sprite->z})
				: P_CheckSight(beam->target.Get(), actor, SF_IGNOREVISIBILITY);
			if (!visible) continue;
			AddSpriteMask(card, origin, scene, stencil);
		}
	}
	return scene.Mesh.Triangles.Size() != 0 || scene.Mesh.MapTriangles.Size() != 0;
}
