
struct TraceResult
{
	float t;
	vec3 primitiveWeights;
	int primitiveIndex;
};

bool IsOpaqueMapCaster(int primitiveIndex, int group)
{
	return surfaces[surfaceIndices[primitiveIndex]].MapShadowGroup == group;
}

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

bool TraceOpaqueMapHit(vec3 origin, vec3 dir, float distance, int group)
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
			if (IsOpaqueMapCaster(primitive, group))
				rayQueryConfirmIntersectionEXT(query);
		}
	}
	return rayQueryGetIntersectionTypeEXT(query, true) != gl_RayQueryCommittedIntersectionNoneEXT;
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

float MapNodeEntry(int node, vec3 origin, vec3 invRay, vec3 absInvRay, bvec3 parallel)
{
	vec3 offset = nodes[node].center - origin;
	vec3 extents = nodes[node].extents;
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

bool MapTriangleHit(int element, vec3 origin, vec3 ray)
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
	return scale >= FLT_EPSILON && min(u, v) >= 0.0 && u + v <= scale &&
		distance > FLT_EPSILON * scale && distance < scale;
}

bool TraceOpaqueMapHit(vec3 origin, vec3 dir, float distance, int group)
{
	if (distance <= 0.0 || nodesRoot < 0) return false;
	// All rays for a light start at the same end of the segment. Neighbouring
	// fragments encounter the same near nodes and register stack entries.
	vec3 ray = -dir * distance;
	origin -= ray;
	bvec3 parallel = equal(ray, vec3(0.0));
	vec3 invRay = 1.0 / mix(ray, vec3(1.0), parallel);
	vec3 absInvRay = abs(invRay);
	int node = nodesRoot;
	ivec4 front = ivec4(0);
	int spill[64], depth = 0;
	while (true)
	{
		int element = nodes[node].element_index;
		if (element >= 0)
		{
			if (MapTriangleHit(element, origin, ray) && IsOpaqueMapCaster(element / 3, group))
				return true;
		}
		else
		{
			int left = nodes[node].left, right = nodes[node].right;
			float a = MapNodeEntry(left, origin, invRay, absInvRay, parallel);
			float b = MapNodeEntry(right, origin, invRay, absInvRay, parallel);
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
	return false;
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
