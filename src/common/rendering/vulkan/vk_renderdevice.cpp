/*
**  Vulkan backend
**  Copyright (c) 2016-2020 Magnus Norddahl
**
**  This software is provided 'as-is', without any express or implied
**  warranty.  In no event will the authors be held liable for any damages
**  arising from the use of this software.
**
**  Permission is granted to anyone to use this software for any purpose,
**  including commercial applications, and to alter it and redistribute it
**  freely, subject to the following restrictions:
**
**  1. The origin of this software must not be misrepresented; you must not
**     claim that you wrote the original software. If you use this software
**     in a product, an acknowledgment in the product documentation would be
**     appreciated but is not required.
**  2. Altered source versions must be plainly marked as such, and must not be
**     misrepresented as being the original software.
**  3. This notice may not be removed or altered from any source distribution.
**
*/

#include <zvulkan/vulkanobjects.h>
#include <zvulkan/cfxtrace.h>

#include <inttypes.h>

#include "v_video.h"
#include "m_png.h"

#include "r_videoscale.h"
#include "i_time.h"
#include "v_text.h"
#include "version.h"
#include "v_draw.h"

#include "actor.h"
#include "g_levellocals.h"
#include "hw_clock.h"
#include "hw_vrmodes.h"
#include "hw_cvars.h"
#include "hw_skydome.h"
#include "flatvertices.h"
#include "hw_meshbuilder.h"
#include "texturemanager.h"

#include "vk_renderdevice.h"
#include "vk_shadowpuppet_depth.h"
#include "vk_shadowpuppet_stencil.h"
#include "vulkan/vk_renderstate.h"
#include "vulkan/vk_postprocess.h"
#include "vulkan/vk_levelmesh.h"
#include "vulkan/vk_lightmapper.h"
#include "vulkan/vk_lightprober.h"
#include "vulkan/pipelines/vk_renderpass.h"
#include "vulkan/descriptorsets/vk_descriptorset.h"
#include "vulkan/shaders/vk_shader.h"
#include "vulkan/shaders/vk_shadercache.h"
#include "vulkan/samplers/vk_samplers.h"
#include "vulkan/textures/vk_renderbuffers.h"
#include "vulkan/textures/vk_hwtexture.h"
#include "vulkan/textures/vk_texture.h"
#include "vulkan/textures/vk_pfviewdiagnostics.h"
#include "vulkan/framebuffers/vk_framebuffer.h"
#include "vulkan/commands/vk_commandbuffer.h"
#include "vulkan/buffers/vk_hwbuffer.h"
#include "vulkan/buffers/vk_buffer.h"
#include "vulkan/buffers/vk_rsbuffers.h"
#include <zvulkan/vulkanswapchain.h>
#include <zvulkan/vulkanbuilders.h>
#include <zvulkan/vulkansurface.h>
#include <zvulkan/vulkancompatibledevice.h>
#include "engineerrors.h"
#include "c_dispatch.h"
#include "menu.h"
#include "cmdlib.h"

FString JitCaptureStackTrace(int framesToSkip, bool includeNativeFrames, int maxFrames = -1);

EXTERN_CVAR(Int, gl_tonemap)
EXTERN_CVAR(Int, screenblocks)
EXTERN_CVAR(Bool, cl_capfps)
EXTERN_CVAR(Bool, r_skipmats)
EXTERN_CVAR(Bool, gl_precache)
EXTERN_CVAR(Bool, gl_levelmesh)
EXTERN_CVAR(Bool, gl_ubershaders)
EXTERN_CVAR(Bool, gl_raytrace)
EXTERN_CVAR(Int, gl_viewmodel_lighting)

// Physical device info
static std::vector<VulkanCompatibleDevice> SupportedDevices;
int vkversion;
static TArray<FString> memheapnames;
static TArray<VmaBudget> membudgets;
static int hwtexturecount;

CUSTOM_CVAR(Bool, vk_debug, false, CVAR_ARCHIVE | CVAR_GLOBALCONFIG | CVAR_NOINITCALL)
{
	Printf("This won't take effect until " GAMENAME " is restarted.\n");
}

CVAR(Bool, vk_debug_callstack, true, CVAR_ARCHIVE | CVAR_GLOBALCONFIG)
CVAR(Bool, vk_amd_driver_check, true, CVAR_ARCHIVE | CVAR_GLOBALCONFIG)

CUSTOM_CVAR(Int, vk_device, 0, CVAR_ARCHIVE | CVAR_GLOBALCONFIG | CVAR_NOINITCALL)
{
	Printf("This won't take effect until " GAMENAME " is restarted.\n");
}

CUSTOM_CVAR(Bool, vk_rayquery, true, CVAR_ARCHIVE | CVAR_GLOBALCONFIG | CVAR_NOINITCALL)
{
	Printf("This won't take effect until " GAMENAME " is restarted.\n");
}

CCMD(vk_listdevices)
{
	for (size_t i = 0; i < SupportedDevices.size(); i++)
	{
		Printf("#%d - %s\n", (int)i, SupportedDevices[i].Device->Properties.Properties.deviceName);
	}
}

CCMD(vk_membudget)
{
	for (size_t i = 0; i < membudgets.size(); i++)
	{
		if (membudgets[i].budget != 0)
		{
			Printf("#%d%s - %d MB used out of %d MB estimated budget (%d%%)\n",
				(int)i, memheapnames[i].GetChars(),
				(int)(membudgets[i].usage / (1024 * 1024)),
				(int)(membudgets[i].budget / (1024 * 1024)),
				(int)(membudgets[i].usage * 100 / membudgets[i].budget));
		}
		else
		{
			Printf("#%d %s - %d MB used\n",
				(int)i, memheapnames[i].GetChars(),
				(int)(membudgets[i].usage / (1024 * 1024)));
		}
	}
	Printf("%d total hardware textures\n", hwtexturecount);
}

void I_BuildVKDeviceList(FOptionValues* opt)
{
	for (size_t i = 0; i < SupportedDevices.size(); i++)
	{
		unsigned int idx = opt->mValues.Reserve(1);
		opt->mValues[idx].Value = (double)i;
		opt->mValues[idx].Text = SupportedDevices[i].Device->Properties.Properties.deviceName;
	}
}

void VulkanError(const char* text)
{
	throw CVulkanError(text);
}

void VulkanPrintLog(const char* typestr, const std::string& msg)
{
	bool showcallstack = strstr(typestr, "error") != nullptr;

	if (showcallstack)
		Printf("\n");

	Printf(TEXTCOLOR_RED "[%s] ", typestr);
	Printf(TEXTCOLOR_WHITE "%s\n", msg.c_str());

	if (vk_debug_callstack && showcallstack)
	{
		FString callstack = JitCaptureStackTrace(0, true, 5);
		if (!callstack.IsEmpty())
			Printf("%s\n", callstack.GetChars());
	}
}

