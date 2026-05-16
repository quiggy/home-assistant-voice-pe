# Home Assistant Voice PE - Project Notes

## Devices

| Device | ESPHome Name | IP Address | MAC Address |
|--------|-------------|------------|-------------|
| Wohnzimmer | ha-voice-0abfdc | 192.168.2.122 | 20:F8:3B:0A:BF:DC |
| Küche | ha-voice-0abef9 | 192.168.2.131 | 20:F8:3B:0A:BE:F9 |
| Arbeitszimmer | ha-voice-099f06 | 192.168.2.94 | 20:F8:3B:09:9F:06 |

## Documentation

- [ARENA-SIZE-BUG.md](ARENA-SIZE-BUG.md) — Models fail to load due to undersized tensor_arena_size. Fixed by PR #15628 (milestoned for 2026.4.0b2).
- [ESP-NN-FC-BUG.md](ESP-NN-FC-BUG.md) — VAD model produces near-zero output due to broken `esp_nn_fully_connected_s8()` in esp-nn 1.2.1. NOT fixed by PR #15628. Patched locally via `patch_esp_nn_fc.py`.

## Build & Flash

- **ESPHome**: 2026.4.5 via Docker (`ghcr.io/esphome/esphome:2026.4.5`)
- **Compile**: `docker run --rm -v "$(pwd)":/config ghcr.io/esphome/esphome:2026.4.5 compile /config/custom-<device>.yaml`
- **OTA flash**: `docker run --rm -v "$(pwd)":/config ghcr.io/esphome/esphome:2026.4.5 upload /config/custom-<device>.yaml --device <IP>`
- **USB flash** (macOS, Docker can't pass USB): Compile in Docker, then flash with host esptool:
  ```
  python3 -m esptool --chip esp32s3 --port /dev/cu.usbmodem1101 write_flash 0x10000 .esphome/build/<name>/.pioenvs/<name>/firmware.bin
  ```

## Patch: ESP-NN FC

- [patch_esp_nn_fc.py](patch_esp_nn_fc.py) — PlatformIO pre-build script. Disables broken ESP-NN hardware-accelerated FullyConnected kernel.
- [patch_esp_nn_fc.cmake](patch_esp_nn_fc.cmake) — CMake script invoked via `CMAKE_PROJECT_INCLUDE` for clean builds (when `managed_components/` doesn't exist yet).
- Each device YAML must include in `platformio_options`:
  ```yaml
  platformio_options:
    extra_scripts:
      - pre:../../../patch_esp_nn_fc.py
  ```
