// SHADOW-001's bounded CPU projection/receiver clipping, independent of views.
#pragma once
#include <algorithm>
#include <cmath>
#include <vector>

namespace HWSpriteShadow
{
struct Point { double x, y, z; };
struct Vertex { double x, y, z, u, v; };
struct Edge { double x1, y1, x2, y2; };
constexpr int ProjectionStrips = 16;
constexpr unsigned MaxReceiverEdges = 64;
constexpr unsigned MaxVertices = 256;

inline Point CardPoint(Point anchor, double sideX, double sideY, double width, double height,
    double offset, double top, double u, double v, bool mirror, double horizontalOffset)
{
    double across = offset - u * width;
    if (mirror) across = -across;
    across += horizontalOffset;
    return {anchor.x + sideX * across, anchor.y + sideY * across, top - v * height};
}

inline bool Project(Point light, Point point, double floor, double maxLength, Point anchor, Vertex& out)
{
    const double denominator = light.z - point.z;
    if (!std::isfinite(denominator) || denominator < 8 || point.z < floor - .01 ||
        !std::isfinite(maxLength) || maxLength < 16 || maxLength > 512) return false;
    const double t = (light.z - floor) / denominator;
    if (!std::isfinite(t) || t < 1 || t > 64) return false;
    out.x = light.x + t * (point.x - light.x);
    out.y = light.y + t * (point.y - light.y);
    out.z = floor;
    const double dx = out.x - anchor.x, dy = out.y - anchor.y;
    return std::isfinite(out.x) && std::isfinite(out.y) && std::isfinite(floor) &&
        dx * dx + dy * dy <= maxLength * maxLength;
}

inline double Side(const Edge& e, double x, double y)
{
    return (e.x2 - e.x1) * (y - e.y1) - (e.y2 - e.y1) * (x - e.x1);
}

// Clip one projected band to the convex BSP receiver. Boundary intersections
// interpolate UV as well as position. The 16 small bands bound the error of
// affine UV interpolation for this projective point-light mapping.
inline std::vector<Vertex> Clip(std::vector<Vertex> polygon, const std::vector<Edge>& edges, Point inside)
{
    if (edges.size() < 3 || edges.size() > MaxReceiverEdges) return {};
    for (const auto& e : edges)
    {
        const double centreSide = Side(e, inside.x, inside.y);
        if (!std::isfinite(centreSide) || std::abs(centreSide) < 1e-8) return {};
        const double sign = centreSide > 0 ? 1 : -1;
        std::vector<Vertex> next;
        if (polygon.empty()) return {};
        auto previous = polygon.back();
        double previousDistance = sign * Side(e, previous.x, previous.y);
        for (const auto& current : polygon)
        {
            const double distance = sign * Side(e, current.x, current.y);
            if ((distance >= 0) != (previousDistance >= 0))
            {
                const double t = previousDistance / (previousDistance - distance);
                next.push_back({previous.x + t * (current.x - previous.x), previous.y + t * (current.y - previous.y),
                    current.z, previous.u + t * (current.u - previous.u), previous.v + t * (current.v - previous.v)});
            }
            if (distance >= 0) next.push_back(current);
            previous = current;
            previousDistance = distance;
        }
        if (next.size() > MaxReceiverEdges + 4) return {};
        polygon = std::move(next);
    }
    return polygon;
}
}
