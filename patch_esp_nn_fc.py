"""
PlatformIO pre-build script: Patch ESP-NN FullyConnected kernel.

Disables the ESP-NN optimized FullyConnected int8 path which produces incorrect
inference results for the micro_wake_word VAD model on ESP32-S3.

See ESP-NN-FC-BUG.md for full details.
See https://github.com/espressif/esp-tflite-micro/issues/108

This patch is needed for esp-tflite-micro <= v1.3.3.1 (bundled with ESPHome <= 2026.3.3).
It can be removed once ESPHome upgrades to esp-tflite-micro >= v1.3.4.
"""
import glob
import os
import re

Import("env")  # noqa: F821 — PlatformIO injects this

MARKER = "// [PATCHED] ESP-NN FC disabled for VAD compatibility"


def patch_fully_connected(source, env):
    """Find and patch all esp_nn/fully_connected.cc files in managed_components."""
    project_dir = env.subst("$PROJECT_DIR")
    pattern = os.path.join(
        project_dir,
        "managed_components",
        "espressif__esp-tflite-micro",
        "tensorflow",
        "lite",
        "micro",
        "kernels",
        "esp_nn",
        "fully_connected.cc",
    )
    matches = glob.glob(pattern)
    if not matches:
        print(f"[patch-esp-nn-fc] WARNING: No fully_connected.cc found at {pattern}")
        return

    for filepath in matches:
        with open(filepath, "r") as f:
            content = f.read()

        # Already patched?
        if MARKER in content:
            print(f"[patch-esp-nn-fc] Already patched: {filepath}")
            continue

        # Replace '#if ESP_NN' in the kTfLiteInt8 case with '#if 0'
        # The pattern: 'case kTfLiteInt8: {\n#if ESP_NN'
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
            continue

        with open(filepath, "w") as f:
            f.write(patched)
        print(f"[patch-esp-nn-fc] Patched: {filepath}")


# Run the patch immediately at script load time.
# At this point managed_components should already be downloaded by the IDF component
# manager (which runs before PlatformIO extra_scripts on incremental builds).
#
# NOTE: On a fully clean build (no managed_components yet), this will log a warning
# and skip patching. The IDF component manager downloads managed_components during the
# CMake configuration phase that follows. On the next compile (incremental), this
# script will find and patch the file, and CMake/ninja will recompile just that file.
# In practice, clean builds are rare — this auto-heals on the second compile.
patch_fully_connected(None, env)
