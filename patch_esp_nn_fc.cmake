# patch_esp_nn_fc.cmake — Injected via CMAKE_PROJECT_INCLUDE (runs after project())
#
# Patches ESP-NN FullyConnected kernel to disable hardware acceleration
# that produces incorrect VAD model inference on ESP32-S3.
#
# This runs during cmake configure, AFTER managed_components are downloaded
# by the ESP-IDF component manager, so it works on the very first clean build.
#
# See ESP-NN-FC-BUG.md for details.
# See https://github.com/espressif/esp-tflite-micro/issues/108

set(_fc_file "${CMAKE_SOURCE_DIR}/managed_components/espressif__esp-tflite-micro/tensorflow/lite/micro/kernels/esp_nn/fully_connected.cc")

if(EXISTS "${_fc_file}")
    file(READ "${_fc_file}" _fc_content)

    # Already patched?
    string(FIND "${_fc_content}" "[PATCHED]" _patched_pos)
    if(_patched_pos EQUAL -1)
        # Replace '#if ESP_NN' with '#if 0 ... #elif ESP_NN' in the kTfLiteInt8 case.
        # The pattern: 'case kTfLiteInt8: {\n#if ESP_NN'
        string(REGEX REPLACE
            "(case kTfLiteInt8:[^\n]*\\{)\n#if ESP_NN"
            "\\1\n#if 0  // [PATCHED] ESP-NN FC disabled for VAD compatibility\n          // ESP-NN esp_nn_fully_connected_s8() produces wrong results for VAD model.\n          // Forcing reference implementation. See ESP-NN-FC-BUG.md\n#elif ESP_NN"
            _fc_patched
            "${_fc_content}"
        )

        if(NOT "${_fc_patched}" STREQUAL "${_fc_content}")
            file(WRITE "${_fc_file}" "${_fc_patched}")
            message(STATUS "[patch-esp-nn-fc] Patched: ${_fc_file}")
        else()
            message(WARNING "[patch-esp-nn-fc] Pattern not found in: ${_fc_file}")
        endif()
    else()
        message(STATUS "[patch-esp-nn-fc] Already patched: ${_fc_file}")
    endif()
else()
    message(WARNING "[patch-esp-nn-fc] File not found: ${_fc_file} (component not yet downloaded?)")
endif()
