"""Run this on your computer (standard library only):  python make_sounds.py

It writes short .wav sounds into sounds/: hit, gem, levelup, hurt and end.
main.py only loads the finished files (it never imports wave).
"""

import math
import os
import struct
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sounds")
RATE = 22050  # samples per second


def synth(notes, decay):
    """notes = [(frequency, seconds), ...] — a sine per note with an exponential drop."""
    samples = []
    for freq, duration in notes:
        n = int(RATE * duration)
        for i in range(n):
            t = i / RATE
            samples.append(math.sin(2 * math.pi * freq * t) * math.exp(-decay * t))
    return samples


def save(name, samples, volume):
    path = os.path.join(OUT, name + ".wav")
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        frames = bytearray()
        for s in samples:
            frames += struct.pack("<h", int(max(-1.0, min(1.0, s * volume)) * 32767))
        f.writeframes(bytes(frames))
    print("wrote sounds/" + name + ".wav (%.2f s)" % (len(samples) / RATE))


def main():
    os.makedirs(OUT, exist_ok=True)
    save("hit", synth([(700, 0.05)], decay=60), volume=0.35)
    save("gem", synth([(1046, 0.05), (1568, 0.09)], decay=25), volume=0.30)
    save("levelup", synth([(523, 0.08), (659, 0.08), (784, 0.14)], decay=12), volume=0.35)
    save("hurt", synth([(180, 0.14)], decay=20), volume=0.45)
    save("end", synth([(392, 0.16), (330, 0.16), (262, 0.35)], decay=8), volume=0.40)


if __name__ == "__main__":
    main()
