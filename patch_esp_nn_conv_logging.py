"""
PlatformIO pre-build script: inject diagnostic MicroPrintf before every
esp_nn_conv_s8() call in esp-tflite-micro's Conv kernel.

Purpose: when the patch_esp_nn_conv.py workaround is OFF and ESP-NN Conv
is active, BC-ResNet aborts in conv.cc somewhere on the first Invoke.
The Backtrace gives us the source line of the *next* statement after
the crash, which is symbolically attributed to conv.cc:291 (TFLITE_DCHECK)
— but the real crash site is inside esp_nn_conv_s8 itself, on a specific
Conv layer shape.

This patch logs the input/filter/output dims + stride/padding *before*
each esp_nn_conv_s8 call. The last log line emitted before the abort()
identifies the layer that triggers the bug.

Once we know that layer's shape, we can either:
  - Write a more targeted patch that falls back to the reference impl
    only for the matching shape, keeping ESP-NN acceleration for the
    rest of the model.
  - File a precise upstream bug report.

This script is for diagnostic use only. Activate by adding to the device
YAML's extra_scripts AND removing patch_esp_nn_conv.py from the same list
(the call to esp_nn_conv_s8 must actually happen for the log to fire).
"""
import glob
import os
import re

Import("env")  # noqa: F821

MARKER = "// [DIAG] ESP-NN Conv shape logging injected"
CMAKE_SCRIPT = "patch_esp_nn_conv_logging.cmake"

# Inject a MicroPrintf at the *earliest safe point* in EvalQuantizedPerChannel:
# right after the four RuntimeShape vars are populated, but BEFORE any
# Dims(N) access or DCHECK_EQ on DimensionsCount(). v1.3.4's body in the
# `if (dilation_*_factor == 1 ...)` branch does:
#
#   RuntimeShape filter_shape = ...;
#   RuntimeShape input_shape  = ...;
#   RuntimeShape output_shape = ...;
#   RuntimeShape bias_shape   = ...;      <-- inject right after this
#   const int8_t *input_data  = ...;
#   ...
#   const int input_height    = input_shape.Dims(1);   <-- crashes if <3D
#   ...
#   TFLITE_DCHECK_EQ(input_shape.DimensionsCount(), 4);  <-- crashes if !=4
#
# Logging just the four dimension counts is cheap (4 args, short fmt) so
# it fits inside the 8 KB mww-task stack we've already bumped to.
LOG_INSERT = """\
    // [DIAG] ESP-NN Conv shape logging injected
    static int conv_n = 0;
    conv_n++;
    MicroPrintf("[D]Q#%d i=%d f=%d o=%d b=%d", conv_n,
                input_shape.DimensionsCount(),
                filter_shape.DimensionsCount(),
                output_shape.DimensionsCount(),
                bias_shape.DimensionsCount());

    """


def patch_source_file(filepath):
    with open(filepath, "r") as f:
        content = f.read()

    if MARKER in content:
        print(f"[patch-esp-nn-conv-logging] Already patched: {filepath}")
        return False

    # Match the for-loop line uniquely. esp_nn EvalQuantizedPerChannel has
    # `    for (int i_batch = 0; i_batch < batch_size; ...` directly before
    # the esp_nn_conv_s8 call.
    patched, n = re.subn(
        r"(\n    for \(int i_batch = 0; i_batch < batch_size;)",
        "\n    " + MARKER + "\n" + LOG_INSERT + r"\1",
        content,
        count=1,
    )

    if n == 0:
        print(f"[patch-esp-nn-conv-logging] WARNING: for-loop anchor not found in {filepath}")
        return False

    with open(filepath, "w") as f:
        f.write(patched)
    print(f"[patch-esp-nn-conv-logging] Injected diagnostic log into {filepath}")
    return True


def invalidate_object_cache(source_path, project_dir):
    rel = os.path.relpath(source_path, project_dir)
    pioenvs = os.path.join(project_dir, ".pioenvs")
    if not os.path.isdir(pioenvs):
        return
    for env_dir in os.listdir(pioenvs):
        obj_path = os.path.join(pioenvs, env_dir, rel + ".o")
        if os.path.isfile(obj_path):
            if os.path.getmtime(obj_path) < os.path.getmtime(source_path):
                os.remove(obj_path)
                print(f"[patch-esp-nn-conv-logging] Removed stale object: {obj_path}")


def patch_if_exists(project_dir):
    pattern = os.path.join(
        project_dir, "managed_components", "espressif__esp-tflite-micro",
        "tensorflow", "lite", "micro", "kernels", "esp_nn", "conv.cc",
    )
    for filepath in glob.glob(pattern):
        if patch_source_file(filepath):
            invalidate_object_cache(filepath, project_dir)


def inject_cmake_include(project_dir):
    cmake_patch = os.path.abspath(os.path.join(project_dir, "..", "..", "..", CMAKE_SCRIPT))

    if not os.path.isfile(cmake_patch):
        print(f"[patch-esp-nn-conv-logging] WARNING: {cmake_patch} not found")
        return

    cmake_lists = os.path.join(project_dir, "CMakeLists.txt")
    if os.path.isfile(cmake_lists):
        with open(cmake_lists, "r") as f:
            content = f.read()
        if CMAKE_SCRIPT in content:
            return
        with open(cmake_lists, "a") as f:
            f.write(f'\n# ESP-NN Conv diagnostic logging — injected by patch_esp_nn_conv_logging.py\n')
            f.write(f'include("{cmake_patch}")\n')
        print(f"[patch-esp-nn-conv-logging] Injected cmake include into CMakeLists.txt")


project_dir = env.subst("$PROJECT_DIR")
patch_if_exists(project_dir)
inject_cmake_include(project_dir)