VulkanCapabilities VulkanCapabilities::FromDevice(VulkanDevice* device)
{
	VulkanCapabilities capabilities;
	const auto& properties = device->PhysicalDevice.Properties.Properties;
	const auto& descriptorFeatures = device->EnabledFeatures.DescriptorIndexing;
	const auto& coreLimits = properties.limits;
	const auto& indexingLimits = device->PhysicalDevice.Properties.DescriptorIndexing;

	capabilities.VendorID = properties.vendorID;
	capabilities.DeviceID = properties.deviceID;
	capabilities.DriverVersion = properties.driverVersion;
	capabilities.DeviceType = properties.deviceType;

	capabilities.DescriptorIndexing.PartiallyBound = descriptorFeatures.descriptorBindingPartiallyBound;
	capabilities.DescriptorIndexing.VariableDescriptorCount = descriptorFeatures.descriptorBindingVariableDescriptorCount;
	capabilities.DescriptorIndexing.SampledImageUpdateAfterBind = descriptorFeatures.descriptorBindingSampledImageUpdateAfterBind;
	capabilities.DescriptorIndexing.RuntimeDescriptorArray = descriptorFeatures.runtimeDescriptorArray;
	capabilities.DescriptorIndexing.SampledImageArrayNonUniformIndexing = descriptorFeatures.shaderSampledImageArrayNonUniformIndexing;

	capabilities.BindlessLimits.MaxPerStageDescriptorSamplers = coreLimits.maxPerStageDescriptorSamplers;
	capabilities.BindlessLimits.MaxPerStageDescriptorSampledImages = coreLimits.maxPerStageDescriptorSampledImages;
	capabilities.BindlessLimits.MaxDescriptorSetSamplers = coreLimits.maxDescriptorSetSamplers;
	capabilities.BindlessLimits.MaxDescriptorSetSampledImages = coreLimits.maxDescriptorSetSampledImages;
	capabilities.BindlessLimits.MaxPerStageDescriptorUpdateAfterBindSamplers = indexingLimits.maxPerStageDescriptorUpdateAfterBindSamplers;
	capabilities.BindlessLimits.MaxPerStageDescriptorUpdateAfterBindSampledImages = indexingLimits.maxPerStageDescriptorUpdateAfterBindSampledImages;
	capabilities.BindlessLimits.MaxDescriptorSetUpdateAfterBindSamplers = indexingLimits.maxDescriptorSetUpdateAfterBindSamplers;
	capabilities.BindlessLimits.MaxDescriptorSetUpdateAfterBindSampledImages = indexingLimits.maxDescriptorSetUpdateAfterBindSampledImages;
	capabilities.BindlessLimits.MaxPerStageUpdateAfterBindResources = indexingLimits.maxPerStageUpdateAfterBindResources;
	capabilities.BindlessLimits.MaxUpdateAfterBindDescriptorsInAllPools = indexingLimits.maxUpdateAfterBindDescriptorsInAllPools;

	capabilities.RayQueryExtension = device->SupportsExtension(VK_KHR_RAY_QUERY_EXTENSION_NAME);
	capabilities.RayQueryFeature = device->PhysicalDevice.Features.RayQuery.rayQuery;
	capabilities.AccelerationStructureExtension = device->SupportsExtension(VK_KHR_ACCELERATION_STRUCTURE_EXTENSION_NAME);
	capabilities.AccelerationStructureFeature = device->PhysicalDevice.Features.AccelerationStructure.accelerationStructure;
	capabilities.GraphicsPipelineLibraryExtension = device->SupportsExtension(VK_EXT_GRAPHICS_PIPELINE_LIBRARY_EXTENSION_NAME);
	capabilities.GraphicsPipelineLibraryFeature = device->EnabledFeatures.GraphicsPipelineLibrary.graphicsPipelineLibrary;
	capabilities.ShaderClipDistance = device->PhysicalDevice.Features.Features.shaderClipDistance;

	capabilities.SceneSampleCounts = coreLimits.sampledImageColorSampleCounts &
		coreLimits.sampledImageDepthSampleCounts & coreLimits.sampledImageStencilSampleCounts;
	capabilities.IntelSamplerQuirk = VkClassifyIntelSamplerQuirk(
		properties.vendorID, properties.deviceID, properties.driverVersion);
	capabilities.AmdRayQueryDriverQuirk = VkHasAmdRayQueryDriverQuirk(
		properties.vendorID, properties.driverVersion);
	return capabilities;
}

VulkanRenderDevice::VulkanRenderDevice(void *hMonitor, bool fullscreen, std::shared_ptr<VulkanInstance> instance, std::shared_ptr<VulkanSurface> surface) : SystemBaseFrameBuffer(hMonitor, fullscreen)
{
	VulkanDeviceBuilder builder;
	builder.OptionalRayQuery();
	if (CfxTrace::Enabled()) builder.OptionalExtension(VK_NV_DEVICE_DIAGNOSTIC_CHECKPOINTS_EXTENSION_NAME);
	if (CfxAddress::Enabled() && instance->AddressBindingMessengerActive)
		builder.OptionalExtension(VK_EXT_DEVICE_ADDRESS_BINDING_REPORT_EXTENSION_NAME);
	builder.RequireExtension(VK_EXT_DESCRIPTOR_INDEXING_EXTENSION_NAME);
	if (surface)
	{
		HasSurface = true;
		builder.Surface(surface);
	}
	builder.SelectDevice(vk_device);
	SupportedDevices = builder.FindDevices(instance);
	mDevice = builder.Create(instance);
	if (CfxTrace::Enabled())
	{
		CfxTrace::Mark("capability", mDevice->SupportsExtension(VK_NV_DEVICE_DIAGNOSTIC_CHECKPOINTS_EXTENSION_NAME) ? "nv-checkpoints-enabled" : "nv-checkpoints-unavailable");
		CfxTrace::Mark("capability", mDevice->SupportsExtension(VK_EXT_DEVICE_FAULT_EXTENSION_NAME) && mDevice->EnabledFeatures.Fault.deviceFault ? "ext-device-fault-enabled" : "ext-device-fault-unavailable");
		if (CfxAddress::State().requested)
			CfxTrace::Mark("capability", mDevice->EnabledFeatures.AddressBinding.reportAddressBinding ? "address-binding-report-enabled" : "address-binding-report-unavailable");
	}
	mCapabilities = VulkanCapabilities::FromDevice(mDevice.get());
	mCapabilities.DepthD24S8 = SupportsRenderTargetFormat(VK_FORMAT_D24_UNORM_S8_UINT);
	mCapabilities.DepthD32S8 = SupportsRenderTargetFormat(VK_FORMAT_D32_SFLOAT_S8_UINT);
	mCapabilities.NormalA2R10G10B10 = SupportsNormalGBufferFormat(VK_FORMAT_A2R10G10B10_UNORM_PACK32);
	mCapabilities.NormalR8G8B8A8 = SupportsNormalGBufferFormat(VK_FORMAT_R8G8B8A8_UNORM);
	mCapabilities.DepthStencilFormat = VkSelectDepthStencilFormat(mCapabilities.DepthD24S8, mCapabilities.DepthD32S8);
	mCapabilities.NormalFormat = VkSelectNormalGBufferFormat(mCapabilities.NormalA2R10G10B10, mCapabilities.NormalR8G8B8A8);

	if (!mCapabilities.SupportsRequiredBindlessContract())
	{
		I_FatalError("This GPU does not support the required Vulkan descriptor-indexing features for bindless sampled images");
	}

	mUseRayQuery = vk_rayquery && mCapabilities.SupportsRayQuery();

	if (vk_amd_driver_check && mCapabilities.AmdRayQueryDriverQuirk)
	{
		// Inherited AMDVLK workaround: specialization-constant/ray-query shaders can stall the first frame
		// long enough to lose the device on Windows or freeze Linux. PF-007 only centralizes the driver
		// classification; the existing user override and legacy-path fallback remain unchanged.
		if (mUseRayQuery)
		{
			Printf("AMD driver detected. Disabling RT cores. You can force RT cores on by setting vk_amd_driver_check to false.\n");
			mUseRayQuery = false;
		}
	}

	CfxTrace::Mark("capability", mUseRayQuery ? "ray-query-enabled" : "ray-query-disabled");
	CfxTrace::Mark("capability", mCapabilities.SupportsGraphicsPipelineLibrary() ? "graphics-pipeline-library-supported" : "graphics-pipeline-library-unavailable");
	mShaderCache = std::make_unique<VkShaderCache>(this);
}

VulkanRenderDevice::~VulkanRenderDevice()
{
	if (!CfxTrace::Enabled() || !CfxTrace::State().deviceLost.load())
		vkDeviceWaitIdle(mDevice->device); // inherited normal teardown; lost diagnostic device must not wait again

	delete mSkyData;
	delete mShadowMap;
	mShadowPuppetDepth.reset();
	mShadowPuppetStencil.reset();

	if (mDescriptorSetManager)
		mDescriptorSetManager->Deinit();
	if (mCommands)
		mCommands->DeleteFrameObjects();
	if (mTextureManager)
		mTextureManager->Deinit();
	if (mBufferManager)
		mBufferManager->Deinit();
	if (mShaderManager)
		mShaderManager->Deinit();
	if (mCommands)
		mCommands->DeleteFrameObjects();
}

void VulkanRenderDevice::PrecacheFlashlightShadowPipelines()
{
	if (!mShadowPuppetDepth)
		mShadowPuppetDepth = std::make_unique<VkShadowPuppetDepth>(this);
	mShadowPuppetDepth->PreparePipeline();
	if (SupportsShadowPuppetStencil())
		mShadowPuppetStencil->PreparePipelines();
}

