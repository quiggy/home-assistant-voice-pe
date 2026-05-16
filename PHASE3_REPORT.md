# Phase 3 — BC-ResNet Smoke Test on Voice PE Arbeitszimmer

Branch: `bcresnet-test`
Target device: Voice PE Arbeitszimmer (`ha-voice-099f06`, ESP32-S3, 192.168.2.94)
Production devices (Wohnzimmer, Küche): **not touched**, remain on `mww-sonos-redirect`.
Date: 2026-05-16

## Verdict

**works.** Weg A (`op_resolver.AddDequantize()` zum MWW-Op-Resolver hinzufügen) ist
hardware-validiert. Nach Zusatz-Patch des esp-nn Conv2D-Kernels läuft BC-ResNet
end-to-end auf Voice PE und erkennt "yes" zuverlässig. Inferenz-Latenz liegt
unter dem 25-ms-Threshold. Ring-Buffer-Drops bei 7.4 % sind ein offener Punkt —
ohne ESP-NN-Beschleunigung reicht der Reference-Conv-Kernel knapp nicht für
den 10-ms-Frame-Step, Detection-Accuracy bleibt aber subjektiv akzeptabel.

## Messwerte (Funktional-Test, 104 s Capture)

| Metrik | Wert |
|---|---|
| Inferenz-Latenz (median) | **16.79 ms** |
| Inferenz-Latenz (min) | 16.28 ms |
| Inferenz-Latenz (mean) | 16.92 ms |
| Inferenz-Latenz (p95) | 17.73 ms |
| Inferenz-Latenz (max) | 27.27 ms |
| Inferenzen insgesamt | 5 746 |
| Effektive Rate | ~55 Inferenzen/s |
| Ring-Buffer-Resets | 427 (7.4 % der Inferenzen) |
| Detections auf "yes" | 26 events |
| Detection max-probability | meist 1.00, einige 0.67-0.95 |
| Detection avg-probability (5-Frame-Sliding) | 0.50-0.65 |
| Probability-Cutoff (Manifest) | 0.50 |
| Stride im Modell | 1 (eine Inferenz pro 10-ms-Frame) |
| Tensor-Arena (probed) | 133 888 Bytes |
| Tensor-Arena (`arena_used_bytes`) | 67 700 Bytes |
| Variable-Arena | 1 024 Bytes (Default) |
| Free Heap (boot, vor MWW-Load) | ~143 528 Bytes |
| Free Heap (nach MWW-Load) | 139 240 Bytes (–4.3 KB) |
| Build-RAM | 13.3 % (43 508 / 327 680 Bytes) |
| Build-Flash | 33.9 % (2.75 MB / 8.1 MB) |
| PSRAM total | 8 192 KB |

## Modell-I/O (re-exportiert auf Fedora, Phase 2.5)

```
Input  quant: scale=0.093704  zero_point=19   type=9 (int8)
Output quant: scale=0.003906  zero_point=0    type=3 (uint8)
Outputs:      1
Stride:       1  (input dims[1])
```

Input passt direkt zu MWW (`PREPROCESSOR_FEATURE_SIZE = 40`, int8). Output ist
sauberes uint8 mit zero_point=0, also kein Offset-Conversion-Code nötig.

## Was untersucht und gefixt wurde

### 1. AddDequantize: Hauptthese aus Phase 2

✅ Stock-MWW-Op-Resolver registriert 20 Ops; BC-ResNet bringt einen 21. Op
(DEQUANTIZE, 26 Aufrufe für PTQ-FIFO-State-Vars). Wir bumpten
`MicroMutableOpResolver<20>` → `<21>` an drei Stellen und fügten
`op_resolver.AddDequantize()` in `register_streaming_ops_` hinzu. Build
zog `dequantize.cc.o` und `dequantize_common.cc.o` in das Firmware-Binary,
`AllocateTensors()` läuft sauber durch — Op-Set-Hypothese hardware-bestätigt.

### 2. Arena-Probe

Manifest-Feld `probe_arena: true` schaltet die binär-suchende Arena-Probe ein.
Gemessen: **133 888 Bytes** stabil über drei Boots. Tatsächlich genutzt
(`arena_used_bytes`): 67 700 Bytes. Differenz (~66 KB) ist normaler Scratch-
und Persistent-Buffer-Overhead in TFLite Micro.

Für Steady-State-Deploy in einer späteren Phase: Manifest auf
`tensor_arena_size: 133888` und `probe_arena: false` setzen.

### 3. Latenz-Instrumentierung

Manifest-Feld `log_timing: true` umklammert jeden `interpreter_->Invoke()` mit
`esp_timer_get_time()`. Im Steady-State später ausschalten — kostet ein paar
Mikrosekunden pro Inference und füllt die Log-Buffer.

### 4. ESP-NN Conv2D Crash (neu entdeckt)

Erste End-to-end-Inferenz crashte sofort:

```
abort() at PC 0x42072953 on core 0
Backtrace (resolved):
  0x42072953: tflite::Eval at esp_nn/conv.cc:291
  0x42078c0b: MicroInterpreterGraph::InvokeSubgraph
  0x4205f9c5: MicroInterpreter::Invoke
  0x42016a4c: StreamingModel::perform_streaming_inference  (streaming_model.cpp:237)
  0x42015e54: MicroWakeWord::update_model_probabilities_
  0x4201637e: MicroWakeWord::inference_task
```

Pathologie identisch zum bestehenden ESP-NN-FC-Bug (siehe
[ESP-NN-FC-BUG.md](ESP-NN-FC-BUG.md)). Workaround analog:

