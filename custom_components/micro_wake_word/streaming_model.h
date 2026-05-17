#pragma once

#ifdef USE_ESP32

#include "preprocessor_settings.h"

#include "esphome/core/preferences.h"

#include <cstdio>
#include <cstring>

#include <esp_log.h>
#include <esp_timer.h>

#include <tensorflow/lite/core/c/common.h>
#include <tensorflow/lite/micro/micro_interpreter.h>
#include <tensorflow/lite/micro/micro_mutable_op_resolver.h>
#include <tensorflow/lite/micro/micro_profiler_interface.h>

namespace esphome {
namespace micro_wake_word {

static const uint8_t MIN_SLICES_BEFORE_DETECTION = 100;
static const uint32_t STREAMING_MODEL_VARIABLE_ARENA_SIZE = 1024;

// Self-contained MicroProfilerInterface implementation. Records per-op
// start/end timestamps using esp_timer_get_time() (microsecond precision),
// then emits two tables via ESP_LOGI on log_and_stop():
//   1. per-call timeline (op #N, tag, microseconds)
//   2. aggregate by tag (op-type, count, total microseconds)
//
// Why not just wrap tflite::MicroProfiler:
//   * Its 4096-event buffer overflows after ~2 s on our streaming model
//     (~32 ops × ~60 inferences/s).
//   * Its Log()/LogTicksPerTagCsv() emit via TFLite-Micro's MicroPrintf,
//     which on ESP-IDF goes through esp_log_printf-via-stdout and gets
//     dropped or interleaved oddly in ESPHome's log capture — we observed
//     the calls running but no per-op lines reaching the user's tail.
// This class is gated: after log_and_stop(), BeginEvent/EndEvent are
// no-ops so the model continues running with zero profiling overhead.
class GatedProfiler : public tflite::MicroProfilerInterface {
 public:
  // 128 slots is comfortable for BC-ResNet (32 ops) and any near-future
  // model size; beyond that BeginEvent silently drops events.
  static constexpr int kMaxOps = 128;

  uint32_t BeginEvent(const char *tag) override {
    if (this->stopped_) return 0;
    if (this->n_ >= kMaxOps) return 0;
    this->tags_[this->n_] = tag;
    this->start_us_[this->n_] = esp_timer_get_time();
    this->end_us_[this->n_] = this->start_us_[this->n_];
    return this->n_++;
  }

  void EndEvent(uint32_t event_handle) override {
    if (this->stopped_) return;
    if (event_handle >= static_cast<uint32_t>(kMaxOps)) return;
    this->end_us_[event_handle] = esp_timer_get_time();
  }

  void log_and_stop() {
    this->stopped_ = true;

    // Bypass ESPHome's per-task 768-byte log buffer — 32+ entries blow past
    // it and most lines get dropped silently. Plain printf() writes to
    // stdout which on USB-JTAG is mirrored to the serial console without
    // queueing. Each line carries a [MWW_PROF] tag so it's easy to grep
    // out of the surrounding ESPHome logs.
    int64_t total = 0;
    std::printf("[MWW_PROF] === per-op timeline (n=%d) ===\n", this->n_);
    for (int i = 0; i < this->n_; i++) {
      int64_t dt = this->end_us_[i] - this->start_us_[i];
      total += dt;
      std::printf("[MWW_PROF] #%2d %-24s %6lld us\n",
                  i, this->tags_[i] ? this->tags_[i] : "?", (long long) dt);
    }
    std::printf("[MWW_PROF] === sum of per-op = %lld us ===\n", (long long) total);

    std::printf("[MWW_PROF] === aggregate per op-type ===\n");
    bool already_printed[kMaxOps] = {};
    for (int i = 0; i < this->n_; i++) {
      if (already_printed[i]) continue;
      int64_t agg = this->end_us_[i] - this->start_us_[i];
      int cnt = 1;
      for (int j = i + 1; j < this->n_; j++) {
        if (this->tags_[i] && this->tags_[j] &&
            std::strcmp(this->tags_[i], this->tags_[j]) == 0) {
          agg += this->end_us_[j] - this->start_us_[j];
          cnt++;
          already_printed[j] = true;
        }
      }
      std::printf("[MWW_PROF] %-24s %3dx  %6lld us total\n",
                  this->tags_[i] ? this->tags_[i] : "?", cnt, (long long) agg);
    }
    std::fflush(stdout);
  }

 private:
  const char *tags_[kMaxOps] = {};
  int64_t start_us_[kMaxOps] = {};
  int64_t end_us_[kMaxOps] = {};
  int n_ = 0;
  bool stopped_{false};
};

struct DetectionEvent {
  std::string *wake_word;
  bool detected;
  bool partially_detection;  // Set if the most recent probability exceed the threshold, but the sliding window average
                             // hasn't yet
  uint8_t max_probability;
  uint8_t average_probability;
  bool blocked_by_vad = false;
};

class StreamingModel {
 public:
  virtual void log_model_config() = 0;
  virtual DetectionEvent determine_detected() = 0;

  // Performs inference on the given features.
  //  - If the model is enabled but not loaded, it will load it
  //  - If the model is disabled but loaded, it will unload it
  // Returns true if sucessful or false if there is an error
  bool perform_streaming_inference(const int8_t features[PREPROCESSOR_FEATURE_SIZE]);

  /// @brief Sets all recent_streaming_probabilities to 0 and resets the ignore window count
  void reset_probabilities();

