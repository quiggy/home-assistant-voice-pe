"""
PlatformIO pre-build script: Patch ESP-NN Conv2D kernel.

Disables the ESP-NN optimized Conv2D int8 path. The BC-ResNet smoke-test model
crashes inside esp_nn_conv_s8() during the first Invoke() on ESP32-S3:
  tflite::Eval at esp_nn/conv.cc:291 (Conv2D abort)

Mirrors patch_esp_nn_fc.py exactly. The reference int8 ConvPerChannel kernel
in the #else branch works correctly.

This patch is needed for esp-tflite-micro <= v1.3.3.1 (bundled with ESPHome
<= 2026.3.3). It can be removed once esp-tflite-micro / esp-nn ships a fix.

Strategy:
  1. If managed_components already exist (incremental build), patch the source directly.
  2. Inject an include(patch_esp_nn_conv.cmake) into the generated CMakeLists.txt.
     The cmake script runs AFTER project() downloads managed_components, so it
     handles the first clean build where the source doesn't exist yet.
"""
import glob
import os
import re

Import("env")  # noqa: F821 — PlatformIO injects this

MARKER = "// [PATCHED] ESP-NN Conv disabled for BC-ResNet compatibility"
CMAKE_SCRIPT = "patch_esp_nn_conv.cmake"


def patch_source_file(filepath):
    """Patch a single conv.cc file. Returns True if patched."""
    with open(filepath, "r") as f:
        content = f.read()

    if MARKER in content:
        print(f"[patch-esp-nn-conv] Already patched: {filepath}")
        return False

    patched = re.sub(
        r"#if ESP_NN([ \t]*\n)",
        r"#if 0  " + MARKER + r"\1",
        content,
    )

    if patched == content:
        print(f"[patch-esp-nn-conv] WARNING: Pattern not found in {filepath}")
        return False

    with open(filepath, "w") as f:
        f.write(patched)
    print(f"[patch-esp-nn-conv] Patched: {filepath}")
    return True


def invalidate_object_cache(source_path, project_dir):
    """Delete the cached .o if it's older than the source, forcing PlatformIO to recompile."""
    rel = os.path.relpath(source_path, project_dir)
    pioenvs = os.path.join(project_dir, ".pioenvs")
    if not os.path.isdir(pioenvs):
        return
    for env_dir in os.listdir(pioenvs):
        obj_path = os.path.join(pioenvs, env_dir, rel + ".o")
        if os.path.isfile(obj_path):
            if os.path.getmtime(obj_path) < os.path.getmtime(source_path):
                os.remove(obj_path)
                print(f"[patch-esp-nn-conv] Deleted stale object: {obj_path}")


def patch_if_exists(project_dir):
    """Try to patch managed_components source directly (works for incremental builds)."""
    pattern = os.path.join(
        project_dir, "managed_components", "espressif__esp-tflite-micro",
        "tensorflow", "lite", "micro", "kernels", "esp_nn", "conv.cc",
    )
    for filepath in glob.glob(pattern):
        patch_source_file(filepath)
        invalidate_object_cache(filepath, project_dir)


def inject_cmake_include(project_dir):
    """Ensure patch_esp_nn_conv.cmake runs during cmake configure (after managed_components download)."""
    cmake_patch = os.path.abspath(os.path.join(project_dir, "..", "..", "..", CMAKE_SCRIPT))

    if not os.path.isfile(cmake_patch):
        print(f"[patch-esp-nn-conv] WARNING: {cmake_patch} not found, skipping cmake injection")
        return

    cmake_lists = os.path.join(project_dir, "CMakeLists.txt")

    if os.path.isfile(cmake_lists):
        with open(cmake_lists, "r") as f:
            content = f.read()

        if CMAKE_SCRIPT in content:
            return

        with open(cmake_lists, "a") as f:
            f.write(f'\n# ESP-NN Conv patch — injected by patch_esp_nn_conv.py\n')
            f.write(f'include("{cmake_patch}")\n')
        print(f"[patch-esp-nn-conv] Injected cmake include into CMakeLists.txt")
    else:
        cmake_arg = f"-DCMAKE_PROJECT_INCLUDE={cmake_patch}"
        try:
            existing = env.GetProjectOption("board_build.cmake_extra_args", [])
            if isinstance(existing, str):
                existing = [existing] if existing else []
            if cmake_arg not in existing:
                existing.append(cmake_arg)
                env.SetProjectOption("board_build.cmake_extra_args", existing)
                print(f"[patch-esp-nn-conv] Set CMAKE_PROJECT_INCLUDE via cmake_extra_args (clean build)")
        except Exception as e:
            print(f"[patch-esp-nn-conv] WARNING: Could not set cmake_extra_args: {e}")


project_dir = env.subst("$PROJECT_DIR")
patch_if_exists(project_dir)
inject_cmake_include(project_dir)
