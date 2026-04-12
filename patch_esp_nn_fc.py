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
        r"(#if) ESP_NN\b([ \t]*\n(?: *//[^\n]*\n)* *(?:const RuntimeShape& filter_shape))",
        r"\g<1> 0  " + MARKER + r"\g<2>",
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


def invalidate_object_cache(source_path, project_dir):
    """Delete the cached .o if it's older than the source, forcing PlatformIO to recompile."""
    # .o lives under .pioenvs/<env>/ mirroring the source tree relative to project_dir
    rel = os.path.relpath(source_path, project_dir)
    pioenvs = os.path.join(project_dir, ".pioenvs")
    if not os.path.isdir(pioenvs):
        return
    for env_dir in os.listdir(pioenvs):
        obj_path = os.path.join(pioenvs, env_dir, rel + ".o")
        if os.path.isfile(obj_path):
            if os.path.getmtime(obj_path) < os.path.getmtime(source_path):
                os.remove(obj_path)
                print(f"[patch-esp-nn-fc] Deleted stale object: {obj_path}")


def patch_if_exists(project_dir):
    """Try to patch managed_components source directly (works for incremental builds)."""
    pattern = os.path.join(
        project_dir, "managed_components", "espressif__esp-tflite-micro",
        "tensorflow", "lite", "micro", "kernels", "esp_nn", "fully_connected.cc",
    )
    for filepath in glob.glob(pattern):
        patch_source_file(filepath)
        invalidate_object_cache(filepath, project_dir)


def inject_cmake_include(project_dir):
    """Ensure patch_esp_nn_fc.cmake runs during cmake configure (after managed_components download).

    Method 1: Append include() to CMakeLists.txt (works on incremental builds).
    Method 2: Set CMAKE_PROJECT_INCLUDE via board_build.cmake_extra_args (works on clean builds
              where CMakeLists.txt doesn't exist yet when this pre-script runs).
    """
    cmake_patch = os.path.abspath(os.path.join(project_dir, "..", "..", "..", CMAKE_SCRIPT))

    if not os.path.isfile(cmake_patch):
        print(f"[patch-esp-nn-fc] WARNING: {cmake_patch} not found, skipping cmake injection")
        return

    cmake_lists = os.path.join(project_dir, "CMakeLists.txt")

    if os.path.isfile(cmake_lists):
        # Method 1: CMakeLists.txt exists (incremental build) — inject include directly
        with open(cmake_lists, "r") as f:
            content = f.read()

        if CMAKE_SCRIPT in content:
            return  # already injected

        with open(cmake_lists, "a") as f:
            f.write(f'\n# ESP-NN FC patch — injected by patch_esp_nn_fc.py\n')
            f.write(f'include("{cmake_patch}")\n')
        print(f"[patch-esp-nn-fc] Injected cmake include into CMakeLists.txt")
    else:
        # Method 2: Clean build — CMakeLists.txt doesn't exist yet.
        # Use CMAKE_PROJECT_INCLUDE so cmake runs our patch after project() downloads
        # managed_components.  Passed via board_build.cmake_extra_args.
        cmake_arg = f"-DCMAKE_PROJECT_INCLUDE={cmake_patch}"
        try:
            existing = env.GetProjectOption("board_build.cmake_extra_args", [])
            if isinstance(existing, str):
                existing = [existing] if existing else []
            if cmake_arg not in existing:
                existing.append(cmake_arg)
                env.SetProjectOption("board_build.cmake_extra_args", existing)
                print(f"[patch-esp-nn-fc] Set CMAKE_PROJECT_INCLUDE via cmake_extra_args (clean build)")
        except Exception as e:
            print(f"[patch-esp-nn-fc] WARNING: Could not set cmake_extra_args: {e}")
            print(f"[patch-esp-nn-fc] Run compile again — incremental build will apply the patch")


project_dir = env.subst("$PROJECT_DIR")

# 1. Patch source directly if it already exists (incremental builds)
patch_if_exists(project_dir)

# 2. Inject cmake include so the patch also applies on clean builds
#    (cmake runs project() which downloads components, then our include patches them)
inject_cmake_include(project_dir)
