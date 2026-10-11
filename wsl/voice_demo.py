#!/usr/bin/env python3
"""Play a few candidate Kokoro voices back to back so the user can compare."""
import subprocess
import tempfile
import os

from kokoro import KPipeline
import soundfile as sf
import numpy as np

CANDIDATES = [
    ("af_bella", "Voice one, Bella."),
    ("af_sky", "Voice two, Sky."),
    ("af_nicole", "Voice three, Nicole."),
    ("bf_emma", "Voice four, Emma, British."),
]
SAMPLE = "Your task is done, and everything looks good!"

pipeline = KPipeline(lang_code="a")


def synth_and_play(text, voice):
    chunks = [audio for _, _, audio in pipeline(text, voice=voice)]
    if not chunks:
        return
    audio = np.concatenate(chunks)
    wav_path = os.path.join(tempfile.gettempdir(), f"claude-tts-demo-{voice}.wav")
    sf.write(wav_path, audio, 24000)
    win_path = subprocess.check_output(["wslpath", "-w", wav_path], text=True).strip()
    ps_cmd = f"(New-Object System.Media.SoundPlayer '{win_path}').PlaySync();"
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd], check=False)
    os.remove(wav_path)


for voice, label in CANDIDATES:
    synth_and_play(label, "af_heart")  # announce in the known-good voice
    synth_and_play(SAMPLE, voice)
