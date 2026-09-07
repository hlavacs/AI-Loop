module;
#include <algorithm>
#include <cctype>
#include <numeric>
#include <string>
#include <vector>
export module strings;

/// @brief Join the parts with a separator.
/// @satisfies R-5
export std::string join(const std::vector<std::string>& parts, const std::string& separator) {
    if (parts.empty()) {
        return "";
    }
    return std::accumulate(std::next(parts.begin()), parts.end(), parts.front(),
                           [&separator](std::string acc, const std::string& part) {
                               return std::move(acc) + separator + part;
                           });
}

/// @brief Upper-case copy of the text.
/// @satisfies R-5
export std::string to_upper(std::string text) {
    std::ranges::transform(text, text.begin(), [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
    return text;
}
