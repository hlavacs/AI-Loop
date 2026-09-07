module;
#include <chrono>
#include <iostream>
#include <string>
#include <string_view>
export module logging;
import strings;

/// @brief Severity of a log line.
/// @satisfies R-6
export enum class Level { Debug, Info, Warn, Error };

/// @brief The level as an upper-case tag.
/// @satisfies R-6
export std::string format_level(Level level) {
    switch (level) {
    case Level::Debug: return to_upper("debug");
    case Level::Info: return to_upper("info");
    case Level::Warn: return to_upper("warn");
    case Level::Error: return to_upper("error");
    }
    return "?";
}

/// @brief Milliseconds since the program started.
/// @satisfies R-6
export long long timestamp() {
    static const auto start = std::chrono::steady_clock::now();
    const auto elapsed = std::chrono::steady_clock::now() - start;
    return std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count();
}

/// @brief Write one line to standard error.
/// @satisfies R-6
export void log(Level level, std::string_view message) {
    std::cerr << '[' << timestamp() << "] " << format_level(level) << ": " << message << '\n';
}
