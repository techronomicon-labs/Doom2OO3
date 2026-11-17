#pragma once

#include "vulkan/commands/vk_commandbuffer.h"
#include "vulkan/vk_renderdevice.h"
#include <zvulkan/vulkanbuilders.h>

#include <algorithm>

// Sprite contours vary by animation frame. Keep the largest buffer so far and
// retire its predecessor with the commands that may still reference it.
inline void UploadShadowPuppetVertices(VulkanRenderDevice* fb, VulkanCommandBuffer* draw,
	std::unique_ptr<VulkanBuffer>& buffer, const void* vertices, size_t bytes, const char* name)
{
	constexpr size_t updateLimit = 65536; // vkCmdUpdateBuffer maximum, in bytes
	if (!buffer || bytes > buffer->size)
	{
		fb->GetCommands()->DrawDeleteList->Add(std::move(buffer));
		const size_t capacity = (bytes + updateLimit - 1) / updateLimit * updateLimit;
		buffer = BufferBuilder().Size(capacity)
			.Usage(VK_BUFFER_USAGE_VERTEX_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT)
			.DebugName(name).Create(fb->GetDevice());
	}
	else
	{
		PipelineBarrier().AddBuffer(buffer.get(), VK_ACCESS_VERTEX_ATTRIBUTE_READ_BIT, VK_ACCESS_TRANSFER_WRITE_BIT)
			.Execute(draw, VK_PIPELINE_STAGE_VERTEX_INPUT_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT);
	}
	const auto* source = static_cast<const uint8_t*>(vertices);
	for (size_t offset = 0; offset < bytes; offset += updateLimit)
		draw->updateBuffer(buffer->buffer, offset, std::min(updateLimit, bytes - offset), source + offset);
	PipelineBarrier().AddBuffer(buffer.get(), VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_VERTEX_ATTRIBUTE_READ_BIT)
		.Execute(draw, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_VERTEX_INPUT_BIT);
}
