
struct TraceResult
{
	float t;
	vec3 primitiveWeights;
	int primitiveIndex;
};

vec2 GetSurfaceUV(int primitiveIndex, vec3 primitiveWeights);

bool FlashlightMaskHit(int primitiveIndex, uint surfaceIndex, vec2 bc)
{
	vec2 uv = GetSurfaceUV(primitiveIndex, vec3(bc, 1.0 - bc.x - bc.y));
	int image = surfaces[surfaceIndex].MaskedTextureIndex;
	if (image < 0)
	{
		if (uv.y < 0.0 || uv.y > 1.0) return false;
		image = ~image;
	}
	return textureLod(textures[nonuniformEXT(image)], uv, 0.0).a > surfaces[surfaceIndex].MaskThreshold;
}

// One centre and twelve equal-weight disk strata. Both reflection axes are
// exact, and the offsets along either axis cover seven different depths of edge.
const vec2 mapDisk[13] = vec2[13](
	vec2(0), vec2(0.2,0.2), vec2(-0.2,-0.2), vec2(0.2,-0.2), vec2(-0.2,0.2),
	vec2(0.84,0.44), vec2(-0.84,-0.44), vec2(0.84,-0.44), vec2(-0.84,0.44),
	vec2(0.44,0.84), vec2(-0.44,-0.84), vec2(0.44,-0.84), vec2(-0.44,0.84));
const int mapDiskMask = (1 << 13) - 1;

// Rotate the four spokes off the lens axes so a straight corridor wall
// sweeps across their lengths even when only one spread axis is enabled.
const vec4 mapCrossX = vec4(.923880, -.382683, -.923880, .382683);
const vec4 mapCrossY = vec4(.382683, .923880, -.382683, -.923880);

#if defined(USE_RAYQUERY) || defined(SUPPORTS_RAYQUERY)

TraceResult TraceFirstHit(vec3 origin, float tmin, vec3 dir, float tmax)
{
	TraceResult result;

	rayQueryEXT rayQuery;
	rayQueryInitializeEXT(rayQuery, acc, gl_RayFlagsCullBackFacingTrianglesEXT, 0xFF, origin, tmin, dir, tmax);

	while(rayQueryProceedEXT(rayQuery))
	{
		if (rayQueryGetIntersectionTypeEXT(rayQuery, false) == gl_RayQueryCommittedIntersectionTriangleEXT)
		{
			rayQueryConfirmIntersectionEXT(rayQuery);
		}
	}

	if (rayQueryGetIntersectionTypeEXT(rayQuery, true) == gl_RayQueryCommittedIntersectionTriangleEXT)
	{
		result.t = rayQueryGetIntersectionTEXT(rayQuery, true);

		result.primitiveWeights.xy = rayQueryGetIntersectionBarycentricsEXT(rayQuery, true);
		result.primitiveWeights.z = 1.0 - result.primitiveWeights.x - result.primitiveWeights.y;

		result.primitiveIndex =
			rayQueryGetIntersectionInstanceCustomIndexEXT(rayQuery, true) +
			rayQueryGetIntersectionPrimitiveIndexEXT(rayQuery, true);
	}
	else
	{
		result.t = tmax;
		result.primitiveIndex = -1;
	}

	return result;
}

