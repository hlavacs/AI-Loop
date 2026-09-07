module;
#include "json_lite.h"
export module jsonlite;

/// @brief Wrapper module: the parts of json_lite.h the project uses.
export namespace jsonlite {
using jsonlite::quote;
using jsonlite::to_json;
}  // namespace jsonlite