bool VulkanRenderDevice::SupportsShadowPuppetStencil()
{
	if (!mShadowPuppetStencil)
		mShadowPuppetStencil = std::make_unique<VkShadowPuppetStencil>(this);
	return mShadowPuppetStencil->Supported();
}

int VulkanRenderDevice::RenderShadowPuppetStencil(const HWShadowPuppetMesh& mesh, FVector3 origin,
	const VSMatrix& cameraProjection, const IntRect& viewport)
{
	return mShadowPuppetStencil->Render(mesh, origin, cameraProjection, viewport);
}

int VulkanRenderDevice::RenderShadowPuppetDepth(const TArray<FVector3>& triangles, const VSMatrix& lightProjection)
{
	if (!mShadowPuppetDepth)
		mShadowPuppetDepth = std::make_unique<VkShadowPuppetDepth>(this);
	return mShadowPuppetDepth->Render(triangles, lightProjection);
}

bool VulkanRenderDevice::SupportsRenderTargetFormat(VkFormat format)
{
	if (ImageBuilder()
		.Size(1024, 1024)
		.Format(format)
		.Usage(VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT)
		.IsFormatSupported(GetDevice()))
		return true;

	return ImageBuilder()
		.Size(1024, 1024)
		.Format(format)
		.Samples(VK_SAMPLE_COUNT_4_BIT)
		.Usage(VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT)
		.IsFormatSupported(GetDevice());
}

bool VulkanRenderDevice::SupportsNormalGBufferFormat(VkFormat format)
{
	if (ImageBuilder()
		.Size(1024, 1024)
		.Format(format)
		.Usage(VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT)
		.IsFormatSupported(GetDevice()))
		return true;

	return ImageBuilder()
		.Size(1024, 1024)
		.Format(format)
		.Samples(VK_SAMPLE_COUNT_4_BIT)
		.Usage(VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT)
		.IsFormatSupported(GetDevice());
}

void VulkanRenderDevice::InitializeState()
{
	static bool first = true;
	if (first)
	{
		PrintStartupLog();
		first = false;
	}

	// Use the same names here as OpenGL returns.
	switch (mDevice->PhysicalDevice.Properties.Properties.vendorID)
	{
	case 0x1002: vendorstring = "ATI Technologies Inc.";     break;
	case 0x10DE: vendorstring = "NVIDIA Corporation";  break;
	case 0x8086: vendorstring = "Intel";   break;
	default:     vendorstring = "Unknown"; break;
	}

	uniformblockalignment = (unsigned int)mDevice->PhysicalDevice.Properties.Properties.limits.minUniformBufferOffsetAlignment;
	maxuniformblock = std::min(mDevice->PhysicalDevice.Properties.Properties.limits.maxUniformBufferRange, (uint32_t)1024 * 1024);

	DepthStencilFormat = mCapabilities.DepthStencilFormat;
	if (DepthStencilFormat == VK_FORMAT_UNDEFINED)
		I_FatalError("This device does not support any of the required depth stencil image formats.");

	NormalFormat = mCapabilities.NormalFormat;
	if (NormalFormat == VK_FORMAT_UNDEFINED)
		I_FatalError("This device does not support any of the required normal buffer image formats.");

	NullMesh.reset(new LevelMesh());
	levelMesh = NullMesh.get();

	mCommands.reset(new VkCommandBufferManager(this));

	mSamplerManager.reset(new VkSamplerManager(this));
	mTextureManager.reset(new VkTextureManager(this));
	mFramebufferManager.reset(new VkFramebufferManager(this));
	mBufferManager.reset(new VkBufferManager(this));

	mScreenBuffers.reset(new VkRenderBuffers(this));
	mSaveBuffers.reset(new VkRenderBuffers(this));
	mActiveRenderBuffers = mScreenBuffers.get();

	mPostprocess.reset(new VkPostprocess(this));
	mDescriptorSetManager.reset(new VkDescriptorSetManager(this));
	mShaderManager.reset(new VkShaderManager(this));
	mRenderPassManager.reset(new VkRenderPassManager(this));
	mLevelMesh.reset(new VkLevelMesh(this));
	mLightmapper.reset(new VkLightmapper(this));
	mLightprober.reset(new VkLightprober(this));

	mBufferManager->Init();

	mSkyData = new FSkyVertexBuffer(this);
	mShadowMap = new ShadowMap(this);

	mDescriptorSetManager->Init();

	mRenderState = std::make_unique<VkRenderState>(this);
}

void VulkanRenderDevice::Update()
{
	CfxTrace::Stage cfxStage("present");
	twoD.Reset();
	Flush3D.Reset();

	Flush3D.Clock();

	GetPostprocess()->SetActiveRenderTarget();

	Draw2D();
	twod->Clear();

	mRenderState->EndRenderPass();
	mRenderState->EndFrame();

	Flush3D.Unclock();

	mCommands->WaitForCommands(true);
	mCommands->UpdateGpuStats();

	SystemBaseFrameBuffer::Update();
}

bool VulkanRenderDevice::CompileNextShader()
{
	return mShaderManager->CompileNextShader();
}

void VulkanRenderDevice::RenderTextureView(FCanvasTexture* tex, std::function<void(IntRect &)> renderFunc)
{
	auto BaseLayer = static_cast<VkHardwareTexture*>(tex->GetHardwareTexture(0, 0));

	VkTextureImage *image = BaseLayer->GetImage(tex, 0, 0);
	VkTextureImage *depthStencil = BaseLayer->GetDepthStencil(tex);

	mRenderState->EndRenderPass();

	VkImageTransition()
		.AddImage(image, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, false)
		.Execute(mCommands->GetDrawCommands());

	mRenderState->SetRenderTarget(image, depthStencil->View.get(), image->Image->width, image->Image->height, VK_FORMAT_R8G8B8A8_UNORM, VK_SAMPLE_COUNT_1_BIT);

	IntRect bounds;
	bounds.left = bounds.top = 0;
	bounds.width = min(tex->GetWidth(), image->Image->width);
	bounds.height = min(tex->GetHeight(), image->Image->height);

	renderFunc(bounds);

	mRenderState->EndRenderPass();

	VkImageTransition()
		.AddImage(image, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL, false)
		.Execute(mCommands->GetDrawCommands());

	mRenderState->SetRenderTarget(&GetBuffers()->SceneColor, GetBuffers()->SceneDepthStencil.View.get(), GetBuffers()->GetWidth(), GetBuffers()->GetHeight(), VK_FORMAT_R16G16B16A16_SFLOAT, GetBuffers()->GetSceneSamples());

	Pf020VulkanDiagnostics::CameraCompleted(this, image, tex);
	tex->SetUpdated(true);
}

void VulkanRenderDevice::ResetLightProbes()
{
	mTextureManager->ResetLightProbes();
}

void VulkanRenderDevice::RenderLightProbe(int probeIndex, std::function<void(IntRect& bounds, int side)> renderFunc)
{
	mLightprober->RenderEnvironmentMap(std::move(renderFunc));
	mLightprober->GenerateIrradianceMap(probeIndex);
	mLightprober->GeneratePrefilterMap(probeIndex);
}

void VulkanRenderDevice::EndLightProbePass()
{
	mLightprober->EndLightProbePass();
}

void VulkanRenderDevice::DownloadLightProbes(int probeCount, TArrayView<uint16_t> irradianceMaps, TArrayView<uint16_t> prefilterMaps)
{
	mTextureManager->DownloadIrradiancemap(probeCount, irradianceMaps);
	mTextureManager->DownloadPrefiltermap(probeCount, prefilterMaps);
}

void VulkanRenderDevice::UploadLightProbes(int probeCount, const TArray<uint16_t>& irradianceMaps, const TArray<uint16_t>& prefilterMaps)
{
	mTextureManager->UploadIrradiancemap(probeCount, irradianceMaps);
	mTextureManager->UploadPrefiltermap(probeCount, prefilterMaps);
}

void VulkanRenderDevice::PostProcessScene(bool swscene, int fixedcm, float flash, bool palettePostprocess, const std::function<void()> &afterBloomDrawEndScene2D)
{
	CfxTrace::Stage cfxStage("postprocess");
	if (!swscene) mPostprocess->BlitSceneToPostprocess(); // Copy the resulting scene to the current post process texture
	mPostprocess->PostProcessScene(fixedcm, flash, palettePostprocess, afterBloomDrawEndScene2D);
}

