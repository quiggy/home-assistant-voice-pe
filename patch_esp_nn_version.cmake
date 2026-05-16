# patch_esp_nn_version.cmake — Injected via CMAKE_PROJECT_INCLUDE
#
# Re-asserts the esp-nn version pin in src/idf_component.yml during cmake
# configure (clean-build counterpart to patch_esp_nn_version.py).

set(_target_version "1.2.3")
set(_component_name "espressif/esp-nn")
set(_yml_file "${CMAKE_SOURCE_DIR}/src/idf_component.yml")

if(EXISTS "${_yml_file}")
    file(READ "${_yml_file}" _content)

    string(REGEX REPLACE
        "(${_component_name}:[ \t\r\n]+version:[ \t]+)[^\r\n]+"
        "\\1${_target_version}"
        _patched
        "${_content}"
    )

    if(NOT "${_patched}" STREQUAL "${_content}")
        file(WRITE "${_yml_file}" "${_patched}")
        message(STATUS "[pin-esp-nn] cmake re-asserted ${_component_name} ${_target_version}")

        if(EXISTS "${CMAKE_SOURCE_DIR}/dependencies.lock")
            file(REMOVE "${CMAKE_SOURCE_DIR}/dependencies.lock")
            message(STATUS "[pin-esp-nn] Removed dependencies.lock")
        endif()
        if(EXISTS "${CMAKE_SOURCE_DIR}/managed_components/espressif__esp-nn")
            file(REMOVE_RECURSE "${CMAKE_SOURCE_DIR}/managed_components/espressif__esp-nn")
            message(STATUS "[pin-esp-nn] Removed managed_components/espressif__esp-nn")
        endif()
    endif()
else()
    message(WARNING "[pin-esp-nn] ${_yml_file} not found at cmake time — check ESPHome codegen ordering")
endif()
