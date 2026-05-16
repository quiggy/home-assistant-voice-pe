"""
PlatformIO pre-build script: strip the dead `-std=c++11` flag from
esp-tflite-micro's CMakeLists.txt so newer kernels that use C++14 syntax
(digit separators like 0x8000'0000) can compile.

esp-tflite-micro's CMakeLists.txt at v1.3.4/v1.3.5 contains *two* -std=
flags on the C++ compile options line:

    target_compile_options(${COMPONENT_LIB} PRIVATE $<$<COMPILE_LANGUAGE:CXX>:
                                          ${common_flags} -std=c++11 -fno-rtti -fno-exceptions
                                          -fno-threadsafe-statics -Werror -Wno-return-type
                                          -Wno-strict-aliasing -std=gnu++14 >)

GCC's "last -std= wins" rule should pick gnu++14, but in some build paths
the c++11 flag prevails (suspected: ESP-IDF/PlatformIO flag-ordering quirk).
v1.3.5 introduces decode_state_huffman.h / decode_state.cc which use the
C++14 digit-separator syntax — when c++11 is effective, they fail to parse:

    error: expected ';' at end of member declaration
       47 |   static constexpr uint32_t kTable32BitSymbolFoundMask = 0x8000'0000;

This patch removes the dead c++11 flag, leaving only gnu++14 active.
"""
import glob
import os
import re

Import("env")  # noqa: F821

MARKER = "# [PATCHED] dead -std=c++11 stripped for C++14 kernel support"
CMAKE_SCRIPT = "patch_esp_tflite_micro_cppstd.cmake"


def patch_source_file(filepath):
    with open(filepath, "r") as f:
        content = f.read()

    if MARKER in content:
        print(f"[patch-tflite-cppstd] Already patched: {filepath}")
        return False

    # Strip a leading "-std=c++11 " from the multi-line CXX options block.
    patched = re.sub(
        r"-std=c\+\+11 ",
        "",
        content,
        count=1,
    )

    if patched == content:
        print(f"[patch-tflite-cppstd] WARNING: -std=c++11 not found in {filepath}")
        return False

    # Add marker as a comment so we can detect already-patched
    patched = patched.replace(
        "# enable ESP-NN optimizations by Espressif",
        MARKER + "\n# enable ESP-NN optimizations by Espressif",
        1,
    )

    with open(filepath, "w") as f:
        f.write(patched)
    print(f"[patch-tflite-cppstd] Patched: {filepath}")
    return True


def invalidate_object_cache(source_path, project_dir):
    pioenvs = os.path.join(project_dir, ".pioenvs")
    if not os.path.isdir(pioenvs):
        return
    # Force re-link of esp-tflite-micro lib so new flags take effect.
    for env_dir in os.listdir(pioenvs):
        lib_glob = os.path.join(
            pioenvs, env_dir, "managed_components", "espressif__esp-tflite-micro", "**", "*.o"
        )
        for obj_path in glob.glob(lib_glob, recursive=True):
            os.remove(obj_path)
        archive = os.path.join(pioenvs, env_dir, "libespressif__esp-tflite-micro.a")
        if os.path.isfile(archive):
            os.remove(archive)
            print(f"[patch-tflite-cppstd] Removed stale archive: {archive}")


def patch_if_exists(project_dir):
    pattern = os.path.join(
        project_dir, "managed_components", "espressif__esp-tflite-micro", "CMakeLists.txt"
    )
    for filepath in glob.glob(pattern):
        if patch_source_file(filepath):
            invalidate_object_cache(filepath, project_dir)


def inject_cmake_include(project_dir):
    cmake_patch = os.path.abspath(os.path.join(project_dir, "..", "..", "..", CMAKE_SCRIPT))

    if not os.path.isfile(cmake_patch):
        print(f"[patch-tflite-cppstd] WARNING: {cmake_patch} not found")
        return

    cmake_lists = os.path.join(project_dir, "CMakeLists.txt")
    if os.path.isfile(cmake_lists):
        with open(cmake_lists, "r") as f:
            content = f.read()
        if CMAKE_SCRIPT in content:
            return
        with open(cmake_lists, "a") as f:
            f.write(f'\n# esp-tflite-micro C++ std cleanup — injected by patch_esp_tflite_micro_cppstd.py\n')
            f.write(f'include("{cmake_patch}")\n')
        print(f"[patch-tflite-cppstd] Injected cmake include into CMakeLists.txt")
    else:
        cmake_arg = f"-DCMAKE_PROJECT_INCLUDE={cmake_patch}"
        try:
            existing = env.GetProjectOption("board_build.cmake_extra_args", [])
            if isinstance(existing, str):
                existing = [existing] if existing else []
            if cmake_arg not in existing:
                existing.append(cmake_arg)
                env.SetProjectOption("board_build.cmake_extra_args", existing)
                print(f"[patch-tflite-cppstd] Set CMAKE_PROJECT_INCLUDE via cmake_extra_args")
        except Exception as e:
            print(f"[patch-tflite-cppstd] WARNING: Could not set cmake_extra_args: {e}")


project_dir = env.subst("$PROJECT_DIR")
patch_if_exists(project_dir)
inject_cmake_include(project_dir)
