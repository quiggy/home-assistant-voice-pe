#include "mic_streamer.h"
#include "esphome/core/log.h"

#include <lwip/sockets.h>
#include <lwip/inet.h>

#include <algorithm>
#include <cerrno>
#include <cstring>

namespace esphome {
namespace mic_streamer {

static const char *const TAG = "mic_streamer";

void MicStreamer::setup() {
  this->socket_fd_ = ::socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
  if (this->socket_fd_ < 0) {
    ESP_LOGE(TAG, "Failed to create UDP socket: errno %d", errno);
    this->mark_failed();
    return;
  }

  // Non-blocking: a stalled/overfull send buffer must never block the mic task.
  // Dropped datagrams are reported by the PC-side capture script via the seq
  // header rather than stalling the audio pipeline.
  int flags = lwip_fcntl(this->socket_fd_, F_GETFL, 0);
  lwip_fcntl(this->socket_fd_, F_SETFL, flags | O_NONBLOCK);

  this->mic_source_->add_data_callback([this](const std::vector<uint8_t> &data) {
    if (this->streaming_) {
      this->send_audio_(data);
    }
  });
}

void MicStreamer::send_audio_(const std::vector<uint8_t> &data) {
  if (this->socket_fd_ < 0 || data.empty()) {
    return;
  }

  struct sockaddr_in dest;
  std::memset(&dest, 0, sizeof(dest));
  dest.sin_family = AF_INET;
  dest.sin_port = htons(this->port_);
  dest.sin_addr.s_addr = inet_addr(this->address_.c_str());

  const size_t header = sizeof(uint32_t);
  const size_t payload_chunk = this->max_packet_size_ > header ? this->max_packet_size_ - header : 1;

  size_t offset = 0;
  while (offset < data.size()) {
    size_t n = std::min(payload_chunk, data.size() - offset);
    this->packet_buf_.resize(header + n);

    // Little-endian sequence number.
    this->packet_buf_[0] = static_cast<uint8_t>(this->seq_ & 0xFF);
    this->packet_buf_[1] = static_cast<uint8_t>((this->seq_ >> 8) & 0xFF);
    this->packet_buf_[2] = static_cast<uint8_t>((this->seq_ >> 16) & 0xFF);
    this->packet_buf_[3] = static_cast<uint8_t>((this->seq_ >> 24) & 0xFF);
    std::memcpy(this->packet_buf_.data() + header, data.data() + offset, n);

    int sent = ::sendto(this->socket_fd_, this->packet_buf_.data(), this->packet_buf_.size(), 0,
                        reinterpret_cast<struct sockaddr *>(&dest), sizeof(dest));
    if (sent < 0) {
      // Typically EWOULDBLOCK when the lwIP send buffer is momentarily full.
      this->send_errors_++;
    }

    this->seq_++;
    offset += n;
  }
}

void MicStreamer::start() {
  if (this->is_failed() || this->streaming_) {
    return;
  }
  this->seq_ = 0;
  this->send_errors_ = 0;
  this->streaming_ = true;
  this->mic_source_->start();
  ESP_LOGI(TAG, "Streaming microphone audio to %s:%u", this->address_.c_str(), this->port_);
}

void MicStreamer::stop() {
  if (!this->streaming_) {
    return;
  }
  this->streaming_ = false;
  this->mic_source_->stop();
  ESP_LOGI(TAG, "Stopped microphone streaming (%u send errors)", this->send_errors_);
}

void MicStreamer::dump_config() {
  ESP_LOGCONFIG(TAG, "Microphone Streamer:");
  ESP_LOGCONFIG(TAG, "  Destination: %s:%u", this->address_.c_str(), this->port_);
  ESP_LOGCONFIG(TAG, "  Max packet size: %u bytes", (unsigned) this->max_packet_size_);
  if (this->mic_source_ != nullptr) {
    auto info = this->mic_source_->get_audio_stream_info();
    ESP_LOGCONFIG(TAG, "  Format: %u Hz, %u ch, %u-bit", (unsigned) info.get_sample_rate(),
                  (unsigned) info.get_channels(), (unsigned) info.get_bits_per_sample());
  }
}

}  // namespace mic_streamer
}  // namespace esphome
