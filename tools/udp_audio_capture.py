#!/usr/bin/env python3
"""Capture raw PCM audio streamed by the Voice PE `mic_streamer` component over UDP.

The firmware sends one UDP datagram per chunk, each prefixed with a 4-byte
little-endian sequence number so dropped packets can be detected. This script
strips the header, writes the PCM to a WAV file, and reports any gaps.

Example (raw stereo, 16 kHz, 16-bit -> the package default):
    python3 tools/udp_audio_capture.py -o kitchen.wav -c 2

Match the flags to your `mic_streamer` config:
    channels      -> -c   (1 for a single mic index, 2 for channels: "0,1")
    bits_per_sample-> -w   (2 for 16-bit, 4 for 32-bit)
    sample rate is fixed at 16000 by the i2s_mics config.
"""
import argparse
import signal
import socket
import struct
import sys
import time
import wave


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default="capture.wav", help="output WAV file (default: capture.wav)")
    ap.add_argument("-p", "--port", type=int, default=6056, help="UDP port to listen on (default: 6056)")
    ap.add_argument("-b", "--bind", default="0.0.0.0", help="local address to bind (default: all interfaces)")
    ap.add_argument("-r", "--rate", type=int, default=16000, help="sample rate (default: 16000)")
    ap.add_argument("-c", "--channels", type=int, default=2, help="channel count (default: 2)")
    ap.add_argument("-w", "--width", type=int, default=2, help="bytes per sample: 2=16-bit, 4=32-bit (default: 2)")
    ap.add_argument("--no-seq", action="store_true", help="packets have no 4-byte sequence header")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Large receive buffer so a momentary stall in this script doesn't drop audio.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 21)
    sock.bind((args.bind, args.port))
    sock.settimeout(1.0)

    wf = wave.open(args.output, "wb")
    wf.setnchannels(args.channels)
    wf.setsampwidth(args.width)
    wf.setframerate(args.rate)

    bytes_per_sec = args.rate * args.channels * args.width
    print(
        f"Listening on UDP {args.bind}:{args.port} -> {args.output} "
        f"({args.rate} Hz, {args.channels} ch, {args.width * 8}-bit). Ctrl-C to stop.",
        flush=True,
    )

    running = True

    def _stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    expected = None
    total = 0
    dropped = 0
    last_report = time.time()

    while running:
        try:
            pkt, _ = sock.recvfrom(2048)
        except socket.timeout:
            continue

        if args.no_seq:
            payload = pkt
        else:
            if len(pkt) < 4:
                continue
            seq = struct.unpack_from("<I", pkt, 0)[0]
            payload = pkt[4:]
            if expected is not None and seq != expected:
                dropped += (seq - expected) & 0xFFFFFFFF
            expected = (seq + 1) & 0xFFFFFFFF

        wf.writeframes(payload)
        total += len(payload)

        now = time.time()
        if now - last_report >= 1.0:
            secs = total / bytes_per_sec if bytes_per_sec else 0
            print(f"\r{secs:7.1f}s  {total:>10} bytes  {dropped} dropped pkts ", end="", flush=True)
            last_report = now

    wf.close()
    sock.close()
    secs = total / bytes_per_sec if bytes_per_sec else 0
    print(f"\nSaved {args.output}: {secs:.1f}s, {total} bytes, {dropped} dropped packets.")
    if dropped:
        print("WARNING: dropped packets -> the recording has gaps. Move closer to AP or lower max_packet_size.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
