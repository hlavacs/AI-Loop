module;
#include <memory>
#include <numeric>
#include <vector>
export module canvas;
import shapes;

/// @brief Drawing colours.
/// @satisfies R-4
export enum class Color { Red, Green, Blue };

/// @brief Owns the shapes of a scene.
/// @satisfies R-4
export class Canvas {
public:
    Canvas(int width, int height) : width_(width), height_(height) {}

    /// @brief Take ownership of a shape.
    void add(std::unique_ptr<Shape> shape) { shapes_.push_back(std::move(shape)); }

    /// @brief Sum of all shape areas.
    double total_area() const {
        return std::accumulate(shapes_.begin(), shapes_.end(), 0.0,
                               [](double acc, const std::unique_ptr<Shape>& s) { return acc + s->area(); });
    }

    /// @brief The shapes in insertion order.
    const std::vector<std::unique_ptr<Shape>>& shapes() const { return shapes_; }
    int width() const { return width_; }
    int height() const { return height_; }

private:
    int width_;
    int height_;
    std::vector<std::unique_ptr<Shape>> shapes_;
};
