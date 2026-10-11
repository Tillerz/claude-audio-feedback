#!/usr/bin/env python3
"""Resident TTS daemon: loads Kokoro once, then serves synth+play requests
over a Unix socket so hooks get near-instant audio instead of eating a
10-15s cold model-load on every single notification.

Protocol: client connects, sends one line of UTF-8, disconnects.
  "<text>"                        -> synthesize and play it (fire and forget)
  "RENDER\t<wav path>\t<speed>\t<text>"
                                  -> synthesize to that WAV path instead of
                                     playing, then reply "OK" or "ERR <msg>"
                                     on the same connection. Used by the
                                     ~/bin/espeak shim for the Eloquent
                                     VS Code extension.
Requests are handled one at a time, in arrival order.
"""
import os
import socket
import sys
import tempfile
import threading
import queue

from winplay import play_wav

DIR = os.path.dirname(os.path.abspath(__file__))
SOCK_PATH = os.path.join(tempfile.gettempdir(), "claude-tts.sock")
VOICE = os.environ.get("CLAUDE_TTS_VOICE", "af_nicole")
RENDER_TIMEOUT = 120  # seconds a RENDER client waits, incl. any queued playback

# jobs are (kind, text, wav_path, speed, reply) where reply is a Queue the
# worker posts the outcome to for "render" jobs, or None for "play" jobs.
_q: "queue.Queue" = queue.Queue()


def worker():
    from kokoro import KPipeline
    import soundfile as sf
    import numpy as np

    pipeline = KPipeline(lang_code="a")
    print("tts_server: pipeline loaded, ready", flush=True)

    while True:
        job = _q.get()
        if job is None:
            break
        kind, text, out_path, speed, reply = job
        try:
            chunks = [a for _, _, a in pipeline(text, voice=VOICE, speed=speed)]
            if not chunks:
                raise RuntimeError("no audio produced")
            audio = np.concatenate(chunks)

            if kind == "render":
                sf.write(out_path, audio, 24000)
                reply.put("OK")
                continue

            wav_path = os.path.join(tempfile.gettempdir(), f"claude-tts-{os.getpid()}.wav")
            sf.write(wav_path, audio, 24000)
            play_wav(wav_path)
            try:
                os.remove(wav_path)
            except OSError:
                pass
        except Exception as e:
            print(f"tts_server: error synthesizing {text!r}: {e}", file=sys.stderr, flush=True)
            if reply is not None:
                reply.put(f"ERR {e}")


def main():
    # Clean up a stale socket from a crashed previous instance.
    if os.path.exists(SOCK_PATH):
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.connect(SOCK_PATH)
            probe.close()
            print("tts_server: another instance is already listening, exiting", flush=True)
            return
        except OSError:
            os.remove(SOCK_PATH)

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK_PATH)
    srv.listen(8)
    print(f"tts_server: listening on {SOCK_PATH}", flush=True)

    try:
        while True:
            conn, _ = srv.accept()
            with conn:
                data = b""
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                    if b"\n" in data:
                        break
                line = data.decode("utf-8", "replace").strip()
                if not line:
                    continue
                if line.startswith("RENDER\t"):
                    parts = line.split("\t", 3)
                    if len(parts) != 4:
                        conn.sendall(b"ERR bad RENDER request\n")
                        continue
                    _, out_path, speed_s, text = parts
                    try:
                        speed = float(speed_s)
                    except ValueError:
                        speed = 1.0
                    reply: "queue.Queue[str]" = queue.Queue(maxsize=1)
                    _q.put(("render", text, out_path, speed, reply))
                    try:
                        result = reply.get(timeout=RENDER_TIMEOUT)
                    except queue.Empty:
                        result = "ERR timeout"
                    conn.sendall((result + "\n").encode("utf-8"))
                else:
                    _q.put(("play", line, None, 1.0, None))
    finally:
        try:
            os.remove(SOCK_PATH)
        except OSError:
            pass


if __name__ == "__main__":
    main()
