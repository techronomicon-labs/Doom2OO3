#pragma once

#include "tarray.h"
#include "vectors.h"

// Opaque sprite caps face the light. Edge pairs follow the same winding.
struct HWShadowPuppetMesh
{
	TArray<FVector3> Triangles, Edges;
	struct BatchEnd { unsigned Triangles, Edges; };
	TArray<BatchEnd> StencilBatches;
};
