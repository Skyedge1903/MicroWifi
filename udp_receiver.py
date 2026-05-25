import socket
import sounddevice as sd
import numpy as np

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('0.0.0.0', 3333))
sock.setblocking(False)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192)

ESP32_IP = "192.168.4.1"
UDP_PORT = 3333

# -------- HANDSHAKE MINIMAL --------
while True:
    sock.sendto(b"HELLO", (ESP32_IP, UDP_PORT))
    try:
        data, addr = sock.recvfrom(32)
        if data == b"OK":
            break
    except socket.error:
        pass

# -------- RESTE IDENTIQUE --------
sample_rate = 44100
channels = 1
dtype = 'int16'
blocksize = 220

def callback(outdata, frames, time, status):
    try:
        data, addr = sock.recvfrom(440)
        audio_data = np.frombuffer(data, dtype=dtype)

        if len(audio_data) >= frames:
            outdata[:] = audio_data[:frames].reshape(-1, 1)
        else:
            outdata[:len(audio_data)] = audio_data.reshape(-1, 1)
            outdata[len(audio_data):] = 0
    except socket.error:
        outdata[:] = 0

with sd.OutputStream(
    samplerate=sample_rate,
    channels=channels,
    dtype=dtype,
    callback=callback,
    blocksize=blocksize,
    latency=0.020
):
    while True:
        sd.sleep(1000)