TraceResult TraceFirstHitReverse(vec3 origin, float tmin, vec3 dir, float tmax)
{
	TraceResult result;

	rayQueryEXT rayQuery;
	rayQueryInitializeEXT(rayQuery, acc, gl_RayFlagsCullFrontFacingTrianglesEXT, 0xFF, origin, tmin, dir, tmax);

	while(rayQueryProceedEXT(rayQuery))
	{
		if (rayQueryGetIntersectionTypeEXT(rayQuery, false) == gl_RayQueryCommittedIntersectionTriangleEXT)
		{
			rayQueryConfirmIntersectionEXT(rayQuery);
		}
	}

	if (rayQueryGetIntersectionTypeEXT(rayQuery, true) == gl_RayQueryCommittedIntersectionTriangleEXT)
	{
		result.t = rayQueryGetIntersectionTEXT(rayQuery, true);

		result.primitiveWeights.xy = rayQueryGetIntersectionBarycentricsEXT(rayQuery, true);
		result.primitiveWeights.z = 1.0 - result.primitiveWeights.x - result.primitiveWeights.y;

		result.primitiveIndex =
			rayQueryGetIntersectionInstanceCustomIndexEXT(rayQuery, true) +
			rayQueryGetIntersectionPrimitiveIndexEXT(rayQuery, true);
	}
	else
	{
		result.t = tmax;
		result.primitiveIndex = -1;
	}

	return result;
}

bool TraceAnyHit(vec3 origin, float tmin, vec3 dir, float tmax)
{
	rayQueryEXT rayQuery;
	rayQueryInitializeEXT(rayQuery, acc, gl_RayFlagsTerminateOnFirstHitEXT | gl_RayFlagsCullBackFacingTrianglesEXT, 0xFF, origin, tmin, dir, tmax);
	while(rayQueryProceedEXT(rayQuery)) { }
	return rayQueryGetIntersectionTypeEXT(rayQuery, true) != gl_RayQueryCommittedIntersectionNoneEXT;
}

bool TraceMapHit(vec3 origin, vec3 dir, float distance, int group, bool includeMasked)
{
	rayQueryEXT query;
	// Force candidate reporting even for BLASes built with the opaque flag.
	// The mesh contains portals and translucent or masked surfaces too.
	rayQueryInitializeEXT(query, acc, gl_RayFlagsNoOpaqueEXT | gl_RayFlagsTerminateOnFirstHitEXT,
		0xFF, origin, 0.0, dir, distance);
	while (rayQueryProceedEXT(query))
	{
		if (rayQueryGetIntersectionTypeEXT(query, false) == gl_RayQueryCandidateIntersectionTriangleEXT)
		{
			int primitive = rayQueryGetIntersectionInstanceCustomIndexEXT(query, false) +
				rayQueryGetIntersectionPrimitiveIndexEXT(query, false);
			uint surface = surfaceIndices[primitive];
			int caster = surfaces[surface].MapShadowGroup;
			if (caster == group || (includeMasked && caster == -group &&
				FlashlightMaskHit(primitive, surface, rayQueryGetIntersectionBarycentricsEXT(query, false))))
				rayQueryConfirmIntersectionEXT(query);
		}
	}
	return rayQueryGetIntersectionTypeEXT(query, true) != gl_RayQueryCommittedIntersectionNoneEXT;
}

int TraceMapDisk(vec3 receiver, vec3 lamp, vec3 right, vec3 up, int group, int activeMask)
{
	int blocked = 0;
	for (int i = 0; i < 13; ++i)
	{
		if ((activeMask & (1 << i)) == 0) continue;
		vec3 ray = lamp + mapDisk[i].x * right + mapDisk[i].y * up - receiver;
		// A unit segment parameter lets every sample terminate at its own endpoint.
		if (TraceMapHit(receiver, ray, 1.0, group, true)) blocked |= 1 << i;
	}
	return blocked;
}

// Twelve equal-angle slices integrate the source in polar coordinates. The
// second ring bounds each slice at the rim; the first ring can move along it.
const vec2 mapSpokes[12] = vec2[12](
	vec2(.965926, .258819), vec2(.707107, .707107), vec2(.258819, .965926),
	vec2(-.258819, .965926), vec2(-.707107, .707107), vec2(-.965926, .258819),
	vec2(-.965926, -.258819), vec2(-.707107, -.707107), vec2(-.258819, -.965926),
	vec2(.258819, -.965926), vec2(.707107, -.707107), vec2(.965926, -.258819));