const char* VulkanRenderDevice::DeviceName() const
{
	const auto &props = mDevice->PhysicalDevice.Properties;
	return props.Properties.deviceName;
}

void VulkanRenderDevice::SetVSync(bool vsync)
{
	mVSync = vsync;
}

void VulkanRenderDevice::PrecacheMaterial(FMaterial *mat, int translation)
{
	if (mat->Source()->GetUseType() == ETextureType::SWCanvas) return;
	if (mapPipelinePreloadPending && (mat->Source()->GetUseType() == ETextureType::Sprite || (mat->GetScaleFlags() & CTF_Expand)))
		mapSpriteShaders.emplace(mat->GetShaderIndex(), mat->GetLayerFlags());

	MaterialLayerInfo* layer;

	auto systex = static_cast<VkHardwareTexture*>(mat->GetLayer(0, translation, &layer));
	systex->GetImage(layer->layerTexture, translation, layer->scaleFlags);

	int numLayers = mat->NumLayers();
	for (int i = 1; i < numLayers; i++)
	{
		auto syslayer = static_cast<VkHardwareTexture*>(mat->GetLayer(i, 0, &layer));
		syslayer->GetImage(layer->layerTexture, 0, layer->scaleFlags);
	}
}

IHardwareTexture *VulkanRenderDevice::CreateHardwareTexture(int numchannels)
{
	return new VkHardwareTexture(this, numchannels);
}

FMaterial* VulkanRenderDevice::CreateMaterial(FGameTexture* tex, int scaleflags)
{
	return new VkMaterial(this, tex, scaleflags);
}

IBuffer*VulkanRenderDevice::CreateVertexBuffer(int numBindingPoints, int numAttributes, size_t stride, const FVertexBufferAttribute* attrs)
{
	return GetBufferManager()->CreateVertexBuffer(numBindingPoints, numAttributes, stride, attrs);
}

IBuffer*VulkanRenderDevice::CreateIndexBuffer()
{
	return GetBufferManager()->CreateIndexBuffer();
}

void VulkanRenderDevice::SetTextureFilterMode()
{
	if (mSamplerManager)
	{
		// Retire material consumers before replacing their samplers. Republish
		// fixed slots only afterwards so they cannot retain retired HW samplers.
		mDescriptorSetManager->ResetHWTextureSets();
		mSamplerManager->ResetHWSamplers();
		mDescriptorSetManager->UpdateFixedTextureDescriptors();
	}
}

void VulkanRenderDevice::StartPrecaching()
{
	// Destroy material descriptors; the probe view/pair owners remain live.
	mDescriptorSetManager->ResetHWTextureSets();
	mDescriptorSetManager->UpdateFixedTextureDescriptors();
}

void VulkanRenderDevice::InvalidateMaterialBindings()
{
	// SetLevelMesh updates this logical owner immediately. The Vulkan mirror can
	// still refer to the previous map until BeginFrame, so do not invalidate it.
	if (levelMesh)
		levelMesh->InvalidateMaterialBindings();
}

void VulkanRenderDevice::BlurScene(float amount)
{
	if (mPostprocess)
		mPostprocess->BlurScene(amount);
}

void VulkanRenderDevice::UpdatePalette()
{
	if (mPostprocess)
		mPostprocess->ClearTonemapPalette();

	mTextureManager->SetGamePalette();
}

FTexture *VulkanRenderDevice::WipeStartScreen()
{
	SetViewportRects(nullptr);

	auto tex = new FWrapperTexture(mScreenViewport.width, mScreenViewport.height, 1);
	auto systex = static_cast<VkHardwareTexture*>(tex->GetSystemTexture());

	systex->CreateWipeTexture(mScreenViewport.width, mScreenViewport.height, "WipeStartScreen");

	return tex;
}

FTexture *VulkanRenderDevice::WipeEndScreen()
{
	GetPostprocess()->SetActiveRenderTarget();
	Draw2D();
	twod->Clear();

	auto tex = new FWrapperTexture(mScreenViewport.width, mScreenViewport.height, 1);
	auto systex = static_cast<VkHardwareTexture*>(tex->GetSystemTexture());

	systex->CreateWipeTexture(mScreenViewport.width, mScreenViewport.height, "WipeEndScreen");

	return tex;
}

void VulkanRenderDevice::CopyScreenToBuffer(int w, int h, uint8_t *data)
{
	VkTextureImage image;

	// Convert from rgba16f to rgba8 using the GPU:
	image.Image = ImageBuilder()
		.Format(VK_FORMAT_R8G8B8A8_UNORM)
		.Usage(VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT)
		.Size(w, h)
		.DebugName("CopyScreenToBuffer")
		.Create(mDevice.get());

	GetPostprocess()->BlitCurrentToImage(&image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);

	// Staging buffer for download
	auto staging = BufferBuilder()
		.Size(w * h * 4)
		.Usage(VK_BUFFER_USAGE_TRANSFER_DST_BIT, VMA_MEMORY_USAGE_GPU_TO_CPU)
		.DebugName("CopyScreenToBuffer")
		.Create(mDevice.get());

	// Copy from image to buffer
	VkBufferImageCopy region = {};
	region.imageExtent.width = w;
	region.imageExtent.height = h;
	region.imageExtent.depth = 1;
	region.imageSubresource.layerCount = 1;
	region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
	mCommands->GetDrawCommands()->copyImageToBuffer(image.Image->image, image.Layout, staging->buffer, 1, &region);

	// Submit command buffers and wait for device to finish the work
	mCommands->WaitForCommands(false);

	// Map and convert from rgba8 to rgb8
	uint8_t *dest = (uint8_t*)data;
	uint8_t *pixels = (uint8_t*)staging->Map(0, w * h * 4);
	int dindex = 0;
	for (int y = 0; y < h; y++)
	{
		int sindex = (h - y - 1) * w * 4;
		for (int x = 0; x < w; x++)
		{
			dest[dindex] = pixels[sindex];
			dest[dindex + 1] = pixels[sindex + 1];
			dest[dindex + 2] = pixels[sindex + 2];
			dindex += 3;
			sindex += 4;
		}
	}
	staging->Unmap();
}

void VulkanRenderDevice::SetActiveRenderTarget()
{
	mPostprocess->SetActiveRenderTarget();
}

TArray<uint8_t> VulkanRenderDevice::GetScreenshotBuffer(int &pitch, ESSType &color_type, float &gamma)
{
	int w = SCREENWIDTH;
	int h = SCREENHEIGHT;

	IntRect box;
	box.left = 0;
	box.top = 0;
	box.width = w;
	box.height = h;
	mPostprocess->DrawPresentTexture(box, true, true);

	TArray<uint8_t> ScreenshotBuffer(w * h * 3, true);
	CopyScreenToBuffer(w, h, ScreenshotBuffer.Data());
	Pf020VulkanDiagnostics::ScreenshotCompleted(w, h, ScreenshotBuffer.Data(), ScreenshotBuffer.Size());

	pitch = w * 3;
	color_type = SS_RGB;
	gamma = 1.0f;
	return ScreenshotBuffer;
}

