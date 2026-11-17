#pragma once

#include "tarray.h"
#include "vectors.h"
#include "vulkan/textures/vk_imagetransition.h"

class VSMatrix;
struct IntRect;

class VkShadowPuppetStencil
{
public:
	explicit VkShadowPuppetStencil(VulkanRenderDevice* device) : Fb(device) {}
	~VkShadowPuppetStencil();
	bool Supported() const;

	// The camera matrix produces Vulkan clip coordinates. Scene depth already
	// contains the opaque receiver prepass. Returns the sampled visibility slot.
	int Render(const TArray<FVector3>& triangles, FVector3 light, const VSMatrix& cameraProjection, const IntRect& viewport);

private:
	void CreatePipelines();
	void ResizeVisibility(int width, int height);

	VulkanRenderDevice* Fb;
	VkTextureImage Visibility;
	std::unique_ptr<VulkanSampler> Sampler;
	std::unique_ptr<VulkanRenderPass> Pass;
	std::unique_ptr<VulkanPipelineLayout> Layout;
	std::unique_ptr<VulkanPipeline> FrontFaces, BackFaces, Resolve;
	std::unique_ptr<VulkanBuffer> Vertices;
	int TextureIndex = 0;
};
