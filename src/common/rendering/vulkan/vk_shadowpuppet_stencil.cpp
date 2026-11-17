#include "vk_shadowpuppet_stencil.h"

#include "intrect.h"
#include "matrix.h"
#include "vulkan/descriptorsets/vk_descriptorset.h"
#include "vulkan/shaders/vk_shadercache.h"
#include "vulkan/textures/vk_renderbuffers.h"
#include "vulkan/vk_renderstate.h"

#include <algorithm>
#include <array>
#include <map>

namespace
{
constexpr auto VisibilityFormat = VK_FORMAT_R8_UNORM;
constexpr unsigned VertexCapacity = 4096;
constexpr auto DepthStages = VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT | VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT;
constexpr auto DepthAccess = VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_READ_BIT | VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT;
static_assert(VertexCapacity * sizeof(FVector4) <= 65536);
static_assert(sizeof(FVector4) == sizeof(float) * 4);

constexpr char VolumeVertexShader[] = R"(
#version 450
layout(location = 0) in vec4 Position;
layout(push_constant) uniform Projection { mat4 WorldToCamera; };
void main()
{
	gl_Position = WorldToCamera * Position;
}
)";

constexpr char VolumeFragmentShader[] = R"(
#version 450
layout(early_fragment_tests) in;
void main() {}
)";

constexpr char ResolveVertexShader[] = R"(
#version 450
void main()
{
	vec2 position = vec2((gl_VertexIndex << 1) & 2, gl_VertexIndex & 2);
	gl_Position = vec4(position * 2.0 - 1.0, 0.0, 1.0);
}
)";

constexpr char ResolveFragmentShader[] = R"(
#version 450
layout(early_fragment_tests) in;
layout(location = 0) out float Visibility;
void main() { Visibility = 0.0; }
)";

using Point = std::array<float, 3>;
using Edge = std::pair<Point, Point>;

Point EdgePoint(FVector3 point)
{
	return { point.X, point.Y, point.Z };
}

FVector4 Homogeneous(FVector3 position, float w)
{
	return { position.X, position.Y, position.Z, w };
}

void AddTriangle(TArray<FVector4>& output, FVector4 a, FVector4 b, FVector4 c)
{
	output.Push(a);
	output.Push(b);
	output.Push(c);
}

void BuildVolume(TArray<FVector4>& output, const TArray<FVector3>& triangles, FVector3 light)
{
	std::map<Edge, unsigned> silhouette;
	for (unsigned i = 0; i + 2 < triangles.Size(); i += 3)
	{
		auto a = triangles[i], b = triangles[i + 1], c = triangles[i + 2];
		if ((((b - a) ^ (c - a)) | (light - a)) <= 0.0f) continue;

		// Each light-facing triangle forms the near cap and the opposite-winding
		// far cap. Directions with w=0 close the volume at infinity.
		AddTriangle(output, Homogeneous(a, 1), Homogeneous(b, 1), Homogeneous(c, 1));
		AddTriangle(output, Homogeneous(c - light, 0), Homogeneous(b - light, 0), Homogeneous(a - light, 0));
		const Point cap[3] = { EdgePoint(a), EdgePoint(b), EdgePoint(c) };
		for (unsigned edge = 0; edge < 3; ++edge)
		{
			const auto& from = cap[edge];
			const auto& to = cap[(edge + 1) % 3];
			auto opposite = silhouette.find({ to, from });
			if (opposite == silhouette.end())
				++silhouette[{ from, to }];
			else if (--opposite->second == 0)
				silhouette.erase(opposite);
		}
	}

	// Edges shared by two facing triangles cancel. Cap boundary edges each
	// extrude into a quad whose winding closes the corresponding near edge.
	for (const auto& [edge, count] : silhouette)
	{
		const auto& [from, to] = edge;
		FVector3 a(from[0], from[1], from[2]), b(to[0], to[1], to[2]);
		for (unsigned i = 0; i < count; ++i)
		{
			AddTriangle(output, Homogeneous(a, 1), Homogeneous(a - light, 0), Homogeneous(b - light, 0));
			AddTriangle(output, Homogeneous(a, 1), Homogeneous(b - light, 0), Homogeneous(b, 1));
		}
	}
}
}

