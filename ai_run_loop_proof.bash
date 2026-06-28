#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

repo="${AI_LOOP_PROOF_REPO:-/tmp/ai-loop-test}"
source ./ai_loop_python.bash

python_bin="$(choose_ai_loop_python)"
ensure_ai_loop_python_redis "$python_bin"

export AI_LOOP_PYTHON="$python_bin"

usage() {
  cat >&2 <<'EOF'
usage: ./ai_run_loop_proof.bash

Environment:
  AI_LOOP_PROOF_REPO=/tmp/ai-loop-test   fixture repo path
  AI_LOOP_PYTHON=.venv/bin/python        Python used for loop scripts
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

write_fixture() {
  mkdir -p "$repo/src" "$repo/tests"

  cat > "$repo/README.md" <<'EOF'
# AI Loop Test Project

Small C++20 compile-and-run fixture for the Claude + Codex loop.

Run:

```bash
make test
```
EOF

  cat > "$repo/.gitignore" <<'EOF'
build/
EOF

  cat > "$repo/Makefile" <<'EOF'
CXX ?= g++
CXXFLAGS ?= -std=c++20 -O2 -Wall -Wextra -pedantic

BIN := build/ai_loop_fixture
SRC := src/main.cpp src/graph.cpp src/expression.cpp

.PHONY: all test clean

all: $(BIN)

$(BIN): $(SRC) src/graph.hpp src/expression.hpp
	mkdir -p build
	$(CXX) $(CXXFLAGS) $(SRC) -o $(BIN)

test: $(BIN)
	./tests/run_fixture.sh $(BIN)

clean:
	rm -rf build
EOF

  cat > "$repo/src/graph.hpp" <<'EOF'
#pragma once

#include <string>
#include <unordered_map>
#include <vector>

struct PathResult {
    int cost;
    std::vector<std::string> nodes;
};

class WeightedGraph {
public:
    void add_edge(std::string from, std::string to, int weight);
    PathResult shortest_path(const std::string& start, const std::string& goal) const;

private:
    std::unordered_map<std::string, std::vector<std::pair<std::string, int>>> adjacency_;
};
EOF

  cat > "$repo/src/graph.cpp" <<'EOF'
#include "graph.hpp"

#include <algorithm>
#include <functional>
#include <queue>
#include <stdexcept>
#include <unordered_map>

void WeightedGraph::add_edge(std::string from, std::string to, int weight) {
    if (weight <= 0) {
        throw std::invalid_argument("edge weights must be positive");
    }
    adjacency_[std::move(from)].push_back({std::move(to), weight});
}

PathResult WeightedGraph::shortest_path(const std::string& start, const std::string& goal) const {
    using QueueItem = std::pair<int, std::string>;
    std::priority_queue<QueueItem, std::vector<QueueItem>, std::greater<>> queue;
    std::unordered_map<std::string, int> distance;
    std::unordered_map<std::string, std::string> previous;

    distance[start] = 0;
    queue.push({0, start});

    while (!queue.empty()) {
        auto [cost, node] = queue.top();
        queue.pop();

        if (distance.at(node) != cost) {
            continue;
        }
        if (node == goal) {
            break;
        }

        auto found = adjacency_.find(node);
        if (found == adjacency_.end()) {
            continue;
        }

        for (const auto& [next, weight] : found->second) {
            const int candidate = cost + weight;
            if (!distance.contains(next) || candidate < distance[next]) {
                distance[next] = candidate;
                previous[next] = node;
                queue.push({candidate, next});
            }
        }
    }

    if (!distance.contains(goal)) {
        throw std::runtime_error("no path from " + start + " to " + goal);
    }

    std::vector<std::string> path;
    for (std::string node = goal;; node = previous.at(node)) {
        path.push_back(node);
        if (node == start) {
            break;
        }
    }
    std::reverse(path.begin(), path.end());
    return {distance.at(goal), path};
}
EOF

  cat > "$repo/src/expression.hpp" <<'EOF'
#pragma once

#include <string>

int evaluate_expression(const std::string& input);
EOF

  cat > "$repo/src/expression.cpp" <<'EOF'
#include "expression.hpp"

#include <cctype>
#include <stdexcept>
#include <string>

namespace {

class Parser {
public:
    explicit Parser(const std::string& text) : text_(text) {}

    int parse() {
        const int value = expression();
        skip_space();
        if (position_ != text_.size()) {
            throw std::runtime_error("unexpected input at byte " + std::to_string(position_));
        }
        return value;
    }

private:
    int expression() {
        int value = term();
        while (true) {
            skip_space();
            if (match('+')) {
                value += term();
            } else if (match('-')) {
                value -= term();
            } else {
                return value;
            }
        }
    }

    int term() {
        int value = factor();
        while (true) {
            skip_space();
            if (match('*')) {
                value *= factor();
            } else if (match('/')) {
                const int divisor = factor();
                if (divisor == 0) {
                    throw std::runtime_error("division by zero");
                }
                value /= divisor;
            } else {
                return value;
            }
        }
    }

    int factor() {
        skip_space();
        if (match('(')) {
            const int value = expression();
            if (!match(')')) {
                throw std::runtime_error("missing closing parenthesis");
            }
            return value;
        }
        return number();
    }

    int number() {
        skip_space();
        int sign = 1;
        if (match('-')) {
            sign = -1;
        }
        if (position_ >= text_.size() || !std::isdigit(static_cast<unsigned char>(text_[position_]))) {
            throw std::runtime_error("expected number at byte " + std::to_string(position_));
        }
        int value = 0;
        while (position_ < text_.size() && std::isdigit(static_cast<unsigned char>(text_[position_]))) {
            value = value * 10 + (text_[position_] - '0');
            ++position_;
        }
        return sign * value;
    }

    bool match(char expected) {
        skip_space();
        if (position_ < text_.size() && text_[position_] == expected) {
            ++position_;
            return true;
        }
        return false;
    }

    void skip_space() {
        while (position_ < text_.size() && std::isspace(static_cast<unsigned char>(text_[position_]))) {
            ++position_;
        }
    }

    const std::string& text_;
    std::size_t position_ = 0;
};

}  // namespace

int evaluate_expression(const std::string& input) {
    return Parser(input).parse();
}
EOF

  cat > "$repo/src/main.cpp" <<'EOF'
#include "expression.hpp"
#include "graph.hpp"

#include <iostream>
#include <numeric>
#include <string>

namespace {

std::string join_path(const std::vector<std::string>& path) {
    return std::accumulate(
        std::next(path.begin()),
        path.end(),
        path.front(),
        [](std::string joined, const std::string& node) {
            return std::move(joined) + "->" + node;
        });
}

WeightedGraph sample_graph() {
    WeightedGraph graph;
    graph.add_edge("ingest", "parse", 4);
    graph.add_edge("ingest", "cache", 2);
    graph.add_edge("cache", "parse", 1);
    graph.add_edge("parse", "plan", 7);
    graph.add_edge("parse", "review", 3);
    graph.add_edge("review", "plan", 1);
    graph.add_edge("plan", "done", 5);
    graph.add_edge("review", "done", 9);
    return graph;
}

}  // namespace

int main(int argc, char** argv) {
    const std::string expression = argc > 1 ? argv[1] : "7 * (3 + 5) - 6 / 2";

    try {
        const int expression_value = evaluate_expression(expression);
        const auto result = sample_graph().shortest_path("ingest", "done");

        std::cout << "expression=" << expression << "\n";
        std::cout << "value=" << expression_value << "\n";
        std::cout << "shortest_cost=" << result.cost << "\n";
        std::cout << "shortest_path=" << join_path(result.nodes) << "\n";
        std::cout << "fixture=ok\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "fixture error: " << error.what() << "\n";
        return 1;
    }
}
EOF

  cat > "$repo/tests/run_fixture.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

bin="${1:?usage: run_fixture.sh /path/to/binary}"
output="$("$bin" "12 + 2 * (9 - 4)")"

printf '%s\n' "$output"

grep -q '^value=22$' <<<"$output"
grep -q '^shortest_cost=12$' <<<"$output"
grep -q '^shortest_path=ingest->cache->parse->review->plan->done$' <<<"$output"
grep -q '^fixture=ok$' <<<"$output"
EOF
  chmod +x "$repo/tests/run_fixture.sh"
}

ensure_git_repo() {
  if [ ! -d "$repo/.git" ]; then
    git -C "$repo" init
  fi

  git -C "$repo" config user.email ai-loop-test@example.invalid
  git -C "$repo" config user.name "AI Loop Test"

  git -C "$repo" add .
  if ! git -C "$repo" rev-parse --verify HEAD >/dev/null 2>&1; then
    git -C "$repo" commit -m "Add ai loop compile fixture"
  elif ! git -C "$repo" diff --cached --quiet; then
    git -C "$repo" commit -m "Refresh ai loop compile fixture"
  fi
}

echo "proof repo: $repo"
write_fixture
ensure_git_repo

echo "running fixture test"
make -C "$repo" test

echo "checking loop processes"
./ai_loopctl.bash start
./ai_loopctl.bash status

echo "submitting AI loop proof job"
job_output="$("$python_bin" start_job.py \
  --repo "$repo" \
  --goal "Prove the AI loop works on the C++ fixture by adding LOOP_PROOF.txt containing the text ai-loop proof passed. Do not change the fixture behavior." \
  --test-cmd "make test && test -f LOOP_PROOF.txt && grep -q 'ai-loop proof passed' LOOP_PROOF.txt" \
  --constraint "Keep the existing C++ fixture compiling and running." \
  --acceptance "make test passes in the job worktree." \
  --acceptance "LOOP_PROOF.txt exists and contains ai-loop proof passed." \
  --max-iterations 3 \
  --wait \
  --poll-interval 5 \
  --timeout 900)"
printf '%s\n' "$job_output"

job_id="$(sed -n 's/^created job //p' <<<"$job_output")"
if [ -z "$job_id" ]; then
  echo "could not parse job id from start_job.py output" >&2
  exit 1
fi

worktree="$(sed -n 's/^worktree: //p' <<<"$job_output" | tail -n 1)"
if [ -z "$worktree" ]; then
  echo "could not parse worktree from start_job.py output" >&2
  exit 1
fi
echo "verifying worktree: $worktree"
make -C "$worktree" test
test -f "$worktree/LOOP_PROOF.txt"
grep -q 'ai-loop proof passed' "$worktree/LOOP_PROOF.txt"

echo
echo "AI loop proof passed"
echo "job: $job_id"
echo "worktree: $worktree"
echo
echo "Inspect with:"
echo "./ai_check_job.bash $job_id"
echo "./ai_print_log.bash --job $job_id --limit 120"