- [patch_esp_nn_conv.py](patch_esp_nn_conv.py) — PlatformIO pre-build hook
  rewritet alle 5 `#if ESP_NN`-Blöcke in `conv.cc` zu `#if 0`, fällt durch zur
  Reference-Implementation `reference_integer_ops::ConvPerChannel`.
- [patch_esp_nn_conv.cmake](patch_esp_nn_conv.cmake) — cmake-Pendant für
  Clean-Builds, wird via `CMAKE_PROJECT_INCLUDE` nach `project()` ausgeführt.
- `custom-arbeitszimmer.yaml` listet den neuen pre-script neben
  `patch_esp_nn_fc.py`.

Nach dem Patch läuft Invoke() ohne Abort durch, Detection arbeitet wie oben
gemessen.

### 5. OTA-Rollback-Schleife (Lessons Learned)

Beim ersten Versuch, das neue Modell zu flashen, schlug OTA dreimal in Folge
rollback an, weil safe_mode (60s) nicht abgewartet wurde — Device wurde durch
USB-Anschließen reset oder durch den späteren Conv-Crash neu gebootet, bevor
`mark_app_valid_cancel_rollback` getriggert wurde.

Lösung: **web.esphome.io** mit der `firmware.factory.bin`. Schreibt ota_data
sauber neu, kein Rollback-Risiko. Wir kopieren die `.factory.bin` in den
Repo-Root unter `bcresnet-smoke-firmware.factory.bin` (gitignored), damit der
Browser-File-Picker sie ohne Hidden-Files-Toggle findet.

### 6. on_boot Defense-in-Depth

Ein `delay 2s → micro_wake_word.start:` in `esphome.on_boot` hatte beim
Crash-Loop fatale Folgen: das Device crashte ~3 s nach jedem Boot, kam nie
aus safe_mode raus, jeder neue OTA-Versuch rollback'te. Entfernt; MWW wird
ausschließlich durch Toggle des `Server wake word`-Switches in HA gestartet.

## Surprises (für Memory)

1. **ESP-NN bug count = 2** (FC + Conv2D). Beide same root pattern in
   esp-tflite-micro 1.3.3.1 (gebündelt mit ESPHome 2026.3.3). Beide werden
   identisch via `#if ESP_NN → #if 0` Patch umgangen. Wenn ESPHome auf
   esp-tflite-micro 1.3.4 wechselt, beide Patches prüfen ob noch nötig.

2. **`micro_wake_word.start:` in `on_boot` ist eine Falle.** Wenn das geladene
   Modell beim ersten Invoke crashed, geht das Device in einen Bootloop, aus
   dem nur Vollflash via USB/web.esphome.io rauskommt. Sicherer: Start
   ausschließlich über User-toggelbaren Switch.

3. **web.esphome.io ist die Reset-Knopf-Lösung**, wenn OTA wegen Rollback nicht
   mehr greift. Funktioniert auch wenn das Device sich nicht im Safe-Mode
   meldet. Anleitung: Chrome/Edge → web.esphome.io → Connect → Espressif USB
   JTAG/serial port → Install → `firmware.factory.bin` wählen.

4. **Reference Conv kostet ~1.7× mehr Zeit als 10-ms-Frame-Step**, was 7.4 %
   Frame-Drops verursacht. Detection bleibt funktional, aber für späteren
   Production-Use sollte entweder eine ESP-NN-Conv-Fix-Version oder eine
   anderes (kleineres) Modell evaluiert werden.

5. **Bit-Equivalence Twin↔Streaming aus Phase 2 hält in der Praxis.** Modell
   wurde mit `int8`-Input und sauberem `uint8`-Output (zero_point=0) auf
   Fedora re-exportiert; MWW konsumiert es ohne Anpassung der Reader-Logik.

## Commits auf `bcresnet-test`

```
a87d268  Phase 3a: custom MWW component with AddDequantize, arena probe, timing
f6ad1c2  Phase 3b: bcresnet_smoke model and manifest
4b18e1b  Phase 3c: YAML for BC-ResNet smoke test, VA pipeline disabled
0df2583  Phase 3c fixup: neuter remaining 'id: stop' references
7d835ac  Phase 3d-fix: patch ESP-NN Conv2D + drop on_boot MWW.start
(pending) Phase 3e: this report
```

## Offene Punkte für Phase 4

- **Steady-state Manifest**: `tensor_arena_size: 133888`, `probe_arena: false`,
  `log_timing: false`. Reduziert Boot-Probe-Aufwand und Log-Spam.
- **Frame-Drop-Mitigation**: Optionen
  - Modell mit höherem feature_step_size re-trainieren (z.B. 20 ms Step
    → 50 Inferenzen/s benötigt → wir liefern 55/s → OK).
  - Auf ESPHome 2026.4+ warten und prüfen ob ESP-NN Conv gefixt ist.
  - Kleineres Modell (BC-ResNet-0.5 statt -1) evaluieren.
- **False-Accept-Test fehlt**: Aktueller Capture war Positiv-only (User hat
  überwiegend "yes" gesagt). Kontrollierter Test mit 'nein', 'okay', 'hallo',
  'stop' nachholen.
- **10-min-Idle-Stabilität**: Nicht durchgeführt. PSRAM-Belegung über die Zeit
  beobachten.
- **Multi-Distanz-Charakterisierung**: Trigger-Rate auf "yes" aus 1m/2m/3m
  getrennt messen (Anzahl Detections pro Distanz).
- **Production-Voice-Pipeline reaktivieren**: voice_assistant-Block ist
  konfiguriert aber nicht getriggert. Für späteres Deploy in der Smoke-Test-
  Variante muss `on_wake_word_detected` wieder die VA-Pipeline starten.