bool MapRadialSample(vec3 receiver, vec3 lamp, vec3 offset, float fraction, int group, bool centerHit)
{
	vec3 ray = (lamp + offset - receiver) * fraction;
	bool hit = TraceMapHit(receiver, ray, 1.0, group, true);
	if (hit != centerHit && TraceMapHit(lamp, offset, 1.0, group, true)) return centerHit;
	return hit;
}

float CrossMapVisibility(vec3 receiver, vec3 lamp, vec3 right, vec3 up, float fraction, int group)
{
	int accessible = 0, lit = 0;
	for (int lane = 0; lane < 4; ++lane)
	{
		vec3 spoke = right * mapCrossX[lane] + up * mapCrossY[lane];
		for (int bin = 0; bin < 4; ++bin)
		{
			vec3 offset = spoke * sqrt((float(bin) + 0.5) / 4.0);
			if (TraceMapHit(lamp, offset, 1.0, group, true)) continue;
			++accessible;
			if (!TraceMapHit(receiver, (lamp + offset - receiver) * fraction, 1.0, group, true)) ++lit;
		}
	}
	return accessible > 0 ? float(lit) / float(accessible) :
		(TraceMapHit(receiver, (lamp - receiver) * fraction, 1.0, group, true) ? 0.0 : 1.0);
}

float AreaMapVisibility(vec3 receiver, vec3 lamp, vec3 right, vec3 up, float fraction, int group, bool crossOnly)
{
	if (crossOnly) return CrossMapVisibility(receiver, lamp, right, up, fraction, group);
	// Hardware ray queries sample the middle and rim of each polar slice.
	// Refine only intervals in which visibility changes.
	bool centerHit = TraceMapHit(receiver, (lamp - receiver) * fraction, 1.0, group, true);
	float area = 0.0;
	for (int spoke = 0; spoke < 12; ++spoke)
	{
		vec3 offset = right * mapSpokes[spoke].x + up * mapSpokes[spoke].y;
		bool inner = centerHit;
		for (int section = 0; section < 2; ++section)
		{
			float a = 0.5 * float(section), b = a + 0.5;
			bool outer = MapRadialSample(receiver, lamp, offset * b, fraction, group, centerHit);
			if (outer == inner)
				area += inner ? b * b - a * a : 0.0;
			else
			{
				float lo = a, hi = b;
				for (int i = 0; i < 5; ++i)
				{
					float mid = (lo + hi) * 0.5;
					if (MapRadialSample(receiver, lamp, offset * mid, fraction, group, centerHit) == inner)
						lo = mid;
					else
						hi = mid;
				}
				float boundary = (lo + hi) * 0.5;
				area += inner ? boundary * boundary - a * a : b * b - boundary * boundary;
			}
			inner = outer;
		}
	}
	return clamp(1.0 - area / 12.0, 0.0, 1.0);
}

#else

struct RayBBox
{
	vec3 start, end;
	vec3 c, w, v;
};

RayBBox create_ray(vec3 ray_start, vec3 ray_end)
{
	RayBBox ray;
	ray.start = ray_start;
	ray.end = ray_end;
	ray.c = (ray_start + ray_end) * 0.5;
	ray.w = ray_end - ray.c;
	ray.v = abs(ray.w);
	return ray;
}

bool overlap_bv_ray(RayBBox ray, int a)
{
	vec3 v = ray.v;
	vec3 w = ray.w;
	vec3 h = nodes[a].extents;
	vec3 c = ray.c - nodes[a].center;

	if (abs(c.x) > v.x + h.x ||
		abs(c.y) > v.y + h.y ||
		abs(c.z) > v.z + h.z)
	{
		return false;
	}

	if (abs(c.y * w.z - c.z * w.y) > h.y * v.z + h.z * v.y ||
		abs(c.x * w.z - c.z * w.x) > h.x * v.z + h.z * v.x ||
		abs(c.x * w.y - c.y * w.x) > h.x * v.y + h.y * v.x)
	{
		return false;
	}

	return true;
}

