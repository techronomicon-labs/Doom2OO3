#pragma once

#include <array>

class FGameTexture;
class FMaterial;

struct PBRMaterialTuning
{
	std::array<float, 5> Values = { 0.f, 0.f, 1.f, 1.f, 1.f };
};

bool CanTunePBRMaterial(FGameTexture* texture);
const PBRMaterialTuning& GetPBRMaterialTuning(const FMaterial& material);
