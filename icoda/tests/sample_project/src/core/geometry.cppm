module;
#include <cmath>
#include <numeric>
#include <vector>
export module geometry;

/// @brief A point in the plane.
/// @satisfies R-2
export struct Point {
    double x = 0.0;
    double y = 0.0;
};

/// @brief Euclidean distance between two points.
/// @satisfies R-2
export double distance(Point a, Point b) {
    return std::hypot(a.x - b.x, a.y - b.y);
}

/// @brief Arithmetic mean of the points; the origin for an empty list.
/// @satisfies R-2
export Point centroid(const std::vector<Point>& points) {
    if (points.empty()) {
        return {};
    }
    const auto sum = std::accumulate(points.begin(), points.end(), Point{},
                                     [](Point acc, Point p) { return Point{acc.x + p.x, acc.y + p.y}; });
    const auto n = static_cast<double>(points.size());
    return {sum.x / n, sum.y / n};
}
