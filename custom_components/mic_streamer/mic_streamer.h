#pragma once

#include "esphome/core/component.h"
#include "esphome/components/microphone/microphone_source.h"

#include <string>
#include <vector>

namespace esphome {
namespace mic_streamer {

// Taps a microphone source and streams raw PCM to a PC over UDP for recording
// (e.g. gathering wake-word training/eval data straight from the device mics).
// Each datagram is prefixed with a little-endian uint32 sequence number so the
// receiver can detect dropped packets.
class MicStreamer : public Component {
 public:
  void setup() override;
  void dump_config() override;
  // Socket creation needs the network stack up before we send anything.
  float get_setup_priority() const override { return setup_priority::AFTER_WIFI; }

  void set_microphone_source(microphone::MicrophoneSource *mic_source) { this->mic_source_ = mic_source; }
  void set_address(const std::string &address) { this->address_ = address; }
  void set_port(uint16_t port) { this->port_ = port; }
  void set_max_packet_size(size_t size) { this->max_packet_size_ = size; }

  void start();
  void stop();
  bool is_streaming() const { return this->streaming_; }

 protected:
  void send_audio_(const std::vector<uint8_t> &data);

  microphone::MicrophoneSource *mic_source_{nullptr};
  std::string address_;
  uint16_t port_{0};
  size_t max_packet_size_{1024};

  int socket_fd_{-1};
  bool streaming_{false};
  uint32_t seq_{0};
  uint32_t send_errors_{0};
  std::vector<uint8_t> packet_buf_;
};

}  // namespace mic_streamer
}  // namespace esphome
