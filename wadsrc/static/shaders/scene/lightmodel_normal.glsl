
#ifndef SIMPLE3D
	vec3 lightContribution(DynLightInfo light, vec3 normal, vec4 relief)
	{
		if (!UsePackedLight(light))
			return vec3(0.0);
		bool directional = (light.flags & LIGHTINFO_STAGE_B_DIRECTIONAL) != 0;
		float lightdistance = distance(light.pos.xyz, SDVK_LIGHTING_POSITION);
		
		if (light.radius < lightdistance)
			return vec3(0.0); // Early out lights touching surface but not this fragment
		
		vec3 lightdir = directional ? light.spotDir : normalize(light.pos.xyz - SDVK_LIGHTING_POSITION);
		
		float dotprod;
		
		if (!LIGHT_NONORMALS)
		{
			dotprod = dot(normal, lightdir);
			if (dotprod < -0.0001) return vec3(0.0);	// light hits from the backside. This can happen with full sector light lists and must be rejected for all cases. Note that this can cause precision issues.
		}
		
		#ifdef SDVK_STRUCTURAL_RELIEF
		bool useRelief = UseStructuralRelief(light) && any(notEqual(relief, vec4(0.0)));
		vec3 reliefLightDir = lightdir;
		if (useRelief && !directional && relief.w != 0.0)
		{
			vec3 toLight = light.pos.xyz - (SDVK_LIGHTING_POSITION + uSpriteNormal.xyz * relief.w);
			float distanceSquared = dot(toLight, toLight);
			if (distanceSquared > 1e-8)
			{
				lightdistance = sqrt(distanceSquared);
				reliefLightDir = toLight / lightdistance;
			}
		}
		#endif

		float attenuation = PackedLightFalloff(light, lightdistance);

		if ((light.flags & LIGHTINFO_SPOT) != 0)
		{
			float spotCosine = dot(lightdir, light.spotDir.xyz);
			attenuation *= smoothstep(light.spotOuterAngle, light.spotInnerAngle, spotCosine);
		}
		
		#ifdef SDVK_STRUCTURAL_RELIEF
		if (useRelief)
		{
			vec3 geometricNormal = uSpriteNormal.xyz;
			vec3 baseNormal = LIGHT_NONORMALS ? geometricNormal : normal;
			vec3 reliefNormal = SDVKReliefNormal(baseNormal, geometricNormal, relief.xyz);
			float incidence = clamp(dot(reliefNormal, reliefLightDir), 0.0, 1.0);
			if (!LIGHT_NONORMALS && (light.flags & LIGHTINFO_ATTENUATED) != 0)
				attenuation *= incidence;
			else
			{
				float originalIncidence = clamp(dot(baseNormal, reliefLightDir), 0.0, 1.0);
				attenuation *= 1.0 + (incidence - originalIncidence);
			}
		}
		else
		#endif
		if (!LIGHT_NONORMALS)
		{
			if ((light.flags & LIGHTINFO_ATTENUATED) != 0)
			{
				attenuation *= clamp(dotprod, 0.0, 1.0);
			}
		}
		
		if (attenuation > 0.0) // Skip shadow map test if possible
		{
			if((light.flags & (LIGHTINFO_SUN | LIGHTINFO_TRACE)) == (LIGHTINFO_SUN | LIGHTINFO_TRACE))
			{
				attenuation *= traceSun(lightdir);
			}
			else if((light.flags & (LIGHTINFO_SHADOWMAPPED | LIGHTINFO_SUN)) == LIGHTINFO_SHADOWMAPPED)
			{
				attenuation *= shadowAttenuation(light.pos.xyz, light.shadowIndex, light.softShadowRadius, light.flags);
			}
			
			attenuation *= WorldLightVisibility(light, pixelpos.xyz, ivec2(gl_FragCoord.xy));
			return light.color.rgb * attenuation;
		}
		else
		{
			return vec3(0.0);
		}
	}
	
	vec3 ProcessMaterialLight(Material material, vec3 color, float sunlightAttenuation)
	{
		bool stageB = STAGE_B_WORLD_LIGHTING;
		vec4 dynlight = uDynLightColor;
		vec3 normal = material.Normal;
		bool fullbrightRelief = uWorldReliefParams.w >= 5.0;

		if (sunlightAttenuation > 0.0)
		{
			sunlightAttenuation *= clamp(dot(normal, SunDir), 0.0, 1.0);
			dynlight.rgb += SunColor.rgb * SunIntensity * sunlightAttenuation;
		}

		#if defined(SHADE_VERTEX) && !defined(UBERSHADER)
		if (!stageB && !fullbrightRelief)
			dynlight.rgb += vLightColor;
		#endif
		#if defined(UBERSHADER) || defined(SHADE_VERTEX)
		if (stageB)
		#endif
		if (uLightIndex >= 0 && !fullbrightRelief)
		{
			ivec4 lightRange = getLightRange();
			if (lightRange.z > lightRange.x)
			{
				// modulated lights
				for (int i = lightRange.x; i < lightRange.y; i++)
				{
					dynlight.rgb += lightContribution(getLights()[i], normal, material.WorldRelief);
				}

				// subtractive lights
				for (int i = lightRange.y; i < lightRange.z; i++)
				{
					dynlight.rgb -= lightContribution(getLights()[i], normal, material.WorldRelief);
				}
			}
		}
		
		vec3 frag;
		
		if (LIGHT_BLEND_CLAMPED)
		{
			frag = material.Base.rgb * clamp(color + desaturate(dynlight).rgb, 0.0, 1.4);
		}
		else if (LIGHT_BLEND_COLORED_CLAMP)
		{
			frag = color + desaturate(dynlight).rgb;
			frag = material.Base.rgb * ((frag / max(max(max(frag.r, frag.g), frag.b), 1.4) * 1.4));
		}
		else
		{
			frag = material.Base.rgb * (color + desaturate(dynlight).rgb);
		}

		#if defined(UBERSHADER) || defined(SHADE_VERTEX)
		if (stageB)
		#endif
		if (uLightIndex >= 0 && !fullbrightRelief)
		{
			ivec4 lightRange = getLightRange();
			if (lightRange.w > lightRange.z)
			{
				vec4 addlight = vec4(0.0);

				// additive lights
				for (int i = lightRange.z; i < lightRange.w; i++)
				{
					addlight.rgb += lightContribution(getLights()[i], normal, material.WorldRelief);
				}

				frag = clamp(frag + desaturate(addlight).rgb, 0.0, 1.0);
			}
		}

		#ifdef SDVK_STRUCTURAL_RELIEF
		if (fullbrightRelief)
			frag *= SDVKFullbrightReliefScale(material.WorldRelief);
		#endif
		return frag;
	}

	vec3 ProcessSWLight(Material material, float sunlightAttenuation)
	{
		vec3 normal = material.Normal;
		vec3 dynlight = vec3(0.0);
		bool fullbrightRelief = uWorldReliefParams.w >= 5.0;

		if (sunlightAttenuation > 0.0)
		{
			sunlightAttenuation *= clamp(dot(normal, SunDir), 0.0, 1.0);
			dynlight.rgb += SunColor.rgb * SunIntensity * sunlightAttenuation;
		}

		#ifndef UBERSHADER
			#ifdef SHADE_VERTEX
				if (!fullbrightRelief)
					dynlight.rgb += vLightColor;
			#else
				if (uLightIndex >= 0 && !fullbrightRelief)
				{
					ivec4 lightRange = getLightRange();
				
					if (lightRange.z > lightRange.x)
					{
						// modulated lights
						for(int i=lightRange.x; i<lightRange.y; i++)
						{
							dynlight.rgb += lightContribution(getLights()[i], normal, vec4(0.0));
						}

						// subtractive lights
						for(int i=lightRange.y; i<lightRange.z; i++)
						{
							dynlight.rgb -= lightContribution(getLights()[i], normal, vec4(0.0));
						}
					}
				}
			#endif
			dynlight = desaturate(vec4(dynlight, 0.0)).rgb;
		#endif

		return dynlight;
	}

#else
	vec3 ProcessMaterialLight(Material material, vec3 color, float sunlightAttenuation)
	{
		return material.Base.rgb;
	}

	vec3 ProcessSWLight(Material material, float sunlightAttenuation)
	{
		return vec3(0.0);
	}
#endif