#define FLT_EPSILON 1.192092896e-07F // smallest such that 1.0+FLT_EPSILON != 1.0

float intersect_triangle_ray(RayBBox ray, int a, out float barycentricB, out float barycentricC)
{
	int start_element = nodes[a].element_index;

	vec3 p[3];
	p[0] = vertices[elements[start_element]].pos.xyz;
	p[1] = vertices[elements[start_element + 1]].pos.xyz;
	p[2] = vertices[elements[start_element + 2]].pos.xyz;

	// Moeller-Trumbore ray-triangle intersection algorithm:

	vec3 D = ray.end - ray.start;

	// Find vectors for two edges sharing p[0]
	vec3 e1 = p[1] - p[0];
	vec3 e2 = p[2] - p[0];

	// Begin calculating determinant - also used to calculate u parameter
	vec3 P = cross(D, e2);
	float det = dot(e1, P);

	// Backface check
	if (det < 0.0f)
		return 1.0f;

	// If determinant is near zero, ray lies in plane of triangle
	if (det > -FLT_EPSILON && det < FLT_EPSILON)
		return 1.0f;

	float inv_det = 1.0f / det;

	// Calculate distance from p[0] to ray origin
	vec3 T = ray.start - p[0];

	// Calculate u parameter and test bound
	float u = dot(T, P) * inv_det;

	// Check if the intersection lies outside of the triangle
	if (u < 0.f || u > 1.f)
		return 1.0f;

	// Prepare to test v parameter
	vec3 Q = cross(T, e1);

	// Calculate V parameter and test bound
	float v = dot(D, Q) * inv_det;

	// The intersection lies outside of the triangle
	if (v < 0.f || u + v  > 1.f)
		return 1.0f;

	float t = dot(e2, Q) * inv_det;
	if (t <= FLT_EPSILON)
		return 1.0f;

	// Return hit location on triangle in barycentric coordinates
	barycentricB = u;
	barycentricC = v;
	return t;
}

bool is_leaf(int node_index)
{
	return nodes[node_index].element_index != -1;
}

bool TraceAnyHit(vec3 origin, float tmin, vec3 dir, float tmax)
{
	if (tmax <= 0.0f || nodesRoot == -1)
		return false;

	RayBBox ray = create_ray(origin, origin + dir * tmax);
	tmin /= tmax;

	int stack[64];
	int stackIndex = 0;
	stack[stackIndex++] = nodesRoot;
	do
	{
		int a = stack[--stackIndex];
		if (overlap_bv_ray(ray, a))
		{
			if (is_leaf(a))
			{
				float baryB, baryC;
				float t = intersect_triangle_ray(ray, a, baryB, baryC);
				if (t >= tmin && t < 1.0)
				{
					return true;
				}
			}
			else
			{
				stack[stackIndex++] = nodes[a].right;
				stack[stackIndex++] = nodes[a].left;
			}
		}
	} while (stackIndex > 0);
	return false;
}

float MapNodeEntry(int node, vec3 origin, vec3 invRay, vec3 absInvRay, bvec3 parallel, vec3 expand)
{
	vec3 offset = nodes[node].center - origin;
	vec3 extents = nodes[node].extents + expand;
	vec3 center = offset * invRay, reach = extents * absInvRay;
	vec3 lo = center - reach, hi = center + reach;
	if (any(parallel))
	{
		// A ray lying on a slab boundary stays inside that slab throughout.
		lo = mix(lo, vec3(0.0), parallel);
		hi = mix(hi, mix(vec3(-1.0), vec3(1.0), lessThanEqual(abs(offset), extents)), parallel);
	}
	float enter = max(max(lo.x, lo.y), max(lo.z, 0.0));
	float leave = min(min(hi.x, hi.y), min(hi.z, 1.0));
	return enter <= leave ? enter : 2.0;
}

