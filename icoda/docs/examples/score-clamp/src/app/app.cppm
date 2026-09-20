module;
#include <algorithm>
#include <iostream>
export module app;

/// @brief Operations for the Score Clamp example.
export namespace app {

/// @brief Keeps an integer score in the inclusive range 0 to 100.
/// @satisfies G-1
struct ScoreClamp {
    /// @brief Clamp a score without overflow or changing in-range values.
    /// @satisfies R-1
    /// @satisfies R-2
    /// @satisfies R-3
    static int clamp(int value) {
        return std::clamp(value, 0, 100);
    }
};

/// @brief Print three representative scores and return success.
/// @satisfies R-4
int run() {
    std::cout << "scores: " << ScoreClamp::clamp(-5) << ' '
              << ScoreClamp::clamp(42) << ' '
              << ScoreClamp::clamp(120) << '\n';
    return 0;
}

}  // namespace app
