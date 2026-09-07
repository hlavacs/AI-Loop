cmake_minimum_required(VERSION 3.28)
project(sample_project VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_CXX_SCAN_FOR_MODULES ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/bin/${CMAKE_BUILD_TYPE}")
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/bin/${CMAKE_BUILD_TYPE}")

# One module per concept; the library holds everything except main().
add_library(sample_lib STATIC)
target_sources(sample_lib PUBLIC FILE_SET CXX_MODULES FILES
    src/core/geometry.cppm
    src/core/shapes.cppm
    src/core/stack.cppm
    src/util/strings.cppm
    src/util/logging.cppm
    src/render/canvas.cppm
    src/render/renderer.cppm
    src/third_party/json_lite.cppm
    src/app/config.cppm
    src/app/simulation.cppm
)
target_include_directories(sample_lib PRIVATE src/third_party)

add_executable(sample src/main.cpp)
target_link_libraries(sample PRIVATE sample_lib)

enable_testing()
add_executable(smoke_test tests/smoke_test.cpp)
target_link_libraries(smoke_test PRIVATE sample_lib)
add_test(NAME smoke COMMAND smoke_test)