bool MapTriangleHit(int element, vec3 origin, vec3 ray, out vec3 scaledWeights)
{
	vec3 a = vertices[elements[element]].pos;
	vec3 ab = vertices[elements[element + 1]].pos - a;
	vec3 ac = vertices[elements[element + 2]].pos - a;
	vec3 p = cross(ray, ac), t = origin - a;
	vec3 q = cross(t, ab);
	float det = dot(ab, p);
	float side = sign(det);
	float u = dot(t, p) * side, v = dot(ray, q) * side;
	float distance = dot(ac, q) * side;
	float scale = abs(det);
	scaledWeights = vec3(u, v, scale);
	return scale >= FLT_EPSILON && min(u, v) >= 0.0 && u + v <= scale &&
		distance > FLT_EPSILON * scale && distance < scale;
}

// Barycentric edge and depth tests are affine in the ray endpoint for a fixed
// receiver. Evaluate their gradients once per triangle for the whole aperture.
vec4 MapDiskEdges(vec3 direction, vec3 uNormal, vec3 vNormal, vec3 triNormal)
{
	float u = dot(direction, uNormal), v = dot(direction, vNormal), det = dot(direction, triNormal);
	return vec4(u, v, det - u - v, det);
}

int MapDiskTriangle(int element, vec3 receiver, vec3 toLamp, vec3 right, vec3 up, int group, int blocked)
{
	vec3 a = vertices[elements[element]].pos;
	vec3 ab = vertices[elements[element + 1]].pos - a;
	vec3 ac = vertices[elements[element + 2]].pos - a;
	vec3 t = receiver - a;
	vec3 vNormal = cross(t, ab);
	float depth = dot(ac, vNormal);
	if (depth == 0.0) return blocked;
	float side = sign(depth);
	vec3 uNormal = cross(ac, t) * side;
	vec3 normal = cross(ac, ab) * side;
	vNormal *= side;
	vec4 center = MapDiskEdges(toLamp, uNormal, vNormal, normal);
	center.w -= abs(depth); // segment must reach the triangle before the lamp
	vec4 dx = MapDiskEdges(right, uNormal, vNormal, normal);
	vec4 dy = MapDiskEdges(up, uNormal, vNormal, normal);
	vec4 reach = abs(dx) + abs(dy);
	if (any(lessThan(center + reach, vec4(0.0)))) return blocked;

	int primitive = element / 3;
	uint surface = surfaceIndices[primitive];
	int caster = surfaces[surface].MapShadowGroup;
	if (caster != group && caster != -group) return blocked;
	if (caster == group && all(greaterThan(center - reach, vec4(0.0)))) return mapDiskMask;
	for (int i = 0; i < 13; ++i)
	{
		int bit = 1 << i;
		vec4 e = center + dx * mapDisk[i].x + dy * mapDisk[i].y;
		if ((blocked & bit) == 0 && e.w > 0.0 && all(greaterThanEqual(e.xyz, vec3(0.0))) &&
			(caster == group || FlashlightMaskHit(primitive, surface, e.xy / (e.x + e.y + e.z))))
			blocked |= bit;
	}
	return blocked;
}

// Each spoke carries 32 equal-area bins (uniform steps in radius squared).
// Projecting a triangle from the receiver gives four affine half-planes on
// the source: three triangle edges and the finite end of the ray segment.
// Clip the whole radial interval once, then union it with previous triangles.
const vec4 mapSpokeX[3] = vec4[3](vec4(.965926,.707107,.258819,-.258819),
	vec4(-.707107,-.965926,-.965926,-.707107), vec4(-.258819,.258819,.707107,.965926));
const vec4 mapSpokeY[3] = vec4[3](vec4(.258819,.707107,.965926,.965926),
	vec4(.707107,.258819,-.258819,-.707107), vec4(-.965926,-.965926,-.707107,-.258819));