void VulkanRenderDevice::BeginFrame()
{
	CfxTrace::NextFrame();
	CfxTrace::Stage cfxStage("resource-mesh-upload");
	vmaSetCurrentFrameIndex(mDevice->allocator, 0);
	membudgets.Resize(mDevice->PhysicalDevice.Properties.Memory.memoryHeapCount);
	vmaGetHeapBudgets(mDevice->allocator, membudgets.data());
	if (memheapnames.size() == 0)
	{
		memheapnames.Resize(mDevice->PhysicalDevice.Properties.Memory.memoryHeapCount);
		for (unsigned int i = 0; i < memheapnames.Size(); i++)
		{
			bool deviceLocal = !!(mDevice->PhysicalDevice.Properties.Memory.memoryHeaps[i].flags & VK_MEMORY_HEAP_DEVICE_LOCAL_BIT);
			memheapnames[i] = deviceLocal ? " (device local)" : "";
		}
	}
	hwtexturecount = mTextureManager->GetHWTextureCount();

	FrameTileUpdates = 0;
	FrameTileCompletions = 0;

	GetRenderPassManager()->ProcessMainThreadTasks();
	GetTextureManager()->ProcessMainThreadTasks();

	if (levelMeshChanged)
	{
		levelMeshChanged = false;
		mLevelMesh->SetLevelMesh(levelMesh);
		GetTextureManager()->CreateLightmap(levelMesh->Lightmap.TextureSize, levelMesh->Lightmap.TextureCount, levelMesh->Lightmap.TextureData);
		// CreateLightmap takes a const reference. Consume successful initial upload
		// input explicitly; a later refresh/repack must not replay old atlas pixels.
		levelMesh->Lightmap.TextureData.Clear();
		GetLightmapper()->SetLevelMesh(levelMesh);
	}

	SetViewportRects(nullptr);
	mCommands->BeginFrame();
	mLevelMesh->BeginFrame();
	mTextureManager->BeginFrame(levelMesh->Lightmap.TextureSize, levelMesh->Lightmap.TextureCount);
	mScreenBuffers->BeginFrame(screen->mScreenViewport.width, screen->mScreenViewport.height, screen->mSceneViewport.width, screen->mSceneViewport.height);
	mSaveBuffers->BeginFrame(SAVEPICWIDTH, SAVEPICHEIGHT, SAVEPICWIDTH, SAVEPICHEIGHT);
	mRenderState->BeginFrame();
	mDescriptorSetManager->BeginFrame();
	mLightmapper->BeginFrame();
	if (mapPipelinePreloadPending)
	{
		mapPipelinePreloadPending = false;
		if (gl_precache) PrecacheMapPipelines();
		mapSpriteShaders.clear();
	}
	if (CfxTrace::Enabled())
	{
		// Retain warmup extents after allocation, before shadow/world draws. The
		// startup Resolution line precedes deferred vid_setsize and cannot name
		// the viewport or framebuffer selected for a later failing world frame.
		char detail[384];
		std::snprintf(detail, sizeof(detail), "client=%dx%d framebuffer=%dx%d screen_viewport=%dx%d scene_viewport=%dx%d screen_buffers=%dx%d scene_buffers=%dx%d shadow_mode=%d ray_query=%d",
			GetClientWidth(), GetClientHeight(), GetWidth(), GetHeight(),
			mScreenViewport.width, mScreenViewport.height, mSceneViewport.width, mSceneViewport.height,
			mScreenBuffers->GetWidth(), mScreenBuffers->GetHeight(), mScreenBuffers->GetSceneWidth(), mScreenBuffers->GetSceneHeight(),
			(int)gl_light_shadows, IsRayQueryEnabled() ? 1 : 0);
		CfxTrace::Mark("frame-extents", detail);
	}
}

void VulkanRenderDevice::Draw2D()
{
	::Draw2D(twod, *RenderState());
}

void VulkanRenderDevice::WaitForCommands(bool finish)
{
	mCommands->WaitForCommands(finish);
}

void VulkanRenderDevice::PrintStartupLog()
{
	const auto &props = mDevice->PhysicalDevice.Properties.Properties;

	FString deviceType;
	switch (props.deviceType)
	{
	case VK_PHYSICAL_DEVICE_TYPE_OTHER: deviceType = "other"; break;
	case VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU: deviceType = "integrated gpu"; break;
	case VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU: deviceType = "discrete gpu"; break;
	case VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU: deviceType = "virtual gpu"; break;
	case VK_PHYSICAL_DEVICE_TYPE_CPU: deviceType = "cpu"; break;
	default: deviceType.Format("%d", (int)props.deviceType); break;
	}

	FString apiVersion, driverVersion;
	apiVersion.Format("%d.%d.%d", VK_VERSION_MAJOR(props.apiVersion), VK_VERSION_MINOR(props.apiVersion), VK_VERSION_PATCH(props.apiVersion));
	driverVersion.Format("%d.%d.%d", VK_VERSION_MAJOR(props.driverVersion), VK_VERSION_MINOR(props.driverVersion), VK_VERSION_PATCH(props.driverVersion));
	vkversion = VK_API_VERSION_MAJOR(props.apiVersion) * 100 + VK_API_VERSION_MINOR(props.apiVersion);

	Printf("Vulkan device: " TEXTCOLOR_ORANGE "%s\n", props.deviceName);
	Printf("Vulkan device type: %s\n", deviceType.GetChars());
	Printf("Vulkan version: %s (api) %s (driver)\n", apiVersion.GetChars(), driverVersion.GetChars());

	Printf(PRINT_LOG, "Vulkan extensions:");
	for (const VkExtensionProperties &p : mDevice->PhysicalDevice.Extensions)
	{
		Printf(PRINT_LOG, " %s", p.extensionName);
	}
	Printf(PRINT_LOG, "\n");

	const auto &limits = props.limits;
	Printf(PRINT_LOG, "Max. texture size: %d\n", limits.maxImageDimension2D);
	Printf(PRINT_LOG, "Max. uniform buffer range: %d\n", limits.maxUniformBufferRange);
	Printf(PRINT_LOG, "Min. uniform buffer offset alignment: %" PRIu64 "\n", limits.minUniformBufferOffsetAlignment);
	Printf(PRINT_LOG, "Vulkan capabilities: bindless=%s ray-query=%s acceleration-structure=%s pipeline-library=%s shader-clip-distance=%s; ray-query-enabled=%s\n",
		mCapabilities.SupportsRequiredBindlessContract() ? "yes" : "no",
		mCapabilities.SupportsRayQuery() ? "yes" : "no",
		mCapabilities.SupportsAccelerationStructure() ? "yes" : "no",
		mCapabilities.SupportsGraphicsPipelineLibrary() ? "yes" : "no",
		mCapabilities.ShaderClipDistance ? "yes" : "no",
		mUseRayQuery ? "yes" : "no");
	Printf(PRINT_LOG, "Vulkan quirks: intel-sampler=%s amd-ray-query-driver=%s\n",
		VkIntelSamplerQuirkName(mCapabilities.IntelSamplerQuirk),
		mCapabilities.AmdRayQueryDriverQuirk ? "yes" : "no");
	Printf(PRINT_LOG, "Vulkan scene sample counts: 0x%x\n", (unsigned)mCapabilities.SceneSampleCounts);
	Printf(PRINT_LOG, "Bindless descriptor limits: stage-samplers=%u stage-images=%u set-samplers=%u set-images=%u uab-stage-samplers=%u uab-stage-images=%u uab-set-samplers=%u uab-set-images=%u uab-stage-resources=%u uab-pool=%u\n",
		mCapabilities.BindlessLimits.MaxPerStageDescriptorSamplers,
		mCapabilities.BindlessLimits.MaxPerStageDescriptorSampledImages,
		mCapabilities.BindlessLimits.MaxDescriptorSetSamplers,
		mCapabilities.BindlessLimits.MaxDescriptorSetSampledImages,
		mCapabilities.BindlessLimits.MaxPerStageDescriptorUpdateAfterBindSamplers,
		mCapabilities.BindlessLimits.MaxPerStageDescriptorUpdateAfterBindSampledImages,
		mCapabilities.BindlessLimits.MaxDescriptorSetUpdateAfterBindSamplers,
		mCapabilities.BindlessLimits.MaxDescriptorSetUpdateAfterBindSampledImages,
		mCapabilities.BindlessLimits.MaxPerStageUpdateAfterBindResources,
		mCapabilities.BindlessLimits.MaxUpdateAfterBindDescriptorsInAllPools);
	Printf(PRINT_LOG, "Vulkan render-target formats: d24s8=%s d32s8=%s depth-selected=%d a2r10g10b10=%s rgba8=%s normal-selected=%d\n",
		mCapabilities.DepthD24S8 ? "yes" : "no",
		mCapabilities.DepthD32S8 ? "yes" : "no",
		(int)mCapabilities.DepthStencilFormat,
		mCapabilities.NormalA2R10G10B10 ? "yes" : "no",
		mCapabilities.NormalR8G8B8A8 ? "yes" : "no",
		(int)mCapabilities.NormalFormat);
}

