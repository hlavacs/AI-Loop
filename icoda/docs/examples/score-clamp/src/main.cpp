/// @file main.cpp
/// @brief Entry point for the Score Clamp demonstration.
import app;

/// @brief Return a conventional process success or failure status.
/// @satisfies R-4
int main() {
    return app::run() == 0 ? 0 : 1;
}