bool MapAreaTriangle(int element, vec3 receiver, vec3 toLamp, vec3 right, vec3 up, int group,
	bool crossOnly, inout uvec4 covered[3], inout bool centerHit)
{
	int primitive = element / 3;
	uint surface = surfaceIndices[primitive];
	int caster = surfaces[surface].MapShadowGroup;
	if (caster != group && caster != -group) return false;
	vec3 a = vertices[elements[element]].pos;
	vec3 ab = vertices[elements[element + 1]].pos - a;
	vec3 ac = vertices[elements[element + 2]].pos - a;
	vec3 t = receiver - a;
	vec3 vNormal = cross(t, ab);
	float depth = dot(ac, vNormal);
	if (depth == 0.0) return false;
	float side = sign(depth);
	vec3 uNormal = cross(ac, t) * side, normal = cross(ac, ab) * side;
	vNormal *= side;
	vec4 center = MapDiskEdges(toLamp, uNormal, vNormal, normal);
	center.w -= abs(depth) * (1.0 + FLT_EPSILON);
	vec4 dx = MapDiskEdges(right, uNormal, vNormal, normal);
	vec4 dy = MapDiskEdges(up, uNormal, vNormal, normal);
	vec4 reach = abs(dx) + abs(dy);
	if (center.w + reach.w <= 0.0 || any(lessThan(center.xyz + reach.xyz, vec3(0.0)))) return false;
	if (caster == group && all(greaterThan(center - reach, vec4(0.0))))
	{
		centerHit = true;
		return true;
	}
	if (!centerHit && center.w > 0.0 && all(greaterThanEqual(center.xyz, vec3(0.0))))
		centerHit = caster == group || FlashlightMaskHit(primitive, surface, center.xy / (center.x + center.y + center.z));

	for (int row = 0; row < (crossOnly ? 1 : 3); ++row)
	{
		vec4 spokeX = crossOnly ? mapCrossX : mapSpokeX[row];
		vec4 spokeY = crossOnly ? mapCrossY : mapSpokeY[row];
		vec4 lo = vec4(0.0), hi = vec4(1.0);
		for (int plane = 0; plane < 4; ++plane)
		{
			if (center[plane] >= reach[plane]) continue;
			vec4 slope = dx[plane] * spokeX + dy[plane] * spokeY;
			if (center[plane] < 0.0)
				lo = max(lo, -center[plane] / max(slope, vec4(1e-30)));
			else
				hi = min(hi, mix(vec4(1.0), center[plane] / max(-slope, vec4(1e-30)), lessThan(slope, vec4(0.0))));
		}
		// The bin centres represent area, so OR also handles overlapping
		// faces, internal triangulation edges and disjoint blockers.
		ivec4 first = ivec4(ceil(min(lo, vec4(1.0)) * min(lo, vec4(1.0)) * 32.0 - .5));
		ivec4 last = ivec4(floor(hi * hi * 32.0 - .5));
		uvec4 bits = (uvec4(~0u) << clamp(first, 0, 31)) & (uvec4(~0u) >> clamp(31 - last, 0, 31));
		bits = mix(uvec4(0), bits, lessThanEqual(first, last));
		if (caster == group)
			covered[row] |= bits;
		else for (int lane = 0; lane < 4; ++lane)
		{
			uint pending = bits[lane] & ~covered[row][lane];
			vec4 slope = dx * spokeX[lane] + dy * spokeY[lane];
			while (pending != 0u)
			{
				int bin = findLSB(pending);
				float radius = sqrt((float(bin) + 0.5) / 32.0);
				vec3 e = center.xyz + slope.xyz * radius;
				if (FlashlightMaskHit(primitive, surface, e.xy / (e.x + e.y + e.z))) covered[row][lane] |= 1u << bin;
				pending &= pending - 1u;
			}
		}
	}
	return false;
}

