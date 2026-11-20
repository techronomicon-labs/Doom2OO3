#include "vk_shadowpuppet_depth.h"
#include "vk_shadowpuppet_vertices.h"

#include "matrix.h"
#include "vulkan/descriptorsets/vk_descriptorset.h"
#include "vulkan/shaders/vk_shadercache.h"
#include "vulkan/pipelines/vk_renderpass.h"
#include "vulkan/vk_renderdevice.h"
#include "vulkan/vk_renderstate.h"

namespace
{
constexpr unsigned MapSize = 1024;
static_assert(sizeof(FVector3) == sizeof(float) * 3);

constexpr char DepthVertexShader[] = R"(
#version 450
layout(location = 0) in vec3 Position;
layout(push_constant) uniform Projection { mat4 WorldToLight; };
void main()
{
	gl_Position = WorldToLight * vec4(Position, 1.0);
}
)";
}

VkShadowPuppetDepth::~VkShadowPuppetDepth()
{
	if (TextureIndex)
		Fb->GetDescriptorSetManager()->FreeBindlessSlot(TextureIndex);
}

bool VkShadowPuppetDepth::PreparePipeline()
{
	if (TriedPipeline) return Pipeline != nullptr;
	TriedPipeline = true;
	auto device = Fb->GetDevice();
	DepthFormat = VK_FORMAT_D32_SFLOAT;
	ImageBuilder image;
	image.Size(MapSize, MapSize)
		.Usage(VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT)
		.DebugName("PuppetDepth.Image");
	if (!image.Format(DepthFormat).IsFormatSupported(device))
	{
		DepthFormat = VK_FORMAT_D16_UNORM;
		if (!image.Format(DepthFormat).IsFormatSupported(device)) return false;
	}
	Pass = RenderPassBuilder()
		.AddDepthStencilAttachment(DepthFormat, VK_SAMPLE_COUNT_1_BIT,
			VK_ATTACHMENT_LOAD_OP_CLEAR, VK_ATTACHMENT_STORE_OP_STORE,
			VK_ATTACHMENT_LOAD_OP_DONT_CARE, VK_ATTACHMENT_STORE_OP_DONT_CARE,
			VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL)
		.AddSubpass()
		.AddSubpassDepthStencilAttachmentRef(0, VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL)
		.DebugName("PuppetDepth.Pass")
		.Create(device);
	Layout = PipelineLayoutBuilder()
		.AddPushConstantRange(VK_SHADER_STAGE_VERTEX_BIT, 0, sizeof(float) * 16)
		.DebugName("PuppetDepth.Layout")
		.Create(device);
	Pipeline = GraphicsPipelineBuilder()
		.Cache(Fb->GetRenderPassManager()->GetCache())
		.AddVertexShader(CachedGLSLCompiler().Type(ShaderType::Vertex)
			.AddSource("puppet_depth.vert", DepthVertexShader).Compile(Fb))
		.AddVertexBufferBinding(0, sizeof(FVector3))
		.AddVertexAttribute(0, 0, VK_FORMAT_R32G32B32_SFLOAT, 0)
		.Topology(VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST)
		.Viewport(0, 0, MapSize, MapSize)
		.Scissor(0, 0, MapSize, MapSize)
		.Cull(VK_CULL_MODE_NONE, VK_FRONT_FACE_COUNTER_CLOCKWISE)
		.DepthStencilEnable(true, true, false)
		.DepthFunc(VK_COMPARE_OP_LESS)
		.Layout(Layout.get())
		.RenderPass(Pass.get())
		.DebugName("PuppetDepth.Pipeline")
		.Create(device);
	return true;
}

void VkShadowPuppetDepth::CreateTarget()
{
	auto device = Fb->GetDevice();
	Depth.AspectMask = VK_IMAGE_ASPECT_DEPTH_BIT;
	Depth.Image = ImageBuilder().Size(MapSize, MapSize).Format(DepthFormat)
		.Usage(VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT)
		.DebugName("PuppetDepth.Image").Create(device);
	Depth.View = ImageViewBuilder()
		.Image(Depth.Image.get(), DepthFormat, VK_IMAGE_ASPECT_DEPTH_BIT)
		.DebugName("PuppetDepth.View")
		.Create(device);
	Sampler = SamplerBuilder()
		.AddressMode(VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE)
		.MinFilter(VK_FILTER_NEAREST)
		.MagFilter(VK_FILTER_NEAREST)
		.MaxLod(0)
		.DebugName("PuppetDepth.Nearest")
		.Create(device);

	Framebuffer = FramebufferBuilder()
		.Size(MapSize, MapSize)
		.RenderPass(Pass.get())
		.AddAttachment(Depth.View.get())
		.DebugName("PuppetDepth.Framebuffer")
		.Create(device);
	auto descriptors = Fb->GetDescriptorSetManager();
	TextureIndex = descriptors->AllocBindlessSlot(1);
	descriptors->SetBindlessTexture(TextureIndex, Depth.View.get(), Sampler.get());
}

int VkShadowPuppetDepth::Render(const TArray<FVector3>& triangles, const VSMatrix& lightProjection)
{
	const auto count = triangles.Size();
	if (count == 0 || count % 3 != 0)
		return 0;
	if (!PreparePipeline()) return 0;
	if (!Depth.Image) CreateTarget();

	Fb->GetRenderState()->EndRenderPass();
	auto commands = Fb->GetCommands();
	auto draw = commands->GetDrawCommands();
	commands->PushGroup(draw, "puppet.depth");

	UploadShadowPuppetVertices(Fb, draw, Vertices, triangles.Data(), count * sizeof(FVector3), "PuppetDepth.Vertices");
	VkImageTransition().AddImage(&Depth, VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL, false).Execute(draw);

	RenderPassBegin()
		.RenderPass(Pass.get())
		.RenderArea(0, 0, MapSize, MapSize)
		.Framebuffer(Framebuffer.get())
		.AddClearDepth(1.0f)
		.Execute(draw);
	draw->bindPipeline(VK_PIPELINE_BIND_POINT_GRAPHICS, Pipeline.get());
	const VkDeviceSize offset = 0;
	draw->bindVertexBuffers(0, 1, &Vertices->buffer, &offset);
	float worldToLight[16];
	for (int i = 0; i < 16; ++i) worldToLight[i] = static_cast<float>(lightProjection.get()[i]);
	draw->pushConstants(Layout.get(), VK_SHADER_STAGE_VERTEX_BIT, 0, sizeof(worldToLight), worldToLight);
	draw->draw(static_cast<uint32_t>(count), 1, 0, 0);
	draw->endRenderPass();

	VkImageTransition().AddImage(&Depth, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL, false).Execute(draw);
	commands->PopGroup(draw);
	return TextureIndex;
}
