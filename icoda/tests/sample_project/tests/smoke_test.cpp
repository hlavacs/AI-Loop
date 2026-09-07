/// @brief Smoke test: one simulation round draws the two shapes.
import config;
import renderer;
import simulation;

int main() {
    ConsoleRenderer renderer;
    Simulation simulation(load_config(), renderer);
    return simulation.run() == 2 && renderer.drawn() == 2 ? 0 : 1;
}