VkShadowPuppetStencil::~VkShadowPuppetStencil()
{
	if (TextureIndex)
		Fb->GetDescriptorSetManager()->FreeBindlessSlot(TextureIndex);
}

bool VkShadowPuppetStencil::Supported() const
{
	if (!Fb->GetBuffers() || Fb->GetBuffers()->GetSceneSamples() != VK_SAMPLE_COUNT_1_BIT ||
		!Fb->GetDevice()->EnabledFeatures.Features.depthClamp || Fb->DepthStencilFormat == VK_FORMAT_UNDEFINED)
		return false;

	return Pass || ImageBuilder().Size(1, 1).Format(VisibilityFormat)
		.Usage(VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT)
		.IsFormatSupported(Fb->GetDevice());
}

void VkShadowPuppetStencil::CreatePipelines()
{
	auto device = Fb->GetDevice();
	Pass = RenderPassBuilder()
		.AddAttachment(VisibilityFormat, VK_SAMPLE_COUNT_1_BIT,
			VK_ATTACHMENT_LOAD_OP_CLEAR, VK_ATTACHMENT_STORE_OP_STORE,
			VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL)
		.AddDepthStencilAttachment(Fb->DepthStencilFormat, VK_SAMPLE_COUNT_1_BIT,
			VK_ATTACHMENT_LOAD_OP_LOAD, VK_ATTACHMENT_STORE_OP_STORE,
			VK_ATTACHMENT_LOAD_OP_CLEAR, VK_ATTACHMENT_STORE_OP_DONT_CARE,
			VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL)
		.AddSubpass()
		.AddSubpassColorAttachmentRef(0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL)
		.AddSubpassDepthStencilAttachmentRef(1, VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL)
		.DebugName("PuppetStencil.Pass")
		.Create(device);
	Layout = PipelineLayoutBuilder()
		.AddPushConstantRange(VK_SHADER_STAGE_VERTEX_BIT, 0, sizeof(float) * 16)
		.DebugName("PuppetStencil.Layout")
		.Create(device);

	const auto volumeVert = CachedGLSLCompiler().Type(ShaderType::Vertex)
		.AddSource("puppet_stencil_volume.vert", VolumeVertexShader).Compile(Fb);
	const auto volumeFrag = CachedGLSLCompiler().Type(ShaderType::Fragment)
		.AddSource("puppet_stencil_volume.frag", VolumeFragmentShader).Compile(Fb);
	const auto makeVolumePipeline = [&](VkCullModeFlags cull, VkStencilOp depthFail, const char* name)
	{
		return GraphicsPipelineBuilder()
			.AddVertexShader(volumeVert)
			.AddFragmentShader(volumeFrag)
			.AddVertexBufferBinding(0, sizeof(FVector4))
			.AddVertexAttribute(0, 0, VK_FORMAT_R32G32B32A32_SFLOAT, 0)
			.Topology(VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST)
			.AddDynamicState(VK_DYNAMIC_STATE_VIEWPORT)
			.AddDynamicState(VK_DYNAMIC_STATE_SCISSOR)
			.Cull(cull, VK_FRONT_FACE_COUNTER_CLOCKWISE)
			.DepthClampEnable(true)
			.DepthStencilEnable(true, false, true)
			.DepthFunc(VK_COMPARE_OP_LESS_OR_EQUAL)
			.Stencil(VK_STENCIL_OP_KEEP, VK_STENCIL_OP_KEEP, depthFail, VK_COMPARE_OP_ALWAYS, 0xff, 0xff, 0)
			.AddColorBlendAttachment(ColorBlendAttachmentBuilder().ColorWriteMask(0).Create())
			.Layout(Layout.get())
			.RenderPass(Pass.get())
			.DebugName(name)
			.Create(device);
	};
	FrontFaces = makeVolumePipeline(VK_CULL_MODE_BACK_BIT, VK_STENCIL_OP_DECREMENT_AND_WRAP, "PuppetStencil.Front");
	BackFaces = makeVolumePipeline(VK_CULL_MODE_FRONT_BIT, VK_STENCIL_OP_INCREMENT_AND_WRAP, "PuppetStencil.Back");

	Resolve = GraphicsPipelineBuilder()
		.AddVertexShader(CachedGLSLCompiler().Type(ShaderType::Vertex)
			.AddSource("puppet_stencil_resolve.vert", ResolveVertexShader).Compile(Fb))
		.AddFragmentShader(CachedGLSLCompiler().Type(ShaderType::Fragment)
			.AddSource("puppet_stencil_resolve.frag", ResolveFragmentShader).Compile(Fb))
		.Topology(VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST)
		.AddDynamicState(VK_DYNAMIC_STATE_VIEWPORT)
		.AddDynamicState(VK_DYNAMIC_STATE_SCISSOR)
		.Cull(VK_CULL_MODE_NONE, VK_FRONT_FACE_COUNTER_CLOCKWISE)
		.DepthStencilEnable(false, false, true)
		.Stencil(VK_STENCIL_OP_KEEP, VK_STENCIL_OP_KEEP, VK_STENCIL_OP_KEEP, VK_COMPARE_OP_NOT_EQUAL, 0xff, 0, 0)
		.AddColorBlendAttachment(ColorBlendAttachmentBuilder().ColorWriteMask(VK_COLOR_COMPONENT_R_BIT).Create())
		.Layout(Layout.get())
		.RenderPass(Pass.get())
		.DebugName("PuppetStencil.Resolve")
		.Create(device);

	Sampler = SamplerBuilder()
		.AddressMode(VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE)
		.MinFilter(VK_FILTER_NEAREST).MagFilter(VK_FILTER_NEAREST).MaxLod(0)
		.DebugName("PuppetStencil.Nearest")
		.Create(device);
	Vertices = BufferBuilder()
		.Size(VertexCapacity * sizeof(FVector4))
		.Usage(VK_BUFFER_USAGE_VERTEX_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT)
		.DebugName("PuppetStencil.Vertices")
		.Create(device);
}

