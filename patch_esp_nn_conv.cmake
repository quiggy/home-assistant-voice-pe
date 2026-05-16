# patch_esp_nn_conv.cmake — Injected via CMAKE_PROJECT_INCLUDE (runs after project())
#
# Patches ESP-NN Conv2D kernel to disable hardware acceleration that causes a
# crash inside esp_nn_conv_s8() during the first Invoke() of the BC-ResNet
# smoke-test model on ESP32-S3.
#
# Mirrors patch_esp_nn_fc.cmake exactly. Runs during cmake configure, after
# managed_components are downloaded by the ESP-IDF component manager.

set(_conv_file "${CMAKE_SOURCE_DIR}/managed_components/espressif__esp-tflite-micro/tensorflow/lite/micro/kernels/esp_nn/conv.cc")

if(EXISTS "${_conv_file}")
    file(READ "${_conv_file}" _conv_content)

    string(FIND "${_conv_content}" "[PATCHED] ESP-NN Conv" _patched_pos)
    if(_patched_pos EQUAL -1)
        string(REGEX REPLACE
            "#if ESP_NN([ \t]*\n)"
            "#if 0  // [PATCHED] ESP-NN Conv disabled for BC-ResNet compatibility\\1"
            _conv_patched
            "${_conv_content}"
        )

        if(NOT "${_conv_patched}" STREQUAL "${_conv_content}")
            file(WRITE "${_conv_file}" "${_conv_patched}")
            message(STATUS "[patch-esp-nn-conv] Patched: ${_conv_file}")
        else()
            message(WARNING "[patch-esp-nn-conv] Pattern not found in: ${_conv_file}")
        endif()
    else()
        message(STATUS "[patch-esp-nn-conv] Already patched: ${_conv_file}")
    endif()
else()
    message(WARNING "[patch-esp-nn-conv] File not found: ${_conv_file} (component not yet downloaded?)")
endif()
