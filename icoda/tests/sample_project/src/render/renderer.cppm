module;
#include <string>
#include <vector>
export module renderer;
import shapes;
import stack;
import logging;
import strings;

/// @brief Draws shapes somewhere; keeps a log of what it drew.
/// @satisfies R-4
export class Renderer {
public:
    virtual ~Renderer() = default;
    /// @brief Draw one shape.
    virtual void draw(const Shape& shape) = 0;
    /// @brief Number of draw calls so far.
    std::size_t drawn() const { return history_.size(); }

protected:
    /// @brief Remember a description of a drawn shape.
    void remember(std::string description) { history_.push(std::move(description)); }

private:
    Stack<std::string> history_;
};

/// @brief A renderer that prints one line per shape.
/// @satisfies R-4
export class ConsoleRenderer : public Renderer {
public:
    void draw(const Shape& shape) override {
        const std::vector<std::string> parts{describe(shape.kind()), std::to_string(shape.area())};
        const auto line = join(parts, " area=");
        log(Level::Debug, line);
        remember(line);
    }
};
