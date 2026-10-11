#!/usr/bin/env python3
"""Play a WAV through Windows from WSL, without a window flashing up.

Calling powershell.exe straight from WSL makes Windows allocate a console
window for it, which flashes on screen on every single notification.
wscript.exe is a GUI-subsystem program, so it never gets a console; the
.vbs it runs starts the PowerShell helper hidden and waits for it.

Falls back to the plain powershell.exe call if the .vbs is missing, so
playback never silently stops working.
"""
import os
import subprocess

VBS_ENV = "CLAUDE_TTS_VBS"


def _win(path):
    return subprocess.run(["wslpath", "-w", path], capture_output=True,
                          text=True).stdout.strip()


def _vbs_path():
    env = os.environ.get(VBS_ENV)
    if env:
        return os.path.expanduser(env)
    # stderr is dropped on purpose: cmd.exe warns when the working directory is
    # a WSL-only path, but still answers correctly.
    profile = subprocess.run(["cmd.exe", "/c", "echo %USERPROFILE%"],
                             capture_output=True, text=True).stdout.strip()
    if not profile or profile.startswith("%"):
        return None
    home = subprocess.run(["wslpath", "-u", profile], capture_output=True,
                          text=True).stdout.strip()
    return os.path.join(home, ".claude", "tts", "play-hidden.vbs")


def play_wav(wav_path):
    """Play wav_path and block until it has finished."""
    win_wav = _win(wav_path)
    vbs = _vbs_path()
    if vbs and os.path.exists(vbs):
        subprocess.run(["wscript.exe", "//nologo", "//B", _win(vbs), win_wav],
                       check=False)
        return
    ps = f"(New-Object System.Media.SoundPlayer '{win_wav}').PlaySync();"
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                    "-WindowStyle", "Hidden", "-Command", ps], check=False)
