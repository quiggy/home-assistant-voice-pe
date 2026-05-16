# patch_esp_tflite_micro_version.cmake — Injected via CMAKE_PROJECT_INCLUDE
#
# Re-asserts the version pin in src/idf_component.yml during cmake configure.
# This is the clean-build counterpart to patch_esp_tflite_micro_version.py:
# the Python pre-script may run before ESPHome has written the file on a
# first-ever build, so we rewrite here too — right before project() calls
# the IDF Component Manager.

set(_target_version "1.3.4")
set(_component_name "espressif/esp-tflite-micro")
set(_yml_file "${CMAKE_SOURCE_DIR}/src/idf_component.yml")

if(EXISTS "${_yml_file}")
    file(READ "${_yml_file}" _content)

    # Match e.g.
    #   espressif/esp-tflite-micro:
    #     version: 1.3.3~1
    # Preserve the indent of the version line.
    string(REGEX REPLACE
        "(${_component_name}:[ \t\r\n]+version:[ \t]+)[^\r\n]+"
        "\\1${_target_version}"
        _patched
        "${_content}"
    )

    if(NOT "${_patched}" STREQUAL "${_content}")
        file(WRITE "${_yml_file}" "${_patched}")
        message(STATUS "[pin-esp-tflite-micro] cmake re-asserted ${_component_name} ${_target_version}")

        # Invalidate caches so Component Manager re-resolves.
        if(EXISTS "${CMAKE_SOURCE_DIR}/dependencies.lock")
            file(REMOVE "${CMAKE_SOURCE_DIR}/dependencies.lock")
            message(STATUS "[pin-esp-tflite-micro] Removed dependencies.lock")
        endif()
        if(EXISTS "${CMAKE_SOURCE_DIR}/managed_components/espressif__esp-tflite-micro")
            file(REMOVE_RECURSE "${CMAKE_SOURCE_DIR}/managed_components/espressif__esp-tflite-micro")
            message(STATUS "[pin-esp-tflite-micro] Removed managed_components/espressif__esp-tflite-micro")
        endif()
    endif()
else()
    message(WARNING "[pin-esp-tflite-micro] ${_yml_file} not found at cmake time — check ESPHome codegen ordering")
endif()
