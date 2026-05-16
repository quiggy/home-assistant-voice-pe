# patch_esp_tflite_micro_cppstd.cmake — Injected via CMAKE_PROJECT_INCLUDE.
#
# Strips the dead `-std=c++11` flag from esp-tflite-micro's CMakeLists.txt
# (the `-std=gnu++14` on the same line then becomes the effective C++ std).
# Required for v1.3.5+ which introduces C++14 digit-separator syntax in
# decode_state_huffman.h. Runs after `project()` so managed_components has
# been downloaded.

set(_cmake_file "${CMAKE_SOURCE_DIR}/managed_components/espressif__esp-tflite-micro/CMakeLists.txt")

if(EXISTS "${_cmake_file}")
    file(READ "${_cmake_file}" _content)

    string(FIND "${_content}" "[PATCHED] dead -std=c++11" _patched_pos)
    if(_patched_pos EQUAL -1)
        # Strip the literal "-std=c++11 " token. Only one occurrence expected.
        string(REPLACE "-std=c++11 " "" _patched "${_content}")

        if(NOT "${_patched}" STREQUAL "${_content}")
            # Insert a marker comment so subsequent passes detect already-patched
            string(REPLACE
                "# enable ESP-NN optimizations by Espressif"
                "# [PATCHED] dead -std=c++11 stripped for C++14 kernel support\n# enable ESP-NN optimizations by Espressif"
                _patched_marked
                "${_patched}"
            )
            file(WRITE "${_cmake_file}" "${_patched_marked}")
            message(STATUS "[patch-tflite-cppstd] Stripped -std=c++11 from ${_cmake_file}")
        else()
            message(WARNING "[patch-tflite-cppstd] -std=c++11 not found in ${_cmake_file}")
        endif()
    else()
        message(STATUS "[patch-tflite-cppstd] Already patched: ${_cmake_file}")
    endif()
else()
    message(WARNING "[patch-tflite-cppstd] ${_cmake_file} not found yet")
endif()
