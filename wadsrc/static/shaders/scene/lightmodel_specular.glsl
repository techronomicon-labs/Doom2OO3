vec2 lightAttenuation(DynLightInfo light, vec3 normal, vec3 viewdir, float glossiness, float specularLevel)
{
	if (!UsePackedLight(light))
		return vec2(0.0);
	bool directional = (light.flags & LIGHTINFO_STAGE_B_DIRECTIONAL) != 0;
	float lightdistance = distance(light.pos.xyz, SDVK_LIGHTING_POSITION);
	if (light.radius < lightdistance)
		return vec2(0.0); // Early out lights touching surface but not this fragment

	float attenuation = PackedLightFalloff(light, lightdistance);

	if ((light.flags & LIGHTINFO_SPOT) != 0)
	{
		attenuation *= spotLightAttenuation(light.pos.xyz, light.spotDir.xyz, light.spotInnerAngle, light.spotOuterAngle);
	}

	vec3 lightdir = directional ? light.spotDir : normalize(light.pos.xyz - SDVK_LIGHTING_POSITION);

	if (directional || (light.flags & LIGHTINFO_ATTENUATED) != 0)
	{
		attenuation *= clamp(dot(normal, lightdir), 0.0, 1.0);
	}

	if (attenuation > 0.0) // Skip shadow map test if possible
	{
		// The far-away sunlight proxy bypasses local-light shadow attenuation.
		if(light.radius < LIGHT_COMPAT_SUN_ATTENUATION_RADIUS && (light.flags & LIGHTINFO_SHADOWMAPPED) != 0)
		{
			attenuation *= shadowAttenuation(light.pos.xyz, light.shadowIndex, light.softShadowRadius, light.flags);
		}
		attenuation *= ShadowPuppetVisibility(light, pixelpos.xyz, ivec2(gl_FragCoord.xy));
	}

	if (attenuation <= 0.0)
		return vec2(0.0);

	vec3 halfdir = normalize(viewdir + lightdir);
	float specAngle = clamp(dot(halfdir, normal), 0.0f, 1.0f);
	float phExp = glossiness * 4.0f;
	return vec2(attenuation, attenuation * specularLevel * pow(specAngle, phExp));
}

vec3 ProcessMaterialLight(Material material, vec3 color, float sunlightAttenuation)
{
	bool stageB = STAGE_B_WORLD_LIGHTING;
	vec4 dynlight = stageB ? vec4(0.0) : uDynLightColor;
	vec4 specular = vec4(0.0, 0.0, 0.0, 1.0);

	vec3 normal = material.Normal;
	vec3 viewdir = normalize(uCameraPos.xyz - SDVK_LIGHTING_POSITION);

	if (sunlightAttenuation > 0.0)
	{
		sunlightAttenuation *= clamp(dot(normal, SunDir), 0.0, 1.0);
		vec3 color = SunColor.rgb * SunIntensity * sunlightAttenuation;
		vec3 halfdir = normalize(viewdir + SunDir);
		float specAngle = clamp(dot(halfdir, normal), 0.0f, 1.0f);
		float phExp = material.Glossiness * 4.0f;
		dynlight.rgb += color;
		specular.rgb += color * material.SpecularLevel * pow(specAngle, phExp);
	}

#ifdef UBERSHADER
	if (stageB)
#endif
	if (uLightIndex >= 0)
	{
		ivec4 lightRange = getLightRange();
		if (lightRange.z > lightRange.x)
		{
			// modulated lights
			for(int i=lightRange.x; i<lightRange.y; i++)
			{
				vec3 lightcolor = getLights()[i].color.rgb;
				vec2 attenuation = lightAttenuation(getLights()[i], normal, viewdir, material.Glossiness, material.SpecularLevel);
				dynlight.rgb += lightcolor.rgb * attenuation.x;
				specular.rgb += lightcolor.rgb * attenuation.y;
			}

			// subtractive lights
			for(int i=lightRange.y; i<lightRange.z; i++)
			{
				vec3 lightcolor = getLights()[i].color.rgb;
				vec2 attenuation = lightAttenuation(getLights()[i], normal, viewdir, material.Glossiness, material.SpecularLevel);
				dynlight.rgb -= lightcolor.rgb * attenuation.x;
				specular.rgb -= lightcolor.rgb * attenuation.y;
			}
		}
	}
	
	if (LIGHT_BLEND_CLAMPED)
	{
		dynlight.rgb = clamp(color + desaturate(dynlight).rgb, 0.0, 1.4);
		specular.rgb = clamp(desaturate(specular).rgb, 0.0, 1.4);
	}
	else if (LIGHT_BLEND_COLORED_CLAMP)
	{
		dynlight.rgb = color + desaturate(dynlight).rgb;
		specular.rgb = desaturate(specular).rgb;

		dynlight.rgb = ((dynlight.rgb / max(max(max(dynlight.r, dynlight.g), dynlight.b), 1.4) * 1.4));
		specular.rgb = ((specular.rgb / max(max(max(specular.r, specular.g), specular.b), 1.4) * 1.4));
	}
	else
	{
		dynlight.rgb = color + desaturate(dynlight).rgb;
		specular.rgb = desaturate(specular).rgb;
	}

	vec3 frag = material.Base.rgb * dynlight.rgb + material.Specular * specular.rgb;

#ifdef UBERSHADER
	if (stageB)
#endif
	if (uLightIndex >= 0)
	{
		ivec4 lightRange = getLightRange();
		if (lightRange.w > lightRange.z)
		{
			vec4 addlight = vec4(0.0,0.0,0.0,0.0);

			// additive lights
			for(int i=lightRange.z; i<lightRange.w; i++)
			{
				vec3 lightcolor = getLights()[i].color.rgb;
				vec2 attenuation = lightAttenuation(getLights()[i], normal, viewdir, material.Glossiness, material.SpecularLevel);
				addlight.rgb += lightcolor.rgb * attenuation.x;
			}

			frag = clamp(frag + desaturate(addlight).rgb, 0.0, 1.0);
		}
	}

	return frag;
}

vec3 ProcessSWLight(Material material, float sunlightAttenuation)
{
	return vec3(0.0);
}
