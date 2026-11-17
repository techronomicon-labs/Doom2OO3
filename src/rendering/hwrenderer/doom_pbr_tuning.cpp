#include "doom_pbr_pick.h"
#include "doom_levelmesh.h"
#include "filesystem.h"
#include "cmdlib.h"
#include "gameconfigfile.h"
#include "hw_material.h"
#include "texturemanager.h"
#include "vm.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <map>
#include <sstream>
#include <string>

namespace
{
const PBRMaterialTuning Defaults;
using Overrides = std::map<std::string, PBRMaterialTuning>;
Overrides Saved;
const FGameConfigFile* ConfigOwner = nullptr;
uint64_t Revision = 1;

FTextureID SelectedId;
std::string SelectedKey;
PBRMaterialTuning Preview;

const char* MaterialKind(ETextureType type)
{
	switch (type)
	{
	case ETextureType::Wall: return "wall";
	case ETextureType::Flat: return "flat";
	case ETextureType::Sprite:
	case ETextureType::SkinSprite: return "sprite";
	default: return "texture";
	}
}

std::string KeyPart(const char* text)
{
	static constexpr char Hex[] = "0123456789abcdef";
	std::string result;
	for (const unsigned char* c = reinterpret_cast<const unsigned char*>(text); *c; ++c)
	{
		if ((*c >= 'a' && *c <= 'z') || (*c >= '0' && *c <= '9') || *c == '.' || *c == '_' || *c == '-')
			result += char(*c);
		else if (*c >= 'A' && *c <= 'Z')
			result += char(*c + ('a' - 'A'));
		else
		{
			result += '%';
			result += Hex[*c >> 4];
			result += Hex[*c & 15];
		}
	}
	return result;
}

std::string ResourceKey(int lump)
{
	const auto file = fileSystem.GetResourceFileName(fileSystem.GetFileContainer(lump));
	return file ? KeyPart(ExtractFileBase(file, true).GetChars()) : std::string();
}

std::string MaterialKey(FGameTexture& texture)
{
	// Keep names stable across different installations of the same packages.
	const auto iwad = fileSystem.GetResourceFileName(fileSystem.GetIwadNum());
	return (iwad ? KeyPart(ExtractFileBase(iwad, true).GetChars()) : std::string()) + "|" +
		ResourceKey(texture.GetSourceLump()) + "|" + ResourceKey(texture.GetMetallic()->GetSourceLump()) + "|" +
		std::to_string(int(texture.GetUseType())) + ":" + KeyPart(texture.GetName().GetChars());
}

std::filesystem::path OverridePath()
{
	auto path = std::filesystem::u8path(GameConfig->GetPathName());
	path += ".materials";
	return path;
}

bool ReadOverrides(const std::filesystem::path& path, Overrides& entries)
{
	std::error_code error;
	const bool exists = std::filesystem::exists(path, error);
	if (error || !exists)
		return !error;
	std::ifstream file(path);
	if (!file)
		return false;

	std::string line;
	while (std::getline(file, line))
	{
		if (line.empty() || line.front() == '#')
			continue;
		std::istringstream row(line);
		std::string key, extra;
		std::array<int, 5> values;
		if (!(row >> key >> values[0] >> values[1] >> values[2] >> values[3] >> values[4]) || row >> extra)
			continue;
		PBRMaterialTuning tuning;
		for (size_t i = 0; i < values.size(); ++i)
			tuning.Values[i] = std::clamp(values[i], i < 2 ? -100 : 0, i < 2 ? 100 : 200) / 100.f;
		entries[key] = tuning;
	}
	return file.eof() && !file.bad();
}

bool WriteOverrides(const std::filesystem::path& path, const Overrides& entries)
{
	auto temporary = path;
	temporary += ".tmp-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count());
	std::ofstream file(temporary);
	if (!file)
		return false;
	file << "# PBR material overrides. Roughness, metalness, normal, AO and depth in hundredths.\n";
	for (const auto& [key, tuning] : entries)
	{
		file << key;
		for (float value : tuning.Values)
			file << ' ' << std::lround(value * 100.f);
		file << '\n';
	}
	file.close();

	std::error_code error;
	if (file)
	{
		std::filesystem::rename(temporary, path, error);
		if (!error)
			return true;
	}
	std::filesystem::remove(temporary, error);
	return false;
}

void LoadProfile()
{
	if (ConfigOwner == GameConfig)
		return;
	ConfigOwner = GameConfig;
	Saved.clear();
	SelectedId = {};
	SelectedKey.clear();
	Preview = Defaults;
	if (GameConfig)
		ReadOverrides(OverridePath(), Saved);
	++Revision;
}

const PBRMaterialTuning& SavedTuning(const std::string& key)
{
	const auto saved = Saved.find(key);
	return saved == Saved.end() ? Defaults : saved->second;
}

FGameTexture* SelectedTexture()
{
	LoadProfile();
	if (SelectedKey.empty())
		return nullptr;
	auto texture = TexMan.GetGameTexture(SelectedId);
	return CanTunePBRMaterial(texture) && MaterialKey(*texture) == SelectedKey ? texture : nullptr;
}

bool Select(FGameTexture* texture)
{
	if (!CanTunePBRMaterial(texture))
		return false;
	auto key = MaterialKey(*texture);
	if (key == SelectedKey && SelectedId == texture->GetID())
		return true;
	auto previous = SelectedTexture();
	SelectedId = texture->GetID();
	SelectedKey = std::move(key);
	Preview = SavedTuning(SelectedKey);
	++Revision;
	if (previous)
		InvalidatePBRLevelMesh(previous);
	return true;
}

FGameTexture* FindMaterial(const FString& input)
{
	std::string name = input.GetChars();
	const auto start = name.find_first_not_of(" \t");
	if (start == std::string::npos)
		return nullptr;
	name = name.substr(start, name.find_last_not_of(" \t") - start + 1);
	std::string kind;
	const auto separator = name.find(':');
	if (separator != std::string::npos)
	{
		kind = KeyPart(name.substr(0, separator).c_str());
		name.erase(0, separator + 1);
		name.erase(0, name.find_first_not_of(" \t"));
	}

	TArray<FTextureID> choices;
	TexMan.ListTextures(name.c_str(), choices);
	FGameTexture* match = nullptr;
	for (const auto id : choices)
	{
		auto texture = TexMan.GetGameTexture(id);
		if (!CanTunePBRMaterial(texture) || (!kind.empty() && kind != MaterialKind(texture->GetUseType())))
			continue;
		if (match)
			return nullptr;
		match = texture;
	}
	return match;
}
}

