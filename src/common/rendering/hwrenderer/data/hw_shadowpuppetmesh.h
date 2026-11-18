#pragma once

#include "tarray.h"
#include "vectors.h"

// Opaque sprite caps face the light. Edge pairs follow the same winding.
struct HWShadowPuppetMesh
{
	TArray<FVector3> Triangles, Edges;
	TArray<FVector3> MapTriangles; // Opaque world triangles, in the same render coordinates as the sprite caps.
	struct BatchEnd { unsigned Triangles, Edges; };
	TArray<BatchEnd> StencilBatches;
};