int TraceMapRays(vec3 origin, vec3 ray, int group, bool includeMasked, bool disk, vec3 diskRight, vec3 diskUp, int activeMask,
	int areaStyle, inout uvec4 covered[3], inout bool centerHit)
{
	if (nodesRoot < 0) return 0;
	// All rays for a light start at the same end of the segment. Neighbouring
	// fragments encounter the same near nodes and register stack entries.
	vec3 expand = abs(diskRight) + abs(diskUp);
	bvec3 parallel = equal(ray, vec3(0.0));
	vec3 invRay = 1.0 / mix(ray, vec3(1.0), parallel);
	vec3 absInvRay = abs(invRay);
	int node = nodesRoot;
	ivec4 front = ivec4(0);
	int spill[64], depth = 0;
	int blocked = mapDiskMask ^ activeMask;
	while (true)
	{
		int element = nodes[node].element_index;
		if (element >= 0)
		{
			vec3 weights;
			if (areaStyle != 0)
			{
				if (MapAreaTriangle(element, origin + ray, -ray, diskRight, diskUp, group, areaStyle == 3, covered, centerHit))
				{
					for (int i = 0; i < 3; ++i) covered[i] = uvec4(~0u);
					return 0;
				}
			}
			else if (disk)
			{
				blocked = MapDiskTriangle(element, origin + ray, -ray, diskRight, diskUp, group, blocked);
				if (blocked == mapDiskMask) return activeMask;
			}
			else if (MapTriangleHit(element, origin, ray, weights))
			{
				int primitive = element / 3;
				uint surface = surfaceIndices[primitive];
				int caster = surfaces[surface].MapShadowGroup;
				if (caster == group || (includeMasked && caster == -group &&
					FlashlightMaskHit(primitive, surface, weights.xy / weights.z)))
					return 1;
			}
		}
		else
		{
			int left = nodes[node].left, right = nodes[node].right;
			float a = MapNodeEntry(left, origin, invRay, absInvRay, parallel, expand);
			float b = MapNodeEntry(right, origin, invRay, absInvRay, parallel, expand);
			if (min(a, b) <= 1.0)
			{
				node = a <= b ? left : right;
				if (max(a, b) <= 1.0)
				{
					if (depth >= 4) spill[depth - 4] = front.w;
					front = ivec4(a <= b ? right : left, front.xyz);
					++depth;
				}
				continue;
			}
		}
		if (depth == 0) break;
		node = front.x;
		front.xyz = front.yzw;
		if (--depth >= 4) front.w = spill[depth - 4];
	}
	return blocked & activeMask;
}

bool TraceMapHit(vec3 origin, vec3 dir, float distance, int group, bool includeMasked)
{
	vec3 ray = dir * distance;
	uvec4 unused[3];
	bool center = false;
	return distance > 0.0 && TraceMapRays(origin + ray, -ray, group, includeMasked, false, vec3(0), vec3(0), 1, 0, unused, center) != 0;
}

int TraceMapDisk(vec3 receiver, vec3 lamp, vec3 right, vec3 up, int group, int activeMask)
{
	uvec4 unused[3];
	bool center = false;
	return TraceMapRays(lamp, receiver - lamp, group, true, true, right, up, activeMask, 0, unused, center);
}