void VulkanRenderDevice::SetLevelMesh(LevelMesh* mesh)
{
	CfxTrace::Stage cfxStage("startup-map-preparation");
	if (mesh != levelMesh)
	{
		mapPipelinePreloadPending = mesh != nullptr;
		mapSpriteShaders.clear();
	}
	if (!mesh) // Vulkan must have a mesh for its data structures in shaders to remain sane
	{
		NullMesh.reset(new LevelMesh()); // we must have a completely new mesh here as the upload ranges needs to reset as well
		mesh = NullMesh.get();
	}
	levelMesh = mesh;
	levelMeshChanged = true;
}

void VulkanRenderDevice::UpdateLightmaps(const TArray<LightmapTile*>& tiles)
{
	FrameTileUpdates += (int)tiles.size();

	// Raytrace is synchronous with respect to the CPU dirty/completion contract:
	// CopyResult clears these flags only after the current atlas copy and final
	// shader-read barrier have been recorded. Count only real dirty->clean
	// transitions, not merely tiles submitted to the lightmapper.
	std::vector<uint8_t> wasDirty;
	wasDirty.reserve(tiles.Size());
	for (auto* tile : tiles)
		wasDirty.push_back(tile && (tile->NeedsInitialBake || tile->GeometryUpdate || tile->ReceivedNewLight));

	GetLightmapper()->Raytrace(tiles);

	for (unsigned int i = 0; i < tiles.Size(); ++i)
	{
		auto* tile = tiles[i];
		if (wasDirty[i] && tile && !tile->NeedsInitialBake && !tile->GeometryUpdate && !tile->ReceivedNewLight)
			FrameTileCompletions++;
	}
}

void VulkanRenderDevice::SetShadowMaps(const TArray<float>& lights, hwrenderer::LevelAABBTree* tree, bool newTree)
{
	CfxTrace::Stage cfxStage("lighting-shadows");
	auto buffers = GetBufferManager();

	buffers->Shadowmap.Lights->SetData(sizeof(float) * lights.Size(), lights.Data(), BufferUsageType::Stream);

	if (newTree)
	{
		buffers->Shadowmap.Nodes->SetData(tree->NodesSize(), tree->Nodes(), BufferUsageType::Static);
		buffers->Shadowmap.Lines->SetData(tree->LinesSize(), tree->Lines(), BufferUsageType::Static);
	}
	else if (tree->Update())
	{
		buffers->Shadowmap.Nodes->SetSubData(tree->DynamicNodesOffset(), tree->DynamicNodesSize(), tree->DynamicNodes());
		buffers->Shadowmap.Lines->SetSubData(tree->DynamicLinesOffset(), tree->DynamicLinesSize(), tree->DynamicLines());
	}

	mPostprocess->UpdateShadowMap();
}

void VulkanRenderDevice::SetSaveBuffers(bool yes)
{
	if (yes) mActiveRenderBuffers = mSaveBuffers.get();
	else mActiveRenderBuffers = mScreenBuffers.get();
}

void VulkanRenderDevice::ImageTransitionScene(bool unknown)
{
	mPostprocess->ImageTransitionScene(unknown);
}

FRenderState* VulkanRenderDevice::RenderState()
{
	return mRenderState.get();
}

void VulkanRenderDevice::UpdateLinearDepthTexture()
{
	mPostprocess->UpdateLinearDepthTexture();
}

void VulkanRenderDevice::AmbientOccludeScene(float m5)
{
	mPostprocess->AmbientOccludeScene(m5);
}

void VulkanRenderDevice::SetSceneRenderTarget(bool useSSAO)
{
	mRenderState->SetRenderTarget(&GetBuffers()->SceneColor, GetBuffers()->SceneDepthStencil.View.get(), GetBuffers()->GetWidth(), GetBuffers()->GetHeight(), VK_FORMAT_R16G16B16A16_SFLOAT, GetBuffers()->GetSceneSamples());
}

void VulkanRenderDevice::DownloadLightmap(int arrayIndex, uint16_t* buffer)
{
	mTextureManager->DownloadLightmap(arrayIndex, buffer);
}

int VulkanRenderDevice::GetBindlessTextureIndex(FMaterial* material, int clampmode, int translation, bool paletteMode)
{
	GlobalShaderAddr addr;
	auto globalshader = GetGlobalShader(material->GetShaderIndex(), nullptr, addr);

	FMaterialState materialState;
	materialState.mMaterial = material;
	materialState.mClampMode = clampmode;
	materialState.mTranslation = translation;
	materialState.mPaletteMode = paletteMode;

	if(addr.type == 1 && *globalshader)
	{ // handle per-map global shaders
		materialState.globalShaderAddr = addr;
		materialState.mOverrideShader = globalshader->shaderindex;
	}

	return static_cast<VkMaterial*>(material)->GetBindlessIndex(materialState);
}

int VulkanRenderDevice::GetBindlessHeightLayerIndex(FMaterial* material, int clampmode, int translation, bool paletteMode)
{
	GlobalShaderAddr addr;
	auto globalshader = GetGlobalShader(material->GetShaderIndex(), nullptr, addr);

	FMaterialState materialState;
	materialState.mMaterial = material;
	materialState.mClampMode = clampmode;
	materialState.mTranslation = translation;
	materialState.mPaletteMode = paletteMode;

	if(addr.type == 1 && *globalshader)
	{ // handle per-map global shaders
		materialState.globalShaderAddr = addr;
		materialState.mOverrideShader = globalshader->shaderindex;
	}

	return static_cast<VkMaterial*>(material)->GetHeightLayerIndex(materialState);
}

int VulkanRenderDevice::GetLevelMeshPipelineID(const MeshApplyData& applyData, const SurfaceUniforms& surfaceUniforms, const FMaterialState& material)
{
	if (levelVertexFormatIndex == -1)
	{
		static const std::vector<FVertexBufferAttribute> format =
		{
			{ 0, VATTR_VERTEX, VFmt_Float4, (int)myoffsetof(FFlatVertex, x) },
			{ 0, VATTR_TEXCOORD, VFmt_Float2, (int)myoffsetof(FFlatVertex, u) },
			{ 0, VATTR_LIGHTMAP, VFmt_Float2, (int)myoffsetof(FFlatVertex, lu) },
			{ 1, VATTR_UNIFORM_INDEXES, VFmt_Int, 0 }
		};
		levelVertexFormatIndex = GetRenderPassManager()->GetVertexFormat({ sizeof(FFlatVertex), sizeof(int32_t) }, format);
	}

	VkPipelineKey pipelineKey;
	pipelineKey.DrawType = DT_Triangles;
	pipelineKey.RenderStyle = applyData.RenderStyle;
	pipelineKey.DepthFunc = applyData.DepthFunc;
	pipelineKey.ShaderKey.VertexFormat = levelVertexFormatIndex;
	if (applyData.SpecialEffect > EFF_NONE)
	{
		pipelineKey.ShaderKey.SpecialEffect = applyData.SpecialEffect;
		pipelineKey.ShaderKey.EffectState = 0;
		pipelineKey.ShaderKey.Layout.AlphaTest = false;
	}
	else
	{
		int effectState = material.mOverrideShader >= 0 ? material.mOverrideShader : (material.mMaterial ? material.mMaterial->GetShaderIndex() : 0);
		pipelineKey.ShaderKey.SpecialEffect = EFF_NONE;
		pipelineKey.ShaderKey.EffectState = applyData.TextureEnabled ? effectState : SHADER_NoTexture;
		if (r_skipmats && pipelineKey.ShaderKey.EffectState >= 3 && pipelineKey.ShaderKey.EffectState <= 4)
			pipelineKey.ShaderKey.EffectState = 0;
		pipelineKey.ShaderKey.Layout.AlphaTest = surfaceUniforms.uAlphaThreshold >= 0.f;
	}

	int tempTM = (material.mMaterial && material.mMaterial->Source()->isHardwareCanvas()) ? TM_OPAQUE : TM_NORMAL;
	int f = applyData.TextureModeFlags;
	if (!applyData.BrightmapEnabled) f &= ~(TEXF_Brightmap | TEXF_Glowmap);
	if (applyData.TextureClamp) f |= TEXF_ClampY;
	int uTextureMode = (applyData.TextureMode == TM_NORMAL && tempTM == TM_OPAQUE ? TM_OPAQUE : applyData.TextureMode) | f;

	pipelineKey.ShaderKey.TextureMode = uTextureMode & 0xffff;
	pipelineKey.ShaderKey.ClampY = (uTextureMode & TEXF_ClampY) != 0;
	pipelineKey.ShaderKey.Brightmap = (uTextureMode & TEXF_Brightmap) != 0;
	pipelineKey.ShaderKey.Detailmap = (uTextureMode & TEXF_Detailmap) != 0;
	pipelineKey.ShaderKey.Glowmap = (uTextureMode & TEXF_Glowmap) != 0;

	// The way GZDoom handles state is just plain insanity!
	int fogset = 0;
	if (applyData.FogEnabled)
	{
		if (applyData.FogEnabled == 2)
		{
			fogset = -3;	// 2D rendering with 'foggy' overlay.
		}
		else if (applyData.FogColor)
		{
			fogset = gl_fogmode;
		}
		else
		{
			fogset = -gl_fogmode;
		}
	}
	pipelineKey.ShaderKey.Simple2D = (fogset == -3);
	pipelineKey.ShaderKey.FogBeforeLights = (fogset > 0);
	pipelineKey.ShaderKey.FogAfterLights = (fogset < 0);
	pipelineKey.ShaderKey.FogRadial = (fogset < -1 || fogset > 1);
	pipelineKey.ShaderKey.SWLightRadial = (gl_fogmode == 2);
	pipelineKey.ShaderKey.SWLightBanded = false; // gl_bandedswlight;

	float lightlevel = surfaceUniforms.uLightLevel;
	if (lightlevel < 0.0)
	{
		pipelineKey.ShaderKey.LightMode = 0; // Default
	}
	else
	{
		/*if (mLightMode == 5)
			pipelineKey.ShaderKey.LightMode = 3; // Build
		else if (mLightMode == 16)
			pipelineKey.ShaderKey.LightMode = 2; // Vanilla
		else*/
			pipelineKey.ShaderKey.LightMode = 1; // Software
	}

	pipelineKey.ShaderKey.Layout.UseLevelMesh = true;

	for (unsigned int i = 0, count = levelMeshPipelineKeys.Size(); i < count; i++)
	{
		if (levelMeshPipelineKeys[i] == pipelineKey)
		{
			return i;
		}
	}

	levelMeshPipelineKeys.Push(pipelineKey);
	return levelMeshPipelineKeys.Size() - 1;
}