  /// @brief Destroys the TFLite interpreter and frees the tensor and variable arenas' memory
  void unload_model();

  /// @brief Enable the model. The next performing_streaming_inference call will load it.
  virtual void enable() { this->enabled_ = true; }

  /// @brief Disable the model. The next performing_streaming_inference call will unload it.
  virtual void disable() { this->enabled_ = false; }

  /// @brief Return true if the model is enabled.
  bool is_enabled() const { return this->enabled_; }

  bool get_unprocessed_probability_status() const { return this->unprocessed_probability_status_; }

  // Quantized probability cutoffs mapping 0.0 - 1.0 to 0 - 255
  uint8_t get_default_probability_cutoff() const { return this->default_probability_cutoff_; }
  uint8_t get_probability_cutoff() const { return this->probability_cutoff_; }
  void set_probability_cutoff(uint8_t probability_cutoff) { this->probability_cutoff_ = probability_cutoff; }

  void set_probe_arena(bool v) { this->probe_arena_ = v; }
  void set_log_timing(bool v) { this->log_timing_ = v; }
  void set_profile_ops(bool v) { this->profile_ops_ = v; }

 protected:
  /// @brief Allocates tensor and variable arenas and sets up the model interpreter
  /// @return True if successful, false otherwise
  bool load_model_();
  /// @brief Probes the actual required tensor arena size by trial allocation.
  /// @return The required arena size rounded up to 16-byte alignment, or 0 on failure.
  size_t probe_arena_size_();
  /// @brief Returns true if successfully registered the streaming model's TensorFlow operations
  bool register_streaming_ops_(tflite::MicroMutableOpResolver<21> &op_resolver);

  tflite::MicroMutableOpResolver<21> streaming_op_resolver_;

  bool loaded_{false};
  bool enabled_{true};
  bool tensor_arena_size_probed_{false};
  bool probe_arena_{false};
  bool log_timing_{false};
  bool profile_ops_{false};
  bool profile_logged_{false};
  bool unprocessed_probability_status_{false};
  uint8_t current_stride_step_{0};
  int16_t ignore_windows_{-MIN_SLICES_BEFORE_DETECTION};

  uint8_t default_probability_cutoff_;
  uint8_t probability_cutoff_;
  size_t sliding_window_size_;

  size_t last_n_index_{0};
  size_t tensor_arena_size_;
  bool use_internal_ram_{false};  // If true, allocate tensor arena in internal SRAM instead of SPIRAM
  std::vector<uint8_t> recent_streaming_probabilities_;

  const uint8_t *model_start_;
  uint8_t *tensor_arena_{nullptr};
  uint8_t *var_arena_{nullptr};
  std::unique_ptr<tflite::MicroInterpreter> interpreter_;
  tflite::MicroResourceVariables *mrv_{nullptr};
  tflite::MicroAllocator *ma_{nullptr};
  GatedProfiler micro_profiler_;
};

class WakeWordModel final : public StreamingModel {
 public:
  /// @brief Constructs a wake word model object
  /// @param id (std::string) identifier for this model
  /// @param model_start (const uint8_t *) pointer to the start of the model's TFLite FlatBuffer
  /// @param default_probability_cutoff (uint8_t) probability cutoff for acceping the wake word has been said
  /// @param sliding_window_average_size (size_t) the length of the sliding window computing the mean rolling
  ///                                    probability
  /// @param wake_word (std::string) Friendly name of the wake word
  /// @param tensor_arena_size (size_t) Size in bytes for allocating the tensor arena
  /// @param default_enabled (bool) If true, it will be enabled by default on first boot
  /// @param internal_only (bool) If true, the model will not be exposed to HomeAssistant as an available model
  WakeWordModel(const std::string &id, const uint8_t *model_start, uint8_t default_probability_cutoff,
                size_t sliding_window_average_size, const std::string &wake_word, size_t tensor_arena_size,
                bool default_enabled, bool internal_only, bool use_internal_ram = false);

  void log_model_config() override;

  /// @brief Checks for the wake word by comparing the mean probability in the sliding window with the probability
  /// cutoff
  /// @return True if wake word is detected, false otherwise
  DetectionEvent determine_detected() override;

  const std::string &get_id() const { return this->id_; }
  const std::string &get_wake_word() const { return this->wake_word_; }

  void add_trained_language(const std::string &language) { this->trained_languages_.push_back(language); }
  const std::vector<std::string> &get_trained_languages() const { return this->trained_languages_; }

  /// @brief Enable the model and save to flash. The next performing_streaming_inference call will load it.
  void enable() override;

  /// @brief Disable the model and save to flash. The next performing_streaming_inference call will unload it.
  void disable() override;

  bool get_internal_only() { return this->internal_only_; }

 protected:
  std::string id_;
  std::string wake_word_;
  std::vector<std::string> trained_languages_;

  bool internal_only_;

  ESPPreferenceObject pref_;
};

class VADModel final : public StreamingModel {
 public:
  VADModel(const uint8_t *model_start, uint8_t default_probability_cutoff, size_t sliding_window_size,
           size_t tensor_arena_size);

  void log_model_config() override;

  /// @brief Checks for voice activity by comparing the max probability in the sliding window with the probability
  /// cutoff
  /// @return True if voice activity is detected, false otherwise
  DetectionEvent determine_detected() override;
};

}  // namespace micro_wake_word
}  // namespace esphome

#endif
