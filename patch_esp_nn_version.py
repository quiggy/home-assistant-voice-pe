"""
PlatformIO pre-build script: pin espressif/esp-nn to a specific version.

ESPHome's stock micro_wake_word/__init__.py pins esp-nn to 1.1.2 via PR #15703
(VAD regression mitigation on 1.2.x). This script overrides that pin by
rewriting the version constraint in <PROJECT_DIR>/src/idf_component.yml
between ESPHome's codegen and the IDF Component Manager's resolve step.

Same mechanism as patch_esp_tflite_micro_version.py — just for a different
component. Both scripts can be active simultaneously; they operate on
different sections of the same yml.

WARNING: ESPHome explicitly pins esp-nn at 1.1.2 because newer 1.2.x esp-nn
versions broke VAD inference on prior builds. Activating this pin means
you accept the risk of re-introducing that regression unless you've
re-verified VAD on the target version. Test with a VAD-enabled YAML
(e.g. hey_luna_v3 + vad model) before shipping.

Companion: patch_esp_nn_version.cmake (for clean builds).
"""
import os
import re
import shutil

Import("env")  # noqa: F821 — PlatformIO injects this

TARGET_VERSION = "1.2.3"
COMPONENT_NAME = "espressif/esp-nn"
CMAKE_SCRIPT = "patch_esp_nn_version.cmake"

COMPONENT_BLOCK_RE = re.compile(
    rf"(^[ \t]*{re.escape(COMPONENT_NAME)}:\s*\n[ \t]+version:\s*)([^\s#]+)",
    re.MULTILINE,
)


def patch_idf_component_yml(project_dir):
    yml_path = os.path.join(project_dir, "src", "idf_component.yml")
    if not os.path.isfile(yml_path):
        print(f"[pin-esp-nn] {yml_path} not found yet — cmake hook will retry")
        return None

    with open(yml_path, "r") as f:
        content = f.read()

    match = COMPONENT_BLOCK_RE.search(content)
    if not match:
        print(f"[pin-esp-nn] WARNING: {COMPONENT_NAME} not declared in {yml_path}")
        return False

    current_version = match.group(2)
    if current_version == TARGET_VERSION:
        print(f"[pin-esp-nn] Already at {TARGET_VERSION}, nothing to do")
        return False

    new_content = COMPONENT_BLOCK_RE.sub(
        lambda m: m.group(1) + TARGET_VERSION,
        content,
        count=1,
    )

    with open(yml_path, "w") as f:
        f.write(new_content)
    print(f"[pin-esp-nn] Pinned {COMPONENT_NAME}: {current_version} -> {TARGET_VERSION}")
    return True


def invalidate_caches(project_dir):
    """Force IDF Component Manager to re-resolve and re-download esp-nn."""
    lock = os.path.join(project_dir, "dependencies.lock")
    if os.path.isfile(lock):
        os.remove(lock)
        print(f"[pin-esp-nn] Removed {lock}")

    comp_dir = os.path.join(project_dir, "managed_components", "espressif__esp-nn")
    if os.path.isdir(comp_dir):
        shutil.rmtree(comp_dir)
        print(f"[pin-esp-nn] Removed {comp_dir}")


def inject_cmake_include(project_dir):
    """Inject patch_esp_nn_version.cmake via cmake_extra_args for clean builds."""
    cmake_patch = os.path.abspath(os.path.join(project_dir, "..", "..", "..", CMAKE_SCRIPT))

    if not os.path.isfile(cmake_patch):
        print(f"[pin-esp-nn] WARNING: {cmake_patch} not found, skipping cmake injection")
        return

    cmake_lists = os.path.join(project_dir, "CMakeLists.txt")
    if os.path.isfile(cmake_lists):
        with open(cmake_lists, "r") as f:
            content = f.read()
        if CMAKE_SCRIPT in content:
            return
        with open(cmake_lists, "a") as f:
            f.write(f'\n# esp-nn version pin — injected by patch_esp_nn_version.py\n')
            f.write(f'include("{cmake_patch}")\n')
        print(f"[pin-esp-nn] Injected cmake include into CMakeLists.txt")
    else:
        cmake_arg = f"-DCMAKE_PROJECT_INCLUDE={cmake_patch}"
        try:
            existing = env.GetProjectOption("board_build.cmake_extra_args", [])
            if isinstance(existing, str):
                existing = [existing] if existing else []
            if cmake_arg not in existing:
                existing.append(cmake_arg)
                env.SetProjectOption("board_build.cmake_extra_args", existing)
                print(f"[pin-esp-nn] Set CMAKE_PROJECT_INCLUDE via cmake_extra_args (clean build)")
        except Exception as e:
            print(f"[pin-esp-nn] WARNING: Could not set cmake_extra_args: {e}")


project_dir = env.subst("$PROJECT_DIR")
result = patch_idf_component_yml(project_dir)
if result is True:
    invalidate_caches(project_dir)
inject_cmake_include(project_dir)
