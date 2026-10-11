#!/usr/bin/env python3
"""Kokoro-82M local TTS: synthesize text to a WAV file, then play it via
Windows (powershell.exe interop) since WSLg's audio bridge isn't active
in this distro. No network access after the model is cached.
"""
import sys
import os
import tempfile

from winplay import play_wav

def main():
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        return
    text = sys.argv[1].strip()

    from kokoro import KPipeline
    import soundfile as sf

    voice = os.environ.get("CLAUDE_TTS_VOICE", "af_nicole")
    pipeline = KPipeline(lang_code="a")  # 'a' = American English

    out_dir = tempfile.gettempdir()
    wav_path = os.path.join(out_dir, f"claude-tts-{os.getpid()}.wav")

    audio_chunks = []
    for _, _, audio in pipeline(text, voice=voice):
        audio_chunks.append(audio)
    if not audio_chunks:
        return

    import numpy as np
    audio = np.concatenate(audio_chunks)
    sf.write(wav_path, audio, 24000)

    play_wav(wav_path)

    try:
        os.remove(wav_path)
    except OSError:
        pass

if __name__ == "__main__":
    main()
