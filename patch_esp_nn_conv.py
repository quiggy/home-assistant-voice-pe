"""
PlatformIO pre-build script: Patch ESP-NN Conv2D kernel.

Disables the ESP-NN optimized Conv2D int8 path. The BC-ResNet smoke-test model
crashes inside esp_nn_conv_s8() during the first Invoke() on ESP32-S3:
  tflite::Eval at esp_nn/conv.cc:291 (Conv2D abort)

Mirrors patch_esp_nn_fc.py exactly. The reference int8 ConvPerChannel kernel
in the #else branch works correctly.

Originally needed for esp-tflite-micro <= v1.3.3.1 (bundled with ESPHome
<= 2026.3.3). On v1.3.4 + esp-nn 1.2.3 the patch is no longer required for
BC-ResNet's shapes (kept as a safety net for other models, see analysis below).

------------------------------------------------------------------------------
Root cause analysis (avoid hitting this again)
------------------------------------------------------------------------------

The abort is NOT in esp-tflite-micro's wrapper. The wrapper file
  tensorflow/lite/micro/kernels/esp_nn/conv.cc:291
is only a DCHECK on node->builtin_data — the actual crash cascades from
the esp-nn assembly kernel that the wrapper then invokes.

The dispatcher lives in esp-nn at:
  src/convolution/esp_nn_conv_esp32s3.c :: esp_nn_conv_s8_esp32s3()

It selects one of four kernels based on filter shape and in_channels:

  1. 1x1 stride-1 pad-0, channels % 8 == 0
     → esp_nn_conv_s8_mult8_1x1_esp32s3() — full asm, strict alignment.
       Asserts 8-byte aligned filter + channels multiple of 8.

  2. 1x1 stride-1 pad-0, channels % 8 != 0
     → esp_nn_conv_s8_1x1() — C+SIMD fallback, accepts any alignment.

  3. filter_wd * in_ch < 16 AND filter_wd*filter_ht*in_ch >= 16
     → esp_nn_conv_s8_im2col_s3() — NEW in esp-nn 1.2.3. Per-pixel
       im2col into scratch, ACCX dot product. Used by BC-ResNet's
       early convs with in_ch < 16.

  4. Everything else (3x3, 5x5, etc with larger in_ch)
     → esp_nn_conv_s8_filter_aligned_input_padded_esp32s3() — general
       path. Pads filter to 16-byte rows + pads input. This is the
       fragile kernel.

  5. Grouped conv (filter_dims->channels != input_dims->channels)
     → falls back to esp_nn_conv_s8_ansi() reference.

Notable: Espressif themselves disable the dedicated 3x3 fast path at
esp_nn_conv_esp32s3.c:463 (#if 0) with the comment
  "TODO: fix inline asm priming + performance regression before enabling."
So even the upstream library admits part of the SIMD Conv stack is
unstable.

The Conv2D abort observed on BC-ResNet under v1.3.3.1 came from path 4
(the general aligned/padded kernel) with shapes whose
  filter_alignment_padding + boundary_padding
exceeded scratch_buffer's allocation or violated assembly alignment
preconditions. The scratch size is computed in
esp_nn_get_conv_scratch_size_esp32s3() — but its formula and the
kernel's actual write pattern have historically drifted out of sync
when new alignment cases are added.

------------------------------------------------------------------------------
Practical rules to avoid the abort
------------------------------------------------------------------------------

When converting / quantising a model destined for esp-nn:

* Prefer Conv2D filter shapes 1x1, 1x3, 3x1, 3x3, 5x5.
* Keep input channel counts at multiples of 4 (8 is even better — unlocks
  path 1 for 1x1 convs).
* Avoid grouped convolutions (they bypass SIMD entirely — path 5).
* Avoid dilation > 1 (esp-tflite-micro's wrapper falls back to reference
  on any dilation != 1 — see EvalQuantizedPerChannel guard at conv.cc:181).
* If a model crashes only on the first Invoke(): suspect path 4 + an
  edge-case padding shape. Re-enable this patch as the safety net, file
  the shape upstream, and pick a different layer geometry if you need SIMD.

------------------------------------------------------------------------------

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
