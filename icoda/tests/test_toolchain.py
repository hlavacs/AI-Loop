"""libclang candidates per platform, version parsing with the Apple mapping, loading the VM's library."""

from __future__ import annotations

import os

import pytest

from icoda_core import toolchain


def fake_globber(patterns: dict[str, list[str]]):
    return lambda pattern: patterns.get(pattern, [])


def test_env_variable_comes_first_then_platform_then_wheel() -> None:
    xcode = "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/libclang.dylib"
    present = {"/opt/llvm/lib/libclang.dylib", xcode, "/opt/homebrew/opt/llvm/lib/libclang.dylib"}
    found = toolchain.candidates("darwin", {"ICODA_LIBCLANG": "/opt/llvm/lib/libclang.dylib"},
                                 exists=lambda p: p in present,
                                 globber=fake_globber({"/opt/homebrew/opt/llvm*/lib/libclang.dylib":
                                                       ["/opt/homebrew/opt/llvm/lib/libclang.dylib"]}))
    sources = [c.source for c in found if c.source != "wheel"]
    assert sources == ["env", "homebrew", "xcode"]


def test_windows_visual_studio_component() -> None:
    dll = r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\Llvm\x64\bin\libclang.dll"
    pattern = os.path.join(r"C:\Program Files", "Microsoft Visual Studio", "*", "*", "VC", "Tools", "Llvm", "x64",
                           "bin", "libclang.dll")
    found = toolchain.candidates("win32", {"ProgramFiles": r"C:\Program Files"}, exists=lambda p: p == dll,
                                 globber=fake_globber({pattern: [dll]}))
    assert [c.source for c in found if c.source != "wheel"] == ["vs"]


def test_linux_prefers_newest_llvm() -> None:
    libs = ["/usr/lib/llvm-16/lib/libclang.so.1", "/usr/lib/llvm-18/lib/libclang.so.1"]
    found = toolchain.candidates("linux", {}, exists=lambda p: p in libs,
                                 globber=fake_globber({"/usr/lib/llvm-*/lib/libclang.so.1": libs}))
    assert found[0].path.endswith("llvm-18/lib/libclang.so.1")


def test_version_parsing_and_apple_mapping() -> None:
    assert toolchain.parse_version("clang version 18.1.8 (linaro)") == ("18.1.8", 18, False)
    assert toolchain.parse_version("Apple clang version 16.0.0 (clang-1600.0.26.3)") == ("16.0.0", 17, True)
    assert toolchain.parse_version("Apple clang version 17.0.0 (clang-1700.0.13.3)") == ("17.0.0", 19, True)
    assert toolchain.parse_version("garbage") == ("garbage", 0, False)


@pytest.mark.skipif(not toolchain.candidates(), reason="no libclang available")
def test_load_and_self_test() -> None:
    chosen = toolchain.candidates()[0]
    loaded = toolchain.load(chosen.path)
    assert loaded.llvm_major >= 16 and loaded.version.count(".") == 2
    assert "libclang:" in loaded.describe()


def test_select_candidate_reports_when_no_candidates_exist() -> None:
    selection = toolchain.select_candidate([], None)

    assert selection.active is None
    assert selection.candidates == ()
    assert selection.reason == "No libclang libraries were detected."


def test_select_candidate_uses_valid_persisted_preference() -> None:
    detected = [toolchain.Candidate("/llvm/one/libclang.so", "one"),
                toolchain.Candidate("/llvm/two/libclang.so", "two")]

    selection = toolchain.select_candidate(detected, "/llvm/two/libclang.so")

    assert selection.active == detected[1]
    assert selection.preferred_path == detected[1].path
    assert selection.reason == "Using the developer-selected libclang library."


def test_select_candidate_stale_preference_degrades_to_automatic_detection() -> None:
    detected = [toolchain.Candidate("/llvm/current/libclang.so", "linux")]

    selection = toolchain.select_candidate(detected, "/llvm/gone/libclang.so")

    assert selection.active == detected[0]
    assert selection.preferred_path == "/llvm/gone/libclang.so"
    assert selection.reason == (
        "The preferred libclang library /llvm/gone/libclang.so is no longer detected; "
        "automatically selected /llvm/current/libclang.so."
    )


def test_select_candidate_automatic_fallback_uses_first_detected_candidate() -> None:
    detected = [toolchain.Candidate("/llvm/new/libclang.so", "linux"),
                toolchain.Candidate("/llvm/old/libclang.so", "wheel")]

    selection = toolchain.select_candidate(detected, None)

    assert selection.active == detected[0]
    assert selection.reason == "Automatically selected the first detected libclang library."
