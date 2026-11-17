#pragma once

#include "tarray.h"
#include "vectors.h"
#include "vulkan/textures/vk_imagetransition.h"

class VSMatrix;
struct IntRect;
struct HWShadowPuppetMesh;

class VkShadowPuppetStencil
{
public:
	explicit VkShadowPuppetStencil(VulkanRenderDevice* device) : Fb(device) {}
	~VkShadowPuppetStencil();
	bool Supported() const;

	// The camera matrix produces Vulkan clip coordinates. Scene depth already
	// contains the opaque receiver prepass. Returns the sampled visibility slot.
	int Render(const HWShadowPuppetMesh& mesh, FVector3 light,
		const VSMatrix& cameraProjection, const IntRect& viewport);

private:
	void CreatePipelines();
	void ResizeVisibility(int width, int height);

	VulkanRenderDevice* Fb;
	VkTextureImage Visibility;
	VkTextureImage MultisampledVisibility;
	std::unique_ptr<VulkanSampler> Sampler;
	std::unique_ptr<VulkanRenderPass> Pass;
	std::unique_ptr<VulkanPipelineLayout> Layout;
	std::unique_ptr<VulkanPipeline> Volume, Resolve;
	std::unique_ptr<VulkanBuffer> Vertices;
	VkSampleCountFlagBits Samples = VK_SAMPLE_COUNT_1_BIT;
	int TextureIndex = 0;
};