const VkPipelineKey& VulkanRenderDevice::GetLevelMeshPipelineKey(int id) const
{
	return levelMeshPipelineKeys[id];
}

static int MapMaterialEffect(int effect)
{
	if (r_skipmats && (effect == SHADER_PBR || effect == SHADER_Specular)) return SHADER_Default;
	return effect;
}

void VulkanRenderDevice::PrecacheMapPipelines()
{
	CfxTrace::Stage trace("map-shader-preload");
	CfxTrace::Mark("map-shader-preload-begin", level.MapName.GetChars());
	Printf(PRINT_LOG, "Preparing Vulkan shaders for %s...\n", level.MapName.GetChars());

	VkRenderPassKey scene;
	scene.DrawBufferFormat = VK_FORMAT_R16G16B16A16_SFLOAT;
	scene.DepthStencil = 1;
	scene.Samples = mScreenBuffers->GetSceneSamples();
	scene.DrawBuffers = 1;
	const auto lightMode = level.info ? getRealLightmode(&level, true) : ELightMode::Doom;
	const int lightShader = lightMode == ELightMode::DoomSoftware ? 2 : lightMode == ELightMode::Build ? 3 :
		lightMode == ELightMode::ZDoomSoftware ? 1 : 0;
	const bool flashlight = PClass::FindClass("SDVKLocalFlashlightBeam") != nullptr;
	const bool emitters = !gl_levelmesh && !gl_raytrace && !gl_ubershaders && !lm_dynlights && (level.flags3 & LEVEL3_STAGEBLAYOUT) && !(level.flags3 & LEVEL3_NOSHADOWMAP);
	const int immediateVertex = GetBufferManager()->GetRSBuffers()->Flatbuffer.VertexFormat;
	std::set<VkPipelineKey> opaque, translucent;

	VkPipelineKey common;
	common.ColorMask = 15;
	common.DepthTest = common.DepthClamp = common.StencilTest = true;
	common.DepthFunc = DF_LEqual;
	common.ShaderKey.SpecialEffect = EFF_NONE;
	common.ShaderKey.VertexFormat = immediateVertex;
	common.ShaderKey.SWLightRadial = gl_fogmode == 2;
	common.ShaderKey.LightMode = lightShader;
	common.ShaderKey.LightBlendMode = level.info ? static_cast<int>(level.info->lightblendmode) : 0;
	common.ShaderKey.LightAttenuationMode = level.info ? static_cast<int>(level.info->lightattenuationmode) : 0;
	auto setShadowMode = [](VkShaderKey& shader, bool receiver)
	{
		shader.UseShadowmap = receiver || gl_light_shadows == 1;
		shader.UseRaytrace = !receiver && gl_light_shadows >= 2;
		shader.Layout.UseRaytracePrecise = !receiver && gl_light_shadows >= 3;
		shader.ShadowmapFilter = std::clamp(int(gl_light_shadow_filter), 0, 15);
	};

	setShadowMode(common.ShaderKey, false);

	// The level mesh records which material shader and texture layers each surface uses.
	// The regular world renderer submits walls as fans and flats as indexed triangles.
	for (const auto& surface : levelMesh->Mesh.Surfaces)
	{
		if (!surface.MeshLocation.NumElements || !surface.Texture || surface.IsSky || surface.PortalIndex) continue;
		const auto& material = GetLevelMeshPipelineKey(surface.PipelineID);
		VkPipelineKey key = common;
		key.DepthWrite = surface.Alpha >= 1.f;
		key.ShaderKey = material.ShaderKey;
		key.RenderStyle = material.RenderStyle;
		key.DrawType = DT_Triangles;
		if (gl_levelmesh)
			key.DepthFunc = material.DepthFunc;
		else
		{
			key.DrawType = surface.Plane.Z == 0 ? DT_TriangleFan : DT_Triangles;
			key.ShaderKey.VertexFormat = immediateVertex;
			key.ShaderKey.Layout.UseLevelMesh = false;
			key.ShaderKey.Layout.AlphaTest = surface.MaskedMapCaster || (surface.Plane.Z == 0 && surface.Texture->isMasked());
			key.ShaderKey.LightMode = material.ShaderKey.LightMode ? lightShader : 0;
			key.ShaderKey.LightBlendMode = common.ShaderKey.LightBlendMode;
			key.ShaderKey.LightAttenuationMode = common.ShaderKey.LightAttenuationMode;
			if (key.DepthWrite) key.RenderStyle = LegacyRenderStyles[STYLE_Source];
		}
		auto addSurface = [&](VkPipelineKey draw, bool receiver)
		{
			setShadowMode(draw.ShaderKey, receiver);
			(draw.DepthWrite ? opaque : translucent).insert(draw);
			if (flashlight && !gl_levelmesh && draw.DepthWrite && !draw.ShaderKey.Layout.AlphaTest)
			{
				draw.ColorMask = 0;
				draw.ShaderKey.EffectState = SHADER_NoTexture;
				opaque.insert(draw);
			}
		};
		// Saved-game thumbnails, portals and the legacy comparison draw outside
		// the main view's emitter lighting, even with that mode enabled in game.
		addSurface(key, false);
		if (emitters && key.DepthWrite) addSurface(key, true);
	}

	// Projectiles can spawn after actor precaching. Restoring a save can also skip
	// texture precaching altogether, so retain the standard sprite material families.
	if (mapSpriteShaders.empty() && flashlight && !r_skipmats)
		mapSpriteShaders.emplace(SHADER_PBR, 0);
	mapSpriteShaders.emplace(SHADER_Default, 0);
	const int spriteLighting = get_gl_spritelight();
	for (const auto& [effect, layers] : mapSpriteShaders)
	{
		VkPipelineKey key = common;
		key.DrawType = DT_TriangleStrip;
		key.RenderStyle = LegacyRenderStyles[STYLE_Normal];
		key.ShaderKey.Layout.AlphaTest = true;
		key.ShaderKey.Layout.ShadeVertex = spriteLighting == 1;
		key.ShaderKey.EffectState = MapMaterialEffect(effect);
		key.ShaderKey.Brightmap = (layers & TEXF_Brightmap) != 0;
		key.ShaderKey.Detailmap = (layers & TEXF_Detailmap) != 0;
		key.ShaderKey.Glowmap = (layers & TEXF_Glowmap) != 0;
		key.ShaderKey.LightNoNormals = spriteLighting > 0;
		key.ShaderKey.UseSpriteCenter = spriteLighting == 1;
		setShadowMode(key.ShaderKey, false);
		translucent.insert(key);
		if (spriteLighting == 2 && emitters)
		{
			auto receiver = key;
			setShadowMode(receiver.ShaderKey, true);
			translucent.insert(receiver);
		}
		if (effect == SHADER_Default)
		{
			key.RenderStyle = LegacyRenderStyles[STYLE_Add];
			translucent.insert(key);
			key.RenderStyle = LegacyRenderStyles[STYLE_ColorAdd];
			translucent.insert(key);
		}
	}

	auto queue = [&](const std::set<VkPipelineKey>& keys, bool gbuffer)
	{
		auto target = scene;
		target.DrawBuffers = gbuffer ? 3 : 1;
		auto pass = GetRenderPassManager()->GetRenderPass(target);
		for (auto key : keys)
		{
			key.ShaderKey.Layout.GBufferPass = gbuffer;
			pass->PrecachePipeline(key);
		}
	};
	try
	{
		queue(opaque, false); // Also used by portals when the main view uses SSAO.
		if (gl_ssao || gl_shownormals) queue(opaque, true);
		queue(translucent, false);
		PrecacheMapAuxiliaryPipelines(common, scene);
		if (flashlight) PrecacheFlashlightShadowPipelines();
	}
	catch (...)
	{
		// Shader compilation and pipeline preparation can fail synchronously
		// after other builds have started using the same shader modules.
		GetRenderPassManager()->FinishPipelinePrecache();
		throw;
	}
	GetRenderPassManager()->FinishPipelinePrecache();
	CfxTrace::Mark("map-shader-preload-end", level.MapName.GetChars());
}

