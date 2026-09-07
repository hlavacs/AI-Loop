module;
#include <string>
export module config;
import logging;

/// @brief Default canvas width in cells.
export constexpr int kDefaultWidth = 80;
/// @brief Default canvas height in cells.
export constexpr int kDefaultHeight = 24;

/// @brief Everything the simulation needs to start.
/// @satisfies R-7
export struct Config {
    int width = kDefaultWidth;
    int height = kDefaultHeight;
    Level level = Level::Info;
    std::string title = "sample";
};

/// @brief The configuration; a real program would read it from a file.
/// @satisfies R-7
export Config load_config() {
    log(Level::Debug, "using built-in configuration");
    return Config{};
}
