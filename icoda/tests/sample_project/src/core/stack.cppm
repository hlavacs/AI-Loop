module;
#include <cstddef>
#include <optional>
#include <vector>
export module stack;

/// @brief A last-in-first-out container on top of std::vector.
/// @satisfies R-3
export template <class T>
class Stack {
public:
    /// @brief Push a value on top.
    void push(T value) { items_.push_back(std::move(value)); }

    /// @brief Remove and return the top value, or nothing when empty.
    std::optional<T> pop() {
        if (items_.empty()) {
            return std::nullopt;
        }
        T value = std::move(items_.back());
        items_.pop_back();
        return value;
    }

    /// @brief Number of stored values.
    std::size_t size() const { return items_.size(); }

    /// @brief True when nothing is stored.
    bool empty() const { return items_.empty(); }

private:
    std::vector<T> items_;
};
