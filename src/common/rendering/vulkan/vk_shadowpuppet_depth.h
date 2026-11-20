#pragma once

#include "tarray.h"
#include "vectors.h"
#include "vulkan/textures/vk_imagetransition.h"

class VSMatrix;
class VulkanRenderDevice;

class VkShadowPuppetDepth
{
public:
	explicit VkShadowPuppetDepth(VulkanRenderDevice* device) : Fb(device) {}
	~VkShadowPuppetDepth();

	// Triangle vertices and projection use Vulkan scene coordinates (X, Z, Y).
	// Projection must produce depth in [0, w]. Returns the sampled depth slot.
	int Render(const TArray<FVector3>& triangles, const VSMatrix& lightProjection);

private:
	bool CreateResources();

	VulkanRenderDevice* Fb;
	VkTextureImage Depth;
	std::unique_ptr<VulkanSampler> Sampler;
	std::unique_ptr<VulkanRenderPass> Pass;
	std::unique_ptr<VulkanFramebuffer> Framebuffer;
	std::unique_ptr<VulkanPipelineLayout> Layout;
	std::unique_ptr<VulkanPipeline> Pipeline;
	std::unique_ptr<VulkanBuffer> Vertices;
	int TextureIndex = 0;
	bool TriedResources = false;
};
