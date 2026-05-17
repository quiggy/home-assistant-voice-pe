# patch_esp_nn_conv_logging.cmake — Injected via CMAKE_PROJECT_INCLUDE for
# clean builds. Mirrors patch_esp_nn_conv_logging.py: inserts a MicroPrintf
# before each esp_nn_conv_s8() call so the layer shape is visible right
# before the crash.

set(_conv_file "${CMAKE_SOURCE_DIR}/managed_components/espressif__esp-tflite-micro/tensorflow/lite/micro/kernels/esp_nn/conv.cc")
set(_marker "[DIAG] ESP-NN Conv shape logging injected")

if(EXISTS "${_conv_file}")
    file(READ "${_conv_file}" _content)

    string(FIND "${_content}" "${_marker}" _patched_pos)
    if(_patched_pos EQUAL -1)
        # Substitute the for-loop start with logging + for-loop.
        # CMake REGEX REPLACE is awkward for multi-line content — use simple search/replace.
        set(_log "    // ${_marker}\n    static int conv_n = 0;\n    conv_n++;\n    MicroPrintf(\"[DIAG]C%d ih%d iw%d ic%d od%d\", conv_n, input_height, input_width, input_depth, output_depth);\n\n    for (int i_batch = 0; i_batch < batch_size;")
        string(REPLACE
            "    for (int i_batch = 0; i_batch < batch_size;"
            "${_log}"
            _patched
            "${_content}"
        )

        if(NOT "${_patched}" STREQUAL "${_content}")
            file(WRITE "${_conv_file}" "${_patched}")
            message(STATUS "[patch-esp-nn-conv-logging] Injected log into ${_conv_file}")
        else()
            message(WARNING "[patch-esp-nn-conv-logging] for-loop anchor not found")
        endif()
    else()
        message(STATUS "[patch-esp-nn-conv-logging] Already patched: ${_conv_file}")
    endif()
endif()
