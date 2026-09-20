# Score Clamp: completed C++ tutorial

This is the complete reference result for [the ICODA tutorial](../../TUTORIAL.md).
Copy this directory outside the ICODA checkout before opening it as a project.

Use CMake 3.28 or later, Ninja, and a C++23 compiler with C++20 module scanning.
On macOS select Homebrew LLVM before the first configure:

```bash
export CC="$(brew --prefix llvm)/bin/clang"
export CXX="$(brew --prefix llvm)/bin/clang++"
cmake --preset debug
cmake --build --preset debug
ctest --preset debug
./bin/Debug/ScoreClamp
```

On Linux set CC/CXX to your matching Clang tools if needed. On Windows use an
LLVM/MSVC developer prompt with Ninja and run `bin\Debug\ScoreClamp.exe`.

Expected output: `scores: 0 42 100`, exit status 0. CTest runs `smoke` (nine
boundary and extreme cases plus idempotence and the application service) and
`demo` (the executable's output). No external C++ test library is required.

The example entry point is `examples/basic/main.cpp`; it links the reusable module in `src/app/app.cppm`.
The module, entry point, and smoke test are reproduced in full in the tutorial.
The minimal CMake files here contain only the debug preset used by the walkthrough;
a project created by ICODA also includes release presets and generated build scripts.
