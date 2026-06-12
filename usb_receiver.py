#!/usr/bin/env python3
"""
ESP32 serial mic -> speaker
Version réécrite pour limiter la dérive de latence:
- callback audio sounddevice
- régulation de buffer
- auto-détection du port série
- stats temps réel
"""

import struct
import threading
import queue
import argparse
import sys
import time

import serial
import serial.tools.list_ports
import sounddevice as sd


SYNC1 = 0xAA
SYNC2 = 0x55
HEADER_FMT = "<BBHI"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
CRC_SIZE = 2

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"

FRAME_SAMPLES = 80
FRAME_BYTES = FRAME_SAMPLES * 2   # 160 bytes = 5 ms @ 16 kHz mono int16

QUEUE_MAXSIZE = 3
QUEUE_TARGET = 1
QUEUE_HIGH_MARK = 2

ESP_KEYWORDS = [
    "esp32", "cp210", "ch340", "ch9102", "usb serial", "uart", "silicon labs",
    "wch", "arduino", "ftdi"
]


def checksum16(data: bytes) -> int:
    return sum(data) & 0xFFFF


def score_port(port):
    text = " ".join([
        str(port.device or ""),
        str(port.name or ""),
        str(port.description or ""),
        str(port.hwid or ""),
        str(port.manufacturer or ""),
        str(port.product or ""),
        str(port.interface or ""),
    ]).lower()

    score = 0

    for kw in ESP_KEYWORDS:
        if kw in text:
            score += 10

    if "vid:pid" in text:
        score += 3
    if "usb" in text:
        score += 3
    if "ttyusb" in text or "ttyacm" in text or "com" in text:
        score += 2

    return score


def auto_detect_port():
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        raise RuntimeError("Aucun port série détecté")

    ranked = sorted(ports, key=score_port, reverse=True)

    best = ranked[0]
    if score_port(best) <= 0 and len(ranked) > 1:
        raise RuntimeError(
            "Plusieurs ports trouvés mais aucun ne ressemble clairement à un ESP32 :\n" +
            "\n".join(f"- {p.device} | {p.description} | {p.hwid}" for p in ranked)
        )

    return best.device, ranked


def find_output_device(device_hint=None):
    if device_hint is not None:
        return device_hint
    return sd.default.device[1]