void VulkanRenderDevice::PrecacheMapAuxiliaryPipelines(const VkPipelineKey& common, VkRenderPassKey scene)
{
	auto scenePass = GetRenderPassManager()->GetRenderPass(scene);
	VkPipelineKey decal = common;
	decal.DrawType = DT_TriangleStrip;
	decal.DepthBias = true;
	decal.ShaderKey.ClampY = true;
	decal.ShaderKey.Layout.AlphaTest = true;
	for (auto style : { STYLE_Shaded, STYLE_Translucent })
	{
		decal.RenderStyle = style;
		decal.ShaderKey.TextureMode = style == STYLE_Shaded ? TM_ALPHATEXTURE : TM_NORMAL;
		scenePass->PrecachePipeline(decal);
	}

	// Sky, viewmodel and overlay passes bypass sector lighting.
	VkPipelineKey unlit = common;
	unlit.ShaderKey.LightMode = 0;
	bool hasSky = false;
	for (const auto& surface : levelMesh->Mesh.Surfaces)
	{
		if (surface.IsSky)
		{
			hasSky = true;
			break;
		}
	}
	if (hasSky)
	{
		VkPipelineKey portal = unlit;
		portal.DepthWrite = true;
		portal.ColorMask = 8; // Sky portals restore depth and mark the alpha channel.
		portal.RenderStyle = STYLE_Source;
		portal.ShaderKey.SpecialEffect = EFF_STENCIL;
		portal.ShaderKey.Layout.Simple = true;
		for (auto primitive : { DT_TriangleFan, DT_TriangleStrip })
		{
			portal.DrawType = primitive;
			scenePass->PrecachePipeline(portal);
		}
		VkPipelineKey sky = unlit;
		sky.DepthTest = false;
		sky.RenderStyle = STYLE_Translucent;
		sky.ShaderKey.VertexFormat = static_cast<VkHardwareVertexBuffer*>(mSkyData->mVertexBuffer)->VertexFormat;
		sky.ShaderKey.TextureMode = TM_OPAQUE;
		// A sky drawn first inherits the scene's strict depth function. After
		// the opaque world pass the portal renderer restores less-or-equal.
		auto queueSky = [&](VkPipelineKey key)
		{
			key.DepthFunc = DF_Less;
			scenePass->PrecachePipeline(key);
			key.DepthFunc = DF_LEqual;
			scenePass->PrecachePipeline(key);
		};
		sky.DrawType = DT_TriangleFan;
		sky.ShaderKey.EffectState = SHADER_NoTexture;
		queueSky(sky);
		sky.DrawType = DT_TriangleStrip;
		for (auto id : { level.skytexture1, level.skytexture2 })
		{
			auto *tex = TexMan.GetGameTexture(id);
			if (!tex || !tex->isValid()) continue;
			auto *material = FMaterial::ValidateTexture(tex, 0);
			if (!material) continue;
			sky.ShaderKey.EffectState = MapMaterialEffect(material->GetShaderIndex());
			queueSky(sky);
		}
	}

	// Both viewmodels and the HUD draw onto the single-sample scene resolve.
	scene.Samples = VK_SAMPLE_COUNT_1_BIT;
	auto overlay = GetRenderPassManager()->GetRenderPass(scene);
	VkPipelineKey weapon = unlit;
	weapon.DepthTest = weapon.StencilTest = false;
	weapon.RenderStyle = STYLE_Normal;
	weapon.DrawType = DT_TriangleStrip;
	weapon.ShaderKey.Layout.AlphaTest = true;
	weapon.ShaderKey.UseSpriteCenter = gl_viewmodel_lighting != 0 && get_gl_spritelight() != 0;
	weapon.ShaderKey.LightNoNormals = weapon.ShaderKey.Layout.ShadeVertex = weapon.ShaderKey.UseSpriteCenter && gl_viewmodel_lighting == 1;
	for (const auto& [effect, layers] : mapSpriteShaders)
	{
		weapon.ShaderKey.EffectState = MapMaterialEffect(effect);
		weapon.ShaderKey.Brightmap = (layers & TEXF_Brightmap) != 0;
		weapon.ShaderKey.Glowmap = (layers & TEXF_Glowmap) != 0;
		weapon.ShaderKey.Detailmap = (layers & TEXF_Detailmap) != 0;
		overlay->PrecachePipeline(weapon);
	}
	VkPipelineKey hud = unlit;
	hud.DepthTest = hud.StencilTest = false;
	hud.DrawType = DT_Triangles;
	hud.ShaderKey.Layout.AlphaTest = true;
	hud.ShaderKey.Simple2D = hud.ShaderKey.FogAfterLights = hud.ShaderKey.FogRadial = true;
	F2DVertexBuffer hudVertices;
	hud.ShaderKey.VertexFormat = static_cast<VkHardwareVertexBuffer*>(hudVertices.GetBufferObjects().first)->VertexFormat;
	for (auto style : { STYLE_Normal, STYLE_Translucent, STYLE_Shaded })
	{
		hud.RenderStyle = style;
		hud.ShaderKey.TextureMode = style == STYLE_Shaded ? TM_ALPHATEXTURE : TM_NORMAL;
		hud.ShaderKey.EffectState = SHADER_Default;
		overlay->PrecachePipeline(hud);
	}
	hud.ShaderKey.TextureMode = TM_NORMAL;
	hud.RenderStyle = STYLE_Normal;
	for (const auto& material : mapSpriteShaders)
	{
		hud.ShaderKey.EffectState = MapMaterialEffect(material.first);
		overlay->PrecachePipeline(hud);
	}
	hud.RenderStyle = STYLE_Translucent;
	hud.ShaderKey.EffectState = SHADER_NoTexture;
	overlay->PrecachePipeline(hud);

	// A level transition draws the saved screen as an opaque 2D texture.
	hud.RenderStyle = STYLE_Normal;
	hud.ShaderKey.EffectState = SHADER_Default;
	hud.ShaderKey.TextureMode = TM_OPAQUE;
	hud.ShaderKey.LightMode = common.ShaderKey.LightMode;
	overlay->PrecachePipeline(hud);
}
