module;
#include <memory>
#include <string>
#include <vector>
export module simulation;
import canvas;
import config;
import geometry;
import jsonlite;
import logging;
import renderer;
import shapes;
import stack;

/// @brief Builds a scene, draws it and reports about it.
/// @satisfies R-8
export class Simulation {
public:
    Simulation(Config config, Renderer& renderer)
        : config_(std::move(config)), renderer_(renderer), canvas_(config_.width, config_.height) {}

    /// @brief Run one round; returns the number of shapes drawn.
    int run() {
        populate();
        draw_all();
        report();
        return static_cast<int>(canvas_.shapes().size());
    }

private:
    /// @brief Add a few shapes around the centre of the canvas.
    void populate() {
        const Point middle{config_.width / 2.0, config_.height / 2.0};
        canvas_.add(std::make_unique<Circle>(middle, 3.0));
        canvas_.add(std::make_unique<Square>(Point{middle.x + 10, middle.y}, 4.0));
        pending_.push(2);
    }

    /// @brief Draw every shape and record the distances from the centroid.
    void draw_all() {
        std::vector<Point> centers;
        for (const auto& shape : canvas_.shapes()) {
            renderer_.draw(*shape);
            centers.push_back(shape->center());
        }
        const auto mid = centroid(centers);
        for (const auto& c : centers) {
            distances_.push_back(distance(c, mid));
        }
        pending_.pop();
    }

    /// @brief Log a JSON summary of the round.
    void report() {
        log(config_.level, "distances " + jsonlite::to_json(distances_));
        log(config_.level, "total area " + std::to_string(canvas_.total_area()));
    }

    Config config_;
    Renderer& renderer_;
    Canvas canvas_;
    Stack<int> pending_;
    std::vector<double> distances_;
};