bool CanTunePBRMaterial(FGameTexture* texture)
{
	return texture && texture->isValid() && texture->GetName().IsNotEmpty() && !texture->isWarped() &&
		!texture->isHardwareCanvas() && !texture->isSoftwareCanvas() &&
		texture->GetNormalmap() && !texture->GetSpecularmap() && texture->GetMetallic() &&
		texture->GetRoughness() && texture->GetAmbientOcclusion();
}

const PBRMaterialTuning& GetPBRMaterialTuning(const FMaterial& material)
{
	LoadProfile();
	if (SelectedKey.empty() && Saved.empty())
		return Defaults;
	if (material.mTuningRevision != Revision)
	{
		auto texture = material.Source();
		material.mTuning = Defaults;
		if (CanTunePBRMaterial(texture))
		{
			const auto key = MaterialKey(*texture);
			material.mTuning = key == SelectedKey ? Preview : SavedTuning(key);
		}
		material.mTuningRevision = Revision;
	}
	return material.mTuning;
}

DEFINE_ACTION_FUNCTION(DPBRMaterialMenu, PickAimedMaterial)
{
	PARAM_PROLOGUE;
	LoadProfile();
	ACTION_RETURN_INT(Select(PickPBRMaterial()));
}

DEFINE_ACTION_FUNCTION(DPBRMaterialMenu, SelectMaterial)
{
	PARAM_PROLOGUE;
	PARAM_STRING(name);
	LoadProfile();
	ACTION_RETURN_INT(Select(FindMaterial(name)));
}

DEFINE_ACTION_FUNCTION(DPBRMaterialMenu, GetMaterialLabel)
{
	PARAM_PROLOGUE;
	auto texture = SelectedTexture();
	ACTION_RETURN_STRING(texture ? FStringf("%s: %s", MaterialKind(texture->GetUseType()), texture->GetName().GetChars()) : FString());
}

DEFINE_ACTION_FUNCTION(DPBRMaterialMenu, GetParameter)
{
	PARAM_PROLOGUE;
	PARAM_INT(parameter);
	ACTION_RETURN_FLOAT(parameter >= 0 && size_t(parameter) < Preview.Values.size() ? Preview.Values[parameter] : 0.f);
}

DEFINE_ACTION_FUNCTION(DPBRMaterialMenu, SetParameter)
{
	PARAM_PROLOGUE;
	PARAM_INT(parameter);
	PARAM_FLOAT(value);
	auto texture = SelectedTexture();
	if (texture && parameter >= 0 && size_t(parameter) < Preview.Values.size() && std::isfinite(value))
	{
		const auto adjusted = float(std::round(std::clamp(value, parameter < 2 ? -1.0 : 0.0,
			parameter < 2 ? 1.0 : 2.0) * 100.0) / 100.0);
		if (Preview.Values[parameter] != adjusted)
		{
			Preview.Values[parameter] = adjusted;
			++Revision;
			InvalidatePBRLevelMesh(texture);
		}
	}
	return 0;
}

DEFINE_ACTION_FUNCTION(DPBRMaterialMenu, HasRelief)
{
	PARAM_PROLOGUE;
	auto texture = SelectedTexture();
	ACTION_RETURN_INT(texture && texture->GetHeightmap());
}

DEFINE_ACTION_FUNCTION(DPBRMaterialMenu, SaveOverrides)
{
	PARAM_PROLOGUE;
	if (!SelectedTexture() || !GameConfig)
		ACTION_RETURN_INT(false);
	const auto path = OverridePath();
	Overrides entries;
	if (!ReadOverrides(path, entries))
		ACTION_RETURN_INT(false);
	if (Preview.Values == Defaults.Values)
		entries.erase(SelectedKey);
	else
		entries[SelectedKey] = Preview;
	if (!WriteOverrides(path, entries))
		ACTION_RETURN_INT(false);
	Saved = std::move(entries);
	++Revision;
	ACTION_RETURN_INT(true);
}

DEFINE_ACTION_FUNCTION(DPBRMaterialMenu, ResetOverrides)
{
	PARAM_PROLOGUE;
	auto texture = SelectedTexture();
	if (texture && Preview.Values != Defaults.Values)
	{
		Preview = Defaults;
		++Revision;
		InvalidatePBRLevelMesh(texture);
	}
	return 0;
}

DEFINE_ACTION_FUNCTION(DPBRMaterialMenu, DiscardPreview)
{
	PARAM_PROLOGUE;
	auto texture = SelectedTexture();
	if (texture && Preview.Values != SavedTuning(SelectedKey).Values)
	{
		Preview = SavedTuning(SelectedKey);
		++Revision;
		InvalidatePBRLevelMesh(texture);
	}
	return 0;
}
