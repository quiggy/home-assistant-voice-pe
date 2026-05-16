"""
PlatformIO pre-build script: pin espressif/esp-tflite-micro to a specific version.

ESPHome's stock micro_wake_word/__init__.py calls
  esp32.add_idf_component(name="espressif/esp-tflite-micro", ref="1.3.3~1")
which lands in the project's generated <PROJECT_DIR>/src/idf_component.yml as

    espressif/esp-tflite-micro:
      version: 1.3.3~1

This script runs as a PlatformIO pre-build hook *after* ESPHome writes that
file but *before* the IDF Component Manager downloads dependencies. We rewrite
the version constraint, then invalidate dependencies.lock and any previously
downloaded copy so Component Manager re-resolves and re-fetches.

Why this approach: ESPHome offers no first-class way to override a component's
pinned ref. Modifying ESPHome sources inside the Docker image is volatile.
Patching the generated idf_component.yml is the cleanest hook point because
the file lives in the project tree (persistent across rebuilds) and is read
exactly once per build by Component Manager.

Companion: patch_esp_tflite_micro_version.cmake (for clean builds where the
yml may not yet exist when this script first runs).
"""
import os
import re
import shutil

Import("env")  # noqa: F821 — PlatformIO injects this

TARGET_VERSION = "1.3.4"
COMPONENT_NAME = "espressif/esp-tflite-micro"
CMAKE_SCRIPT = "patch_esp_tflite_micro_version.cmake"

# Match the component block exactly: name on its own line, then an indented
# `version:` line. Used in re.MULTILINE so ^ anchors to line starts.
COMPONENT_BLOCK_RE = re.compile(
    rf"(^[ \t]*{re.escape(COMPONENT_NAME)}:\s*\n[ \t]+version:\s*)([^\s#]+)",
    re.MULTILINE,
)


def patch_idf_component_yml(project_dir):
    yml_path = os.path.join(project_dir, "src", "idf_component.yml")
    if not os.path.isfile(yml_path):
        print(f"[pin-esp-tflite-micro] {yml_path} not found yet — cmake hook will retry")
        return None

    with open(yml_path, "r") as f:
        content = f.read()

    match = COMPONENT_BLOCK_RE.search(content)
    if not match:
        print(f"[pin-esp-tflite-micro] WARNING: {COMPONENT_NAME} not declared in {yml_path}")
        return False

    current_version = match.group(2)
    if current_version == TARGET_VERSION:
        print(f"[pin-esp-tflite-micro] Already at {TARGET_VERSION}, nothing to do")
        return False

    new_content = COMPONENT_BLOCK_RE.sub(
        lambda m: m.group(1) + TARGET_VERSION,
        content,
        count=1,
    )

    with open(yml_path, "w") as f:
        f.write(new_content)
    print(f"[pin-esp-tflite-micro] Pinned {COMPONENT_NAME}: {current_version} -> {TARGET_VERSION}")
    return True


def invalidate_caches(project_dir):
    """Force IDF Component Manager to re-resolve and re-download esp-tflite-micro."""
    lock = os.path.join(project_dir, "dependencies.lock")
    if os.path.isfile(lock):
        os.remove(lock)
        print(f"[pin-esp-tflite-micro] Removed {lock}")

    comp_dir = os.path.join(project_dir, "managed_components", "espressif__esp-tflite-micro")
    if os.path.isdir(comp_dir):
        shutil.rmtree(comp_dir)
        print(f"[pin-esp-tflite-micro] Removed {comp_dir}")


def inject_cmake_include(project_dir):
    """Inject patch_esp_tflite_micro_version.cmake via cmake_extra_args for clean builds."""
    cmake_patch = os.path.abspath(os.path.join(project_dir, "..", "..", "..", CMAKE_SCRIPT))

    if not os.path.isfile(cmake_patch):
        print(f"[pin-esp-tflite-micro] WARNING: {cmake_patch} not found, skipping cmake injection")
        return

    cmake_lists = os.path.join(project_dir, "CMakeLists.txt")
    if os.path.isfile(cmake_lists):
        with open(cmake_lists, "r") as f:
            content = f.read()
        if CMAKE_SCRIPT in content:
            return
        with open(cmake_lists, "a") as f:
            f.write(f'\n# esp-tflite-micro version pin — injected by patch_esp_tflite_micro_version.py\n')
            f.write(f'include("{cmake_patch}")\n')
        print(f"[pin-esp-tflite-micro] Injected cmake include into CMakeLists.txt")
    else:
        cmake_arg = f"-DCMAKE_PROJECT_INCLUDE={cmake_patch}"
        try:
            existing = env.GetProjectOption("board_build.cmake_extra_args", [])
            if isinstance(existing, str):
                existing = [existing] if existing else []
            if cmake_arg not in existing:
                existing.append(cmake_arg)
                env.SetProjectOption("board_build.cmake_extra_args", existing)
                print(f"[pin-esp-tflite-micro] Set CMAKE_PROJECT_INCLUDE via cmake_extra_args (clean build)")
        except Exception as e:
            print(f"[pin-esp-tflite-micro] WARNING: Could not set cmake_extra_args: {e}")


project_dir = env.subst("$PROJECT_DIR")
result = patch_idf_component_yml(project_dir)
if result is True:
    invalidate_caches(project_dir)
inject_cmake_include(project_dir)