float AreaMapVisibility(vec3 receiver, vec3 lamp, vec3 right, vec3 up, float fraction, int group, bool crossOnly)
{
	uvec4 covered[3] = uvec4[3](uvec4(0), uvec4(0), uvec4(0));
	vec3 origin = receiver + (lamp - receiver) * fraction;
	bool centerHit = false, foldToDark = false;
	uvec4 crossLit = uvec4(0);
	for (int pass = 0; pass < 2; ++pass)
	{
		TraceMapRays(origin, receiver - origin, group, true, true, right * fraction, up * fraction, 0,
			crossOnly ? 3 : 2, covered, centerHit);
		if (pass == 0)
		{
			foldToDark = centerHit;
			if (crossOnly)
			{
				crossLit = ~covered[0];
				if (all(equal(crossLit, uvec4(0)))) return 0.0;
				if (all(equal(crossLit, uvec4(~0u)))) return 1.0;
				covered[0] = uvec4(0);
			}
			else
			{
				// Only samples opposite the centre can change on the fold pass.
				for (int i = 0; i < 3; ++i)
					if (!foldToDark) covered[i] = ~covered[i];
				if (all(equal(covered[0] & covered[1] & covered[2], uvec4(~0u)))) return foldToDark ? 0.0 : 1.0;
			}
			origin = receiver = lamp;
			fraction = 1.0;
		}
	}
	if (crossOnly)
	{
		// Exclude lens area on the far side of a nearby wall. Folding those
		// samples to the centre would switch them all at once at a silhouette.
		uvec4 accessible = ~covered[0];
		ivec4 total = bitCount(accessible), visible = bitCount(crossLit & accessible);
		int count = total.x + total.y + total.z + total.w;
		return count > 0 ? float(visible.x + visible.y + visible.z + visible.w) / float(count) :
			(foldToDark ? 0.0 : 1.0);
	}
	ivec4 counts = bitCount(covered[0]) + bitCount(covered[1]) + bitCount(covered[2]);
	float area = float(counts.x + counts.y + counts.z + counts.w) / 384.0;
	return foldToDark ? 1.0 - area : area;
}

struct TraceHit
{
	float fraction;
	int triangle;
	float b;
	float c;
};

TraceHit find_first_hit(RayBBox ray)
{
	TraceHit hit;
	hit.fraction = 1.0;
	hit.triangle = -1;
	hit.b = 0.0;
	hit.c = 0.0;
	if (nodesRoot == -1)
		return hit;

	int stack[64];
	int stackIndex = 0;
	stack[stackIndex++] = nodesRoot;
	do
	{
		int a = stack[--stackIndex];
		if (overlap_bv_ray(ray, a))
		{
			if (is_leaf(a))
			{
				float baryB, baryC;
				float t = intersect_triangle_ray(ray, a, baryB, baryC);
				if (t < hit.fraction)
				{
					hit.fraction = t;
					hit.triangle = nodes[a].element_index / 3;
					hit.b = baryB;
					hit.c = baryC;
				}
			}
			else
			{
				stack[stackIndex++] = nodes[a].right;
				stack[stackIndex++] = nodes[a].left;
			}
		}
	} while (stackIndex > 0);
	return hit;
}

TraceResult TraceFirstHit(vec3 origin, float tmin, vec3 dir, float tmax)
{
	TraceResult result;

	// Perform segmented tracing to keep the ray AABB box smaller
	vec3 ray_start = origin;
	vec3 ray_end = origin + dir * tmax;
	vec3 ray_dir = dir;
	float tracedist = tmax;
	float segmentlen = max(200.0, tracedist / 20.0);
	for (float t = 0.0; t < tracedist; t += segmentlen)
	{
		float segstart = t;
		float segend = min(t + segmentlen, tracedist);

		RayBBox ray = create_ray(ray_start + ray_dir * segstart, ray_start + ray_dir * segend);
		TraceHit hit = find_first_hit(ray);
		if (hit.fraction < 1.0)
		{
			result.t = mix(segstart, segend, hit.fraction);
			result.primitiveWeights.x = hit.b;
			result.primitiveWeights.y = hit.c;
			result.primitiveWeights.z = 1.0 - hit.b - hit.c;
			result.primitiveIndex = hit.triangle;
			return result;
		}
	}

	result.t = tracedist;
	result.primitiveIndex = -1;
	return result;
}

//no nice tracing for you sorry
#define TraceFirstHitReverse TraceFirstHit

#endif
