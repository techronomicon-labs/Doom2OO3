// SHADOW-001: shadow-only R8 coverage. No visible sprite data is ever changed.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

namespace HWSpriteShadow
{
constexpr int MaxMaskDimension = 512;
constexpr size_t MaxMaskBytes = 16 * 1024 * 1024;

// Deliberately no hole filling or dilation: a one-pixel rifle/limb gap is
// meaningful artwork. A narrow smoothstep reconstructs the alpha contour,
// rather than applying a blur to either the shadow interior or source art.
inline std::vector<uint8_t> MakeMask(const uint8_t* bgra, int width, int height, int pitch, int scale)
{
    if (!bgra || width <= 0 || height <= 0 || (scale != 1 && scale != 4) ||
        width > MaxMaskDimension / scale || height > MaxMaskDimension / scale || pitch < width * 4)
        return {};
    const int outWidth = width * scale, outHeight = height * scale;
    std::vector<uint8_t> mask(size_t(outWidth) * outHeight);
    auto alpha = [&](int x, int y) -> double {
        // Transparent outside the image, so silhouettes reaching a source
        // edge do not expand or smear across the clamped texture border.
        return x >= 0 && y >= 0 && x < width && y < height ? bgra[y * pitch + x * 4 + 3] / 255.0 : 0.0;
    };
    for (int y = 0; y < outHeight; ++y)
        for (int x = 0; x < outWidth; ++x)
        {
            const double sx = (x + .5) / scale - .5, sy = (y + .5) / scale - .5;
            const int ix = int(std::floor(sx)), iy = int(std::floor(sy));
            const double fx = sx - ix, fy = sy - iy;
            double coverage = (alpha(ix, iy) * (1 - fx) + alpha(ix + 1, iy) * fx) * (1 - fy) +
                (alpha(ix, iy + 1) * (1 - fx) + alpha(ix + 1, iy + 1) * fx) * fy;
            if (scale > 1)
            {
                coverage = std::clamp((coverage - .35) / .30, 0.0, 1.0);
                coverage = coverage * coverage * (3 - 2 * coverage);
            }
            mask[size_t(y) * outWidth + x] = uint8_t(std::lround(coverage * 255));
        }
    return mask;
}
}
