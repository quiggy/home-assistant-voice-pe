#pragma once

#include "esphome/core/automation.h"
#include "mic_streamer.h"

namespace esphome {
namespace mic_streamer {

template<typename... Ts> class StartAction : public Action<Ts...>, public Parented<MicStreamer> {
 public:
  void play(Ts... x) override { this->parent_->start(); }
};

template<typename... Ts> class StopAction : public Action<Ts...>, public Parented<MicStreamer> {
 public:
  void play(Ts... x) override { this->parent_->stop(); }
};

template<typename... Ts> class IsStreamingCondition : public Condition<Ts...>, public Parented<MicStreamer> {
 public:
  bool check(Ts... x) override { return this->parent_->is_streaming(); }
};

}  // namespace mic_streamer
}  // namespace esphome
