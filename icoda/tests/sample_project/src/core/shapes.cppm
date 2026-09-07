module;
#include <numbers>
#include <string>
export module shapes;
import geometry;

/// @brief The kinds of shape the simulation knows.
/// @satisfies R-1
export enum class ShapeKind { Circle, Square, Triangle };

/// @brief Human-readable name of a shape kind.
/// @satisfies R-1
export std::string describe(ShapeKind kind) {
    switch (kind) {
    case ShapeKind::Circle: return "circle";
    case ShapeKind::Square: return "square";
    case ShapeKind::Triangle: return "triangle";
    }
    return "unknown";
}

/// @brief Base of all shapes: a kind, a position and an area.
/// @satisfies R-1
export class Shape {
public:
    virtual ~Shape() = default;
    /// @brief The kind of this shape.
    virtual ShapeKind kind() const = 0;
    /// @brief Enclosed area.
    virtual double area() const = 0;
    /// @brief Reference point of the shape.
    Point center() const { return center_; }

protected:
    explicit Shape(Point center) : center_(center) {}

private:
    Point center_;
};

/// @brief A circle given by centre and radius.
/// @satisfies R-1
export class Circle : public Shape {
public:
    Circle(Point center, double radius) : Shape(center), radius_(radius) {}
    ShapeKind kind() const override { return ShapeKind::Circle; }
    double area() const override { return std::numbers::pi * radius_ * radius_; }

private:
    double radius_;
};

/// @brief An axis-aligned square given by centre and side length.
/// @satisfies R-1
export class Square : public Shape {
public:
    Square(Point center, double side) : Shape(center), side_(side) {}
    ShapeKind kind() const override { return ShapeKind::Square; }
    double area() const override { return side_ * side_; }

private:
    double side_;
};
