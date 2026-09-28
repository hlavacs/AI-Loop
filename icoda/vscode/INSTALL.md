# Install ICODA for VS Code

Follow steps 1–5 on the computer where you will use ICODA. Choose only your
operating system's commands. For Python projects, skip step 3 (the C++ tools).

You need **desktop VS Code, one ICODA `.vsix` file, and a Python environment**.
The extension contains the ICODA backend, but does not install Python or its
dependencies automatically. Node.js/npm and an ICODA source checkout are needed
only if you build the `.vsix` yourself.

## 1. Get VS Code and the extension package

1. Install the current desktop [Visual Studio Code](https://code.visualstudio.com/download).
2. Obtain `icoda-0.1.0.vsix` from the person distributing ICODA. If you have no
   package, follow [Build the package from source](#build-the-package-from-source)
   below, then return here. The `icoda` publisher name does not imply that the
   extension is published in the Marketplace.
3. In VS Code, open the Command Palette: **Ctrl+Shift+P** on Windows/Linux or
   **Cmd+Shift+P** on macOS. Run **Extensions: Install from VSIX…**, select the
   file, and reload VS Code if prompted. This is the same
   [VSIX installation procedure](https://code.visualstudio.com/docs/configure/extensions/extension-marketplace#_install-from-a-vsix)
   on all three systems.

## 2. Prepare Python — choose your operating system

Run these commands as your normal user. The environment lives outside the
extension folder so extension upgrades do not remove it. No environment activation
or PowerShell execution-policy change is necessary. Stop and resolve an error
before continuing to the next step.

### Windows — PowerShell

Install the **Python Install Manager** from [python.org](https://www.python.org/downloads/),
then open a **new PowerShell window**. Install Python 3.12:

```powershell
py install 3.12
```

If Python 3.12 is already installed and `py -3.12 --version` works, skip that
installation command. If an older `py` launcher takes precedence, use
`pymanager install 3.12` instead. See the
[official Windows Python instructions](https://docs.python.org/3/using/windows.html).

```powershell
$icodaRuntime = Join-Path $env:LOCALAPPDATA 'ICODA\runtime'
py -3.12 -m venv "$icodaRuntime"
& "$icodaRuntime\Scripts\python.exe" -m pip install --upgrade pip
& "$icodaRuntime\Scripts\python.exe" -m pip install clang==21.1.7 networkx==3.6.1 jsonschema==4.26.0
& "$icodaRuntime\Scripts\python.exe" -c "import clang.cindex, networkx, jsonschema, sys; print('ICODA Python OK'); print(sys.executable)"
```

Keep the interpreter path printed on the last line. It normally looks like
`C:\Users\YOUR-NAME\AppData\Local\ICODA\runtime\Scripts\python.exe`.

### Linux — terminal

On **Ubuntu 24.04 or newer / Debian 12 or newer**, install Python and venv support:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
python3 --version
```

On other distributions, install the equivalent Python and venv packages using
your package manager. The pinned dependencies below require **Python 3.11+**;
Python 3.12 is the tested baseline. Then run:

```bash
icoda_runtime="$HOME/.local/share/icoda/runtime"
python3 -m venv "$icoda_runtime"
"$icoda_runtime/bin/python" -m pip install --upgrade pip
"$icoda_runtime/bin/python" -m pip install clang==21.1.7 networkx==3.6.1 jsonschema==4.26.0
"$icoda_runtime/bin/python" -c "import clang.cindex, networkx, jsonschema, sys; print('ICODA Python OK'); print(sys.executable)"
```

Keep the printed interpreter path, normally
`/home/YOUR-NAME/.local/share/icoda/runtime/bin/python`.

### macOS — Terminal

Install [Homebrew](https://brew.sh/) if necessary and complete the **Next steps**
printed by its installer so `brew` works in a new terminal. Install
[Python 3.12](https://formulae.brew.sh/formula/python@3.12), then create the environment:

```bash
brew install python@3.12
icoda_runtime="$HOME/Library/Application Support/ICODA/runtime"
"$(brew --prefix python@3.12)/bin/python3.12" -m venv "$icoda_runtime"
"$icoda_runtime/bin/python" -m pip install --upgrade pip
"$icoda_runtime/bin/python" -m pip install clang==21.1.7 networkx==3.6.1 jsonschema==4.26.0
"$icoda_runtime/bin/python" -c "import clang.cindex, networkx, jsonschema, sys; print('ICODA Python OK'); print(sys.executable)"
```

Keep the printed interpreter path, normally
`/Users/YOUR-NAME/Library/Application Support/ICODA/runtime/bin/python`.
These commands use Homebrew's actual prefix on both Apple Silicon and Intel Macs.

## 3. For C++ projects: install the native toolchain

**Skip this section for Python-only projects.** C++ analysis needs native
**libclang** as well as the Python `clang` package; pip's `clang` package does
not contain that native library. Building and recording also need **CMake,
Ninja, Clang, clang-scan-deps, and llvm-symbolizer**, plus the project's own SDKs
and libraries. ICODA's module builds require CMake 3.28+; follow any higher
minimum in the project's documentation.

### Windows

Install [Visual Studio Community or Build Tools](https://visualstudio.microsoft.com/downloads/).
In **Visual Studio Installer → Modify** select:

- **Desktop development with C++**, including its MSVC tools and Windows SDK.
- **C++ Clang compiler/tools for Windows** under the optional/individual components.
- **C++ CMake tools for Windows** (includes Ninja).

Component wording varies by Visual Studio release; see
[Microsoft's Clang setup](https://learn.microsoft.com/en-us/cpp/build/clang-support-cmake?view=msvc-170).
ICODA discovers these installations and prepares the Visual Studio build
environment automatically. For manual CMake commands, use the installed
**Developer PowerShell for Visual Studio** with an x64 tool environment.

### Linux — Ubuntu/Debian

Install LLVM 21 using the [official LLVM package repository](https://apt.llvm.org/)
and its version-selecting installer, then add the required tools:

```bash
sudo apt update
sudo apt install build-essential cmake ninja-build curl wget ca-certificates gnupg lsb-release software-properties-common
icoda_llvm_installer="$(mktemp)"
curl -fsSL https://apt.llvm.org/llvm.sh -o "$icoda_llvm_installer"
sudo bash "$icoda_llvm_installer" 21
sudo apt install clang-21 clang-tools-21 libclang-21-dev llvm-21
```

In step 4, set **ICODA: Toolchain: Clang Path** (`icoda.toolchain.clangPath`) to
`/usr/lib/llvm-21/bin/clang++`. This selects the intended version even if an older
Clang is on PATH. Projects using libc++/`import std` may additionally require
`libc++-21-dev` and `libc++abi-21-dev`; follow their build instructions.
On other distributions install the equivalent LLVM 21 packages, including
libclang, the dependency scanner and symbolizer.

### macOS

Install Apple's command-line developer tools if absent, and wait for their
installer to finish:

```bash
xcode-select --install
```

Then install [LLVM 21](https://formulae.brew.sh/formula/llvm@21) and build tools:

```bash
brew install cmake ninja llvm@21
printf '%s/bin/clang++\n' "$(brew --prefix llvm@21)"
```

In step 4, paste that printed path into **ICODA: Toolchain: Clang Path**
(`icoda.toolchain.clangPath`). Homebrew's versioned LLVM is not put on PATH
automatically. Its scanner and libclang are needed in addition to Apple's tools.

## 4. Point ICODA at the installed Python

1. Open **Settings**, choose the **User** tab, and search for `icoda.pythonPath`.
2. Paste the complete interpreter path printed in step 2 into **ICODA: Python Path**.
   Paste the path alone, without surrounding quotes, arguments, `~`, or variables.
   Keep the virtual-environment path; do not replace it with the system Python
   that a symlink points to.
3. For C++, apply the Clang path from step 3 where specified. The other settings
   `icoda.toolchain.cmakePath`, `icoda.toolchain.ninjaPath`, and
   `icoda.toolchain.llvmSymbolizerPath` can point to installed executables if
   automatic discovery misses them.
4. After installing tools, fully quit and reopen VS Code so it inherits the
   updated PATH. Open your project folder and trust it if it is your own/trusted
   code. Run **ICODA: Show Toolchain** in the Command Palette. Check that the
   effective Python matches step 2 and, for C++, the native tools are found.

## 5. Open a project and check that it works

1. Open the folder containing the project sources and run **ICODA: Open Project**.
2. For **Python**, click **Analyse** in the ICODA **Project** view's title bar.
3. For **C++**, first install the project's dependencies and follow its normal
   configure/build instructions. Enable `CMAKE_EXPORT_COMPILE_COMMANDS=ON` in
   its Ninja/Makefiles configuration. Then use **Build** and **Analyse** in ICODA.
   A fresh project may initially report missing target metadata; build/configure
   it, then run **ICODA: Refresh Targets**.
4. Successful analysis shows entity/edge counts and a model that is no longer
   stale. Click **File View**, **Class View**, or **Call View**, then select an
   entity to open its source.
5. To record C++ calls, choose an executable with **Select Target**, click
   **Record Trace**, and accept **Load Trace** when recording finishes. Call View
   offers **Step Into**, **Step Over**, and **Step Out** for the recorded calls.
   Recording runs the target; stepping navigates the recording.

The Project title bar contains **Analyse, Select Target, Build, Record Trace,
File View, Class View, and Call View**. Hover to see tooltips; narrow sidebars may
put buttons in **…**. Equivalent commands remain in the Command Palette.

### If C++ analysis says `No compile_commands.json found`

ICODA looks at the project root, `build/`, and one directory level below `build/`
(for example `build/debug/`). Generate the file with CMake; creating an empty
file does not solve the problem. For an **existing Ninja/Makefiles build**, run
from the project root, replacing `build/debug` with its actual build directory:

```bash
cmake -S . -B build/debug -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build build/debug
```

If the project uses presets, add `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON` to its normal
`cmake --preset PRESET-NAME` configure command instead, preserving the documented
compiler, SDK and dependency settings. Visual Studio and Xcode generators do not
export this file; use a separate Ninja build as supported by the project.
See [CMake's compilation database documentation](https://cmake.org/cmake/help/latest/variable/CMAKE_EXPORT_COMPILE_COMMANDS.html).

## Common installation problems

| Message or symptom | What to do |
| --- | --- |
| `node` / `npm.cmd` not found | Needed only for building the VSIX. Install Node.js as described below, then open a new terminal. Windows PowerShell uses `npm.cmd`. |
| Python not found / `ModuleNotFoundError` | Repeat step 2 and its import check. Set `icoda.pythonPath` to that exact venv interpreter, then run **Developer: Reload Window**. |
| `libclang` cannot be loaded | Install the native C++ toolchain in step 3. A Python-only pip install cannot supply it. Use **Show Toolchain** to check which installation ICODA finds. |
| CMake/Ninja/Clang missing | Complete step 3, restart VS Code, and check **Show Toolchain**. Set full executable paths if needed. |
| CMake is older than the project requires | Install a suitable version from [CMake](https://cmake.org/download/) and set `icoda.toolchain.cmakePath` to its executable. |
| Missing target metadata or compilation database | Configure/build the actual project as described in step 5, then refresh targets and analyse again. |
| Commands disabled / Restricted Mode | Trust the project through VS Code's Workspace Trust controls. ICODA does not start its backend in untrusted workspaces. |
| Permission denied under `icoda-service-locks` | Close other ICODA instances and check ownership of the exact directory named in the error. Use a current package and a user-writable temp directory; routinely running VS Code as administrator is not required. |

Use **ICODA: Show Output** for the backend error details. A first analysis of a
large C++ project can take several minutes. An AI provider is not required for
analysis or browsing; provider-backed development commands need their respective
installed and authenticated CLIs separately.

## Build the package from source

Skip this section when someone has supplied the `.vsix` file. A package built on
one OS can be copied to the other two; each destination still needs its own
Python environment and any C++ tools.

1. Install [Git](https://git-scm.com/downloads) and **Node.js 22+ with npm** from
   [Node.js downloads](https://nodejs.org/en/download). Node.js 24 LTS is suitable.
   Choose the Windows/macOS installer or follow the download page's Linux setup
   instructions. Open a new terminal after installation.
2. In a directory where you want the source checkout, run the block for your OS.
   If you already have the repository, go directly to its `icoda/vscode` folder
   and run the npm commands there; do not clone inside the existing checkout.

**Windows — PowerShell:**

```powershell
git --version
node --version
npm.cmd --version
git clone --branch develop https://github.com/hlavacs/AI-Loop.git
Set-Location AI-Loop\icoda\vscode
npm.cmd ci
npm.cmd run package
```

**Linux/macOS — terminal:**

```bash
git --version
node --version
npm --version
git clone --branch develop https://github.com/hlavacs/AI-Loop.git
cd AI-Loop/icoda/vscode
npm ci
npm run package
```

The result is `icoda/vscode/dist/icoda-0.1.0.vsix` inside the checkout (the version
in the filename follows `package.json`). Return to step 1 to install it. npm
downloads build dependencies; Python and C++ toolchains are not needed just to
package the extension. Keep the full checkout while packaging because the build
also copies backend files from `icoda/icoda_core`.

To update ICODA later, obtain/build the new `.vsix`, run **Install from VSIX…**
again and reload VS Code. Keep the same Python path unless the new release changes
its runtime requirements.

**Verification scope (2026-09-29):** the repository records Linux extension-host
tests. Windows VSIX installation, backend startup and ViennaVulkanEngine analysis
have been checked, with targeted Windows/backend and extension unit tests.
The macOS instructions follow the implementation and vendor documentation but
have not been executed on a Mac. Full Windows/macOS UI qualification remains
pending; installation instructions do not imply complete platform qualification.
