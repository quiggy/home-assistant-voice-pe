# Tensor Arena Size Bug — Models Fail to Load

## Summary

The upstream model manifest JSON files shipped with undersized `tensor_arena_size` values, causing `AllocateTensors()` to fail and preventing all micro_wake_word models (VAD + wake words) from loading.

## Symptoms

- Models fail to load during `StreamingModel::load_model_()`
- `AllocateTensors()` returns `kTfLiteOk` failure
- Log: `Failed to allocate tensors for the streaming model`
- Wake word detection completely non-functional (no models loaded)

## Root Cause

Each TFLite Micro model requires a tensor arena — a contiguous memory block used for intermediate tensor storage during inference. The required arena size depends on the model architecture and is not embedded in the `.tflite` file itself; it must be specified externally.

The upstream model manifest JSON files (e.g. `models/vad.json`, `models/okay_nabu.json`) declared `tensor_arena_size` values that were too small for the actual models. When `MicroInterpreter::AllocateTensors()` attempted to lay out all intermediate tensors within the undersized arena, it failed.

### Why the sizes were wrong

The `tensor_arena_size` in a model manifest is essentially a manually tuned value. If a model is retrained or the TFLite Micro runtime version changes (different allocation strategy, padding, alignment), the previously declared arena size may no longer be sufficient. The upstream manifests had not been updated to match the actual requirements for ESPHome 2026.3.3 / esp-tflite-micro v1.3.3.1.

## The Fix

Right-sized all arena values by measuring actual usage with `MicroInterpreter::arena_used_bytes()`, then adding headroom (aligned to 16 bytes).

### Original vs Fixed Arena Sizes

| Model | Original (upstream) | Fixed | Actual usage (approx) |
|-------|-------------------:|------:|---------------------:|
| vad | ~16,772 | **25,600** | ~24,588 |
| okay_nabu | undersized | **37,120** | measured |
| hey_luna | undersized | **40,000** | measured |
| stop | undersized | **40,000** | measured |

### How Arena Size Was Measured

A custom component variant added a `probe_arena_size_()` method that performs a binary search:

1. Attempt `AllocateTensors()` with the manifest size, then 1.5×, then 2×
2. Once a working size is found, use `arena_used_bytes()` as lower bound
3. Binary search between `arena_used_bytes() + 16` and the working size
4. Result: minimum arena size (aligned to 16 bytes) that passes `AllocateTensors()`

The stock ESPHome component has no arena probing — it trusts the manifest value verbatim.

### Updated Model Manifests

The fix is applied in the model JSON files under `models/`:

```json
{
  "micro": {
    "tensor_arena_size": 25600
  }
}
```

## Memory Layout

Each model gets two separate allocations via `RAMAllocator` (PSRAM-first, internal SRAM fallback):

| Allocation | Size | Purpose |
|-----------|-----:|---------|
| `tensor_arena_` | per-model (see table above) | Intermediate tensors during inference |
| `var_arena_` | 1,024 bytes (fixed) | `MicroResourceVariables` — streaming state variables |

Total PSRAM budget for all loaded models:

| Model | Arena | Var arena | Total |
|-------|------:|----------:|------:|
| vad | 25,600 | 1,024 | 26,624 |
| okay_nabu | 37,120 | 1,024 | 38,144 |
| hey_luna | 40,000 | 1,024 | 41,024 |
| stop | 40,000 | 1,024 | 41,024 |
| **Total** | **142,720** | **4,096** | **146,816** |

## Relationship to ESP-NN FC Bug

This arena sizing bug was discovered and fixed first, but fixing it alone did not restore VAD functionality. The VAD model loaded successfully with the right-sized arena but still produced near-zero output — that turned out to be the separate [ESP-NN FullyConnected kernel bug](ESP-NN-FC-BUG.md).

Both bugs had to be fixed for the voice pipeline to work:
1. **Arena sizing** → models can load and run inference
2. **ESP-NN FC patch** → VAD inference produces correct output

## Affected Versions

- ESPHome 2026.3.3 with upstream model manifests from [home-assistant/voice-pe](https://github.com/home-assistant/voice-pe)
- Any ESPHome version where the bundled esp-tflite-micro has different arena requirements than what the manifests declare

## Prevention

- After updating ESPHome or esp-tflite-micro, verify models load by checking logs for `Failed to allocate tensors`
- Use the probe approach (attempt with manifest size, measure `arena_used_bytes()`, add 4–8% headroom) to validate arena sizes
- Consider upstreaming a runtime arena probe to the stock ESPHome `micro_wake_word` component
