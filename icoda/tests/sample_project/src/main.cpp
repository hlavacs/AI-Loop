/// @file main.cpp
/// @brief Entry point of the sample project.
#include <string>
import config;
import logging;
import renderer;
import simulation;

/// @brief Load the configuration, run one simulation round, report the count.
/// @satisfies R-8
int main() {
    const auto config = load_config();
    ConsoleRenderer renderer;
    Simulation simulation(config, renderer);
    const int drawn = simulation.run();
    log(Level::Info, "drawn " + std::to_string(drawn));
    return drawn > 0 ? 0 : 1;
}
