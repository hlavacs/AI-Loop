cmake_minimum_required(VERSION 3.28)
project(ScoreClamp VERSION 0.1.0 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_CXX_SCAN_FOR_MODULES ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/bin/${CMAKE_BUILD_TYPE}")

add_library(ScoreClamp_lib STATIC)
target_sources(ScoreClamp_lib PUBLIC FILE_SET CXX_MODULES FILES
    src/app/app.cppm
)
add_executable(ScoreClamp src/main.cpp)
target_link_libraries(ScoreClamp PRIVATE ScoreClamp_lib)

enable_testing()
add_executable(smoke_test tests/smoke_test.cpp)
target_link_libraries(smoke_test PRIVATE ScoreClamp_lib)
add_test(NAME smoke COMMAND smoke_test)
add_test(NAME demo COMMAND ScoreClamp)
set_tests_properties(demo PROPERTIES
    PASS_REGULAR_EXPRESSION "scores: 0 42 100"
)
