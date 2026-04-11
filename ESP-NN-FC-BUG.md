# ESP-NN FullyConnected Kernel Bug — VAD Model Broken on ESP32-S3

## Summary

The VAD (Voice Activity Detection) model in ESPHome's `micro_wake_word` component produces near-zero output on ESP32-S3, causing wake word detection to fail even though the wake word model itself detects speech correctly. The root cause is a bug in the ESP-NN optimized `FullyConnected` kernel used by `esp-tflite-micro`.

## Symptoms

- Wake word models (e.g. `hey_luna`, `okay_nabu`) detect speech correctly
- VAD model always outputs near-zero probabilities (1–4/255 during speech, should be >127/255)
- Log message repeats: `Wake word model predicts 'hey_luna', but VAD model doesn't.`
- Voice assistant pipeline never triggers

## Affected Versions

| Component | Version | Notes |
|-----------|---------|-------|
| ESPHome | 2026.3.3 | |
| ESP-IDF | 5.5.3 | |
| esp-tflite-micro | 1.3.3~1 (v1.3.3.1, commit 78e5532, Jan 2025) | Bundled with ESPHome 2026.3.3 |
| esp-nn | 1.2.1 (commit 6e2e716) | Bundled with esp-tflite-micro |
| Hardware | ESP32-S3 rev0.2 (Home Assistant Voice PE) | |

## Root Cause

The ESP-NN optimized `FullyConnected` kernel in `esp-tflite-micro` produces incorrect inference results for the VAD model on ESP32-S3.

### Technical Details

The file `tensorflow/lite/micro/kernels/esp_nn/fully_connected.cc` replaces the stock TFLite Micro reference implementation with an ESP-NN optimized version. When `ESP_NN` is defined (which it is for ESP32-S3 builds), the `kTfLiteInt8` case calls `esp_nn_fully_connected_s8()` instead of the reference `tflite::reference_integer_ops::FullyConnected()`.

The ESP-NN kernel `esp_nn_fully_connected_s8()` produces numerically incorrect results for the VAD model's FullyConnected layer (Op 29 in the model graph). The VAD model has:
- 33 ops total: CONV_2D×4, DEPTHWISE_CONV_2D×3, FULLY_CONNECTED×1, LOGISTIC, QUANTIZE, etc.
- Input: `[1,3,40]` int8, Output: `[1,1]` uint8
- 14+ per-channel quantized tensors for Conv2D/DepthwiseConv2D weights

The wake word models (hey_luna, okay_nabu, stop) also use FullyConnected layers but are unaffected — suggesting the bug is triggered by specific tensor shapes, quantization parameters, or preceding layer interactions unique to the VAD model.

### Related Issue

This is related to [espressif/esp-tflite-micro#108](https://github.com/espressif/esp-tflite-micro/issues/108) — "ESP32-S3 with TFLite Int8 Quantized Model Returns Only Zeros", which identified that ESP-NN's FullyConnected kernel ignores per-channel quantization and always uses per-tensor `esp_nn_fully_connected_s8()`. However, the VAD bug persists even when per-channel fallback is added, indicating that `esp_nn_fully_connected_s8()` itself produces incorrect results for certain models.

### Fix in esp-tflite-micro v1.3.4

The esp-tflite-micro v1.3.4 release (Sep 2025) includes "Use ESP-NN optimisations for FullyConnected Per-Channel operation" and reworked the FC ESP-NN integration. ESPHome 2026.3.3 ships v1.3.3.1 (Jan 2025) — one version too old.

## The Fix

Disable ESP-NN optimization for the `FullyConnected` `kTfLiteInt8` case, forcing the TFLite Micro reference implementation.

### Patch

In `tensorflow/lite/micro/kernels/esp_nn/fully_connected.cc`, change the `kTfLiteInt8` case from:

```cpp
        case kTfLiteInt8: {
#if ESP_NN
          // ... ESP-NN optimized path (BROKEN for VAD model)
          esp_nn_fully_connected_s8(...);
#else
          tflite::reference_integer_ops::FullyConnected(...);
#endif
```

To:

```cpp
        case kTfLiteInt8: {
#if 0  // ESP-NN FC disabled — esp_nn_fully_connected_s8 produces wrong results for VAD model
          // ... ESP-NN optimized path (disabled)
#else
          tflite::reference_integer_ops::FullyConnected(...);
#endif
```

This forces the reference implementation for all int8 FullyConnected ops. The performance impact is minimal since FullyConnected is only one of many ops in the model, and Conv2D/DepthwiseConv2D (which dominate compute) still use ESP-NN.

## Investigation Timeline

1. **Arena sizes** — Measured actual arena usage. VAD needed ~24588 bytes vs old 16772. Fixed, but VAD still broken.
2. **Variable arena** — Verified both `ma_` and `mrv_` pointers non-null. Ruled out.
3. **Output quantization** — Identical across all models (scale=0.003906, zero_point=0). Ruled out.
4. **Custom component** — Renamed `custom_components` dir entirely. VAD still broken with pure stock ESPHome. Confirmed platform-level bug.
5. **Per-channel FC fallback** — Added `if (data.is_per_channel)` branch to fall back to `FullyConnectedPerChannel`. VAD still broken — the FC layer apparently uses per-tensor quantization, so the fallback never triggered.
6. **Disable ESP-NN FC entirely** — Changed `#if ESP_NN` to `#if 0`. **VAD FIXED.** Full pipeline works: wake word → STT → intent → TTS.

## How to Make the Fix Persistent

The patch is applied automatically via a PlatformIO pre-build script:

1. **`patch_esp_nn_fc.py`** in the project root patches `fully_connected.cc` before compilation
2. **`custom.yaml`** references it via `platformio_options: extra_scripts: pre:../../../patch_esp_nn_fc.py`

### Clean Build Caveat

On a fully clean build (no `.esphome/build/` directory), the first compile runs before `managed_components` are downloaded, so the patch cannot be applied. On the second compile (incremental), the script patches the file and CMake/ninja recompiles just that one file (~25s). Clean builds are rare in practice.

### Upgrading ESPHome

Once ESPHome upgrades its esp-tflite-micro dependency from v1.3.3.1 to >= v1.3.4, this patch is no longer needed and both the script and `extra_scripts` reference can be removed.

## Files

- **Bug location**: `managed_components/espressif__esp-tflite-micro/tensorflow/lite/micro/kernels/esp_nn/fully_connected.cc`
- **VAD model**: `models/vad.tflite` (34328 bytes, MD5 `dcefed8d71eb1107cc6dc2e8d042ba83`)
- **Build directories**: `.esphome/build/ha-voice-0abfdc/` (custom.yaml), `.esphome/build/home-assistant-voice/` (home-assistant-voice.yaml)