class SerialAudioPlayer:
    def __init__(self, port, baudrate=921600, device=None):
        self.port = port
        self.baudrate = baudrate
        self.device = device

        self.audio_q = queue.Queue(maxsize=QUEUE_MAXSIZE)
        self.running = False

        self.frames_ok = 0
        self.frames_crc_err = 0
        self.frames_drop = 0
        self.frames_miss = 0
        self.frames_silence = 0
        self.last_frame_id = None

        self.ser = None
        self.stream = None
        self.lock = threading.Lock()

    def open_serial(self):
        self.ser = serial.Serial(
            self.port,
            self.baudrate,
            timeout=0.05,
            inter_byte_timeout=0.05,
            exclusive=True
        )

        # Tentative Linux: réduire la latence du driver USB-série
        # Ignoré silencieusement si non supporté.
        try:
            import fcntl
            TIOCGSERIAL = 0x541E
            TIOCSSERIAL = 0x541F
            ASYNC_LOW_LATENCY = 0x2000

            buf = bytearray(60)
            fcntl.ioctl(self.ser.fd, TIOCGSERIAL, buf)
            flags = struct.unpack_from("I", buf, 16)[0]
            struct.pack_into("I", buf, 16, flags | ASYNC_LOW_LATENCY)
            fcntl.ioctl(self.ser.fd, TIOCSSERIAL, buf)
        except Exception:
            pass

    def open_audio(self):
        out_device = find_output_device(self.device)

        self.stream = sd.RawOutputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=FRAME_SAMPLES,
            latency="low",
            device=out_device,
            callback=self.audio_callback
        )

    def start(self):
        self.running = True
        self.open_serial()
        self.open_audio()
        self.stream.start()

        self.reader_thread = threading.Thread(target=self.reader_loop, daemon=True)
        self.reader_thread.start()

    def stop(self):
        self.running = False
        time.sleep(0.1)
        try:
            if self.stream:
                self.stream.stop()
                self.stream.close()
        finally:
            if self.ser:
                self.ser.close()

    def read_exact(self, n):
        buf = bytearray()
        while self.running and len(buf) < n:
            chunk = self.ser.read(n - len(buf))
            if not chunk:
                continue
            buf.extend(chunk)
        return bytes(buf)

    def resync(self):
        state = 0
        while self.running:
            b = self.ser.read(1)
            if not b:
                continue
            v = b[0]
            if state == 0:
                if v == SYNC1:
                    state = 1
            elif state == 1:
                if v == SYNC2:
                    return bytes([SYNC1, SYNC2])
                state = 1 if v == SYNC1 else 0
        return None

    def audio_callback(self, outdata, frames, time_info, status):
        silence = b"\x00" * (frames * 2)

        try:
            chunk = self.audio_q.get_nowait()
        except queue.Empty:
            chunk = silence
            with self.lock:
                self.frames_silence += 1

        if len(chunk) < len(outdata):
            chunk = chunk + silence[len(chunk):]

        outdata[:] = chunk[:len(outdata)]

    def reader_loop(self):
        while self.running:
            prefix = self.resync()
            if prefix is None:
                break

            rest = self.read_exact(HEADER_SIZE - 2)
            if len(rest) != HEADER_SIZE - 2:
                continue

            header = prefix + rest
            _, _, length, frame_id = struct.unpack(HEADER_FMT, header)

            if length <= 0 or length > 4096:
                continue

            payload = self.read_exact(length)
            crc_bytes = self.read_exact(CRC_SIZE)

            if len(payload) != length or len(crc_bytes) != CRC_SIZE:
                continue

            recv_crc = struct.unpack("<H", crc_bytes)[0]
            calc_crc = checksum16(payload)

            if recv_crc != calc_crc:
                with self.lock:
                    self.frames_crc_err += 1
                continue

            with self.lock:
                if self.last_frame_id is not None:
                    missed = (frame_id - self.last_frame_id - 1) & 0xFFFFFFFF
                    if missed < 0x7FFFFFFF:
                        self.frames_miss += missed
                self.last_frame_id = frame_id

            # Régulation anti-dérive:
            # si la queue devient trop profonde, on recadre vers une cible faible.
            qsize = self.audio_q.qsize()
            if qsize >= QUEUE_HIGH_MARK:
                to_drop = qsize - QUEUE_TARGET
                dropped = 0
                for _ in range(to_drop):
                    try:
                        self.audio_q.get_nowait()
                        dropped += 1
                    except queue.Empty:
                        break
                with self.lock:
                    self.frames_drop += dropped

            try:
                self.audio_q.put_nowait(payload)
                with self.lock:
                    self.frames_ok += 1
            except queue.Full:
                with self.lock:
                    self.frames_drop += 1

    def print_stats_loop(self):
        while self.running:
            time.sleep(1.0)
            with self.lock:
                ok = self.frames_ok
                crc_err = self.frames_crc_err
                drop = self.frames_drop
                miss = self.frames_miss
                silence = self.frames_silence

            qsize = self.audio_q.qsize()
            latency_ms = qsize * (FRAME_SAMPLES / SAMPLE_RATE) * 1000.0

            print(
                f"port={self.port} ok={ok} crc_err={crc_err} "
                f"drop={drop} miss={miss} silence={silence} "
                f"queue={qsize} latency≈{latency_ms:.1f}ms",
                file=sys.stderr
            )


def main():
    parser = argparse.ArgumentParser(description="ESP32 serial mic -> speaker auto detect")
    parser.add_argument("--port", default=None, help="Port série, ex: COM5 ou /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=921600, help="Baudrate")
    parser.add_argument("--device", default=None, help="ID ou nom du périphérique audio de sortie")
    parser.add_argument("--list-devices", action="store_true", help="Lister les périphériques audio")
    parser.add_argument("--list-ports", action="store_true", help="Lister les ports série")
    args = parser.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        return

    ports = list(serial.tools.list_ports.comports())
    if args.list_ports:
        for p in ports:
            print(f"{p.device} | {p.description} | {p.hwid} | score={score_port(p)}")
        return

    if args.port:
        port = args.port
    else:
        port, ranked = auto_detect_port()
        print("Port auto-détecté :", port, file=sys.stderr)
        for p in ranked[:5]:
            print(f"  {p.device} | {p.description} | score={score_port(p)}", file=sys.stderr)

    player = SerialAudioPlayer(port, args.baud, args.device)
    player.start()

    stats_thread = threading.Thread(target=player.print_stats_loop, daemon=True)
    stats_thread.start()

    print("Streaming audio... Ctrl+C pour arrêter.", file=sys.stderr)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        player.stop()


if __name__ == "__main__":
    main()