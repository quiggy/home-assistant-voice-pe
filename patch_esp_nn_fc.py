"""
PlatformIO pre-build script: Patch ESP-NN FullyConnected kernel.

Disables the ESP-NN optimized FullyConnected int8 path which produces incorrect
inference results for the micro_wake_word VAD model on ESP32-S3.

See ESP-NN-FC-BUG.md for full details.
See https://github.com/espressif/esp-tflite-micro/issues/108

This patch is needed for esp-tflite-micro <= v1.3.3.1 (bundled with ESPHome <= 2026.3.3).
It can be removed once ESPHome upgrades to esp-tflite-micro >= v1.3.4.

Strategy:
  1. If managed_components already exist (incremental build), patch the source directly.
  2. Inject an include(patch_esp_nn_fc.cmake) into the generated CMakeLists.txt.
     The cmake script runs AFTER project() downloads managed_components, so it
     handles the first clean build where the source doesn't exist yet.
"""
import glob
import os
import re

Import("env")  # noqa: F821 — PlatformIO injects this

MARKER = "// [PATCHED] ESP-NN FC disabled for VAD compatibility"
CMAKE_SCRIPT = "patch_esp_nn_fc.cmake"


def patch_source_file(filepath):
    """Patch a single fully_connected.cc file. Returns True if patched."""
    with open(filepath, "r") as f:
        content = f.read()

    if MARKER in content:
        print(f"[patch-esp-nn-fc] Already patched: {filepath}")
        return False

    patched = re.sub(
        r"(case kTfLiteInt8:\s*\{\s*\n)\s*#if ESP_NN\b",
        r"\g<1>"
        + f"#if 0  {MARKER}\n"
        + "          // ESP-NN esp_nn_fully_connected_s8() produces wrong results for VAD model.\n"
        + "          // Forcing reference implementation. See ESP-NN-FC-BUG.md\n"
        + "#elif ESP_NN",
        content,
        count=1,
    )

    if patched == content:
        print(f"[patch-esp-nn-fc] WARNING: Pattern not found in {filepath}")
        return False

    with open(filepath, "w") as f:
        f.write(patched)
    print(f"[patch-esp-nn-fc] Patched: {filepath}")
    return True


def patch_if_exists(project_dir):
    """Try to patch managed_components source directly (works for incremental builds)."""
    pattern = os.path.join(
        project_dir, "managed_components", "espressif__esp-tflite-micro",
        "tensorflow", "lite", "micro", "kernels", "esp_nn", "fully_connected.cc",
    )
    for filepath in glob.glob(pattern):
        patch_source_file(filepath)


def inject_cmake_include(project_dir):
    """Append include(patch_esp_nn_fc.cmake) to CMakeLists.txt for first-build patching."""
    cmake_lists = os.path.join(project_dir, "CMakeLists.txt")
    cmake_patch = os.path.abspath(os.path.join(project_dir, "..", "..", "..", CMAKE_SCRIPT))

    if not os.path.isfile(cmake_patch):
        print(f"[patch-esp-nn-fc] WARNING: {cmake_patch} not found, skipping cmake injection")
        return

    with open(cmake_lists, "r") as f:
        content = f.read()

    if CMAKE_SCRIPT in content:
        return  # already injected (shouldn't happen since ESPHome regenerates, but safe)

    with open(cmake_lists, "a") as f:
        f.write(f'\n# ESP-NN FC patch — injected by patch_esp_nn_fc.py\n')
        f.write(f'include("{cmake_patch}")\n')
    print(f"[patch-esp-nn-fc] Injected cmake include: {cmake_patch}")


project_dir = env.subst("$PROJECT_DIR")

# 1. Patch source directly if it already exists (incremental builds)
patch_if_exists(project_dir)

# 2. Inject cmake include so the patch also applies on clean builds
#    (cmake runs project() which downloads components, then our include patches them)
inject_cmake_include(project_dir)