void VkShadowPuppetStencil::ResizeVisibility(int width, int height)
{
	auto descriptors = Fb->GetDescriptorSetManager();
	if (Visibility.Image)
	{
		// The bindless allocator can reuse a slot immediately. Wait for old
		// readers before rebinding this slot to the resized image.
		Fb->WaitForCommands(false);
		Visibility.Reset(Fb);
	}
	Visibility.Image = ImageBuilder().Size(width, height).Format(VisibilityFormat)
		.Usage(VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT)
		.DebugName("PuppetStencil.Visibility").Create(Fb->GetDevice());
	Visibility.View = ImageViewBuilder()
		.Image(Visibility.Image.get(), VisibilityFormat, VK_IMAGE_ASPECT_COLOR_BIT)
		.DebugName("PuppetStencil.VisibilityView").Create(Fb->GetDevice());
	if (!TextureIndex) TextureIndex = descriptors->AllocBindlessSlot(1);
	descriptors->SetBindlessTexture(TextureIndex, Visibility.View.get(), Sampler.get());
}

int VkShadowPuppetStencil::Render(const TArray<FVector3>& triangles, FVector3 light,
	const VSMatrix& cameraProjection, const IntRect& viewport)
{
	if (!Supported() || triangles.Size() == 0 || triangles.Size() % 3 != 0) return 0;
	auto buffers = Fb->GetBuffers();
	auto& sceneDepth = buffers->SceneDepthStencil;
	const int width = buffers->GetWidth(), height = buffers->GetHeight();
	const int x0 = std::clamp(viewport.left, 0, width), y0 = std::clamp(viewport.top, 0, height);
	const int x1 = std::clamp(viewport.Right(), 0, width), y1 = std::clamp(viewport.Bottom(), 0, height);
	if (x0 >= x1 || y0 >= y1 || sceneDepth.Layout != VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL) return 0;

	TArray<FVector4> volume;
	BuildVolume(volume, triangles, light);
	if (volume.Size() == 0 || volume.Size() > VertexCapacity) return 0;
	if (!Pass) CreatePipelines();
	if (!Visibility.Image || Visibility.Image->width != width || Visibility.Image->height != height)
		ResizeVisibility(width, height);

	auto framebuffer = FramebufferBuilder().Size(width, height).RenderPass(Pass.get())
		.AddAttachment(Visibility.View.get()).AddAttachment(sceneDepth.View.get())
		.DebugName("PuppetStencil.Framebuffer").Create(Fb->GetDevice());

	Fb->GetRenderState()->EndRenderPass();
	auto commands = Fb->GetCommands();
	auto draw = commands->GetDrawCommands();
	commands->PushGroup(draw, "puppet.stencil");
	PipelineBarrier().AddBuffer(Vertices.get(), VK_ACCESS_VERTEX_ATTRIBUTE_READ_BIT, VK_ACCESS_TRANSFER_WRITE_BIT)
		.Execute(draw, VK_PIPELINE_STAGE_VERTEX_INPUT_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT);
	draw->updateBuffer(Vertices->buffer, 0, volume.Size() * sizeof(FVector4), volume.Data());
	PipelineBarrier().AddBuffer(Vertices.get(), VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_VERTEX_ATTRIBUTE_READ_BIT)
		.Execute(draw, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_VERTEX_INPUT_BIT);
	VkImageTransition().AddImage(&Visibility, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, false).Execute(draw);
	PipelineBarrier().AddMemory(DepthAccess, DepthAccess).Execute(draw, DepthStages, DepthStages);

	RenderPassBegin().RenderPass(Pass.get()).RenderArea(0, 0, width, height).Framebuffer(framebuffer.get())
		.AddClearColor(1, 1, 1, 1).AddClearDepthStencil(1.0f, 0).Execute(draw);
	const VkViewport area = { float(viewport.left), float(viewport.top), float(viewport.width), float(viewport.height), 0.0f, 1.0f };
	const VkRect2D scissor = { { x0, y0 }, { uint32_t(x1 - x0), uint32_t(y1 - y0) } };
	draw->setViewport(0, 1, &area);
	draw->setScissor(0, 1, &scissor);
	const VkDeviceSize offset = 0;
	draw->bindVertexBuffers(0, 1, &Vertices->buffer, &offset);
	float projection[16];
	for (int i = 0; i < 16; ++i) projection[i] = static_cast<float>(cameraProjection.get()[i]);
	draw->pushConstants(Layout.get(), VK_SHADER_STAGE_VERTEX_BIT, 0, sizeof(projection), projection);
	draw->bindPipeline(VK_PIPELINE_BIND_POINT_GRAPHICS, FrontFaces.get());
	draw->draw(volume.Size(), 1, 0, 0);
	draw->bindPipeline(VK_PIPELINE_BIND_POINT_GRAPHICS, BackFaces.get());
	draw->draw(volume.Size(), 1, 0, 0);
	draw->bindPipeline(VK_PIPELINE_BIND_POINT_GRAPHICS, Resolve.get());
	draw->draw(3, 1, 0, 0);
	draw->endRenderPass();

	VkImageTransition().AddImage(&Visibility, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL, false).Execute(draw);
	PipelineBarrier().AddMemory(DepthAccess, DepthAccess).Execute(draw, DepthStages, DepthStages);
	commands->PopGroup(draw);
	commands->DrawDeleteList->Add(std::move(framebuffer));
	// Return a clean stencil to the engine's portal pass, keeping receiver depth.
	Fb->GetRenderState()->Clear(CT_Stencil);
	return TextureIndex;
}
