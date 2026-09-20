#include <array>
#include <iostream>
#include <limits>
#include <utility>
import app;

/// @brief Check boundaries, extreme integers, and idempotence.
/// @satisfies R-1
/// @satisfies R-2
/// @satisfies R-3
/// @satisfies R-4
int main() {
    const std::array<std::pair<int, int>, 9> cases{{
        {std::numeric_limits<int>::min(), 0}, {-1, 0},
        {0, 0}, {1, 1}, {42, 42}, {99, 99},
        {100, 100}, {101, 100},
        {std::numeric_limits<int>::max(), 100},
    }};
    for (const auto& [input, expected] : cases) {
        const int actual = app::ScoreClamp::clamp(input);
        if (actual != expected ||
            app::ScoreClamp::clamp(actual) != actual) {
            std::cerr << "Unexpected result for " << input << '\n';
            return 1;
        }
    }
    return app::run();
}
