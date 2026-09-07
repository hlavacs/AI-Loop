// A tiny "third-party" header-only library used through the jsonlite wrapper module.
#pragma once
#include <string>
#include <vector>

namespace jsonlite {

inline std::string quote(const std::string& text) { return "\"" + text + "\""; }

template <class T>
std::string to_json(const std::vector<T>& values) {
    std::string out = "[";
    for (std::size_t i = 0; i < values.size(); ++i) {
        out += (i ? "," : "") + std::to_string(values[i]);
    }
    return out + "]";
}

}  // namespace jsonlite
