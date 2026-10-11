# claude-audio-feedback

Local text-to-speech for Claude Code using Kokoro TTS. Claude speaks out loud when it needs you,
when it finishes, and when a tool fails. No cloud, no API key, no network after the first model download.
You can also hook it up as local tts service for the VS Code plugin Eloquent (see below).

It answers fast. Loading the Kokoro model takes 10-15 seconds, so a small
resident daemon loads it once and keeps it in memory. Everything after that is
about a second.

Runs in WSL (eg. Ubuntu 24.04) and plays the sound through Windows.

> **This folder is a copy, not the live install.** The running code lives in
> `~/.claude/scripts/tts/`. See [Keeping this copy in sync](#keeping-this-copy-in-sync).

## How it works

```
Claude Code event (needs input / stopped / tool failed / ...)
      |
      |  hook in ~/.claude/settings.json
      v
speak.sh <event>            picks the sentence for the event
      |
      |-- fast path: Unix socket /tmp/claude-tts.sock
      |        -> tts_server.py (resident daemon, model already in RAM, ~0.3 s)
      |
      `-- slow path: no daemon yet
               -> speak.py (cold start, 10-15 s) and starts the daemon
                  so the next event is fast
      |
      v
Kokoro-82M makes a WAV in /tmp
      |
      v
winplay.py -> wscript.exe play-hidden.vbs -> System.Media.SoundPlayer
```

**Why Windows plays the sound.** WSLg's audio bridge is not active here, so WSL
itself has no sound device (`/dev/snd` is empty and there is no
`/mnt/wslg/PulseServer`). The WAV is written where Windows can read it, and
Windows is asked to play it.

**Why not call PowerShell straight from WSL?** That works, but Windows
allocates a console window for it, which flashes on screen on every single
notification. `wscript.exe` is a GUI-subsystem program, so it never gets a
console, and the small `play-hidden.vbs` it runs starts the PowerShell helper
with window style 0 (hidden) and waits for it. Nothing appears on screen.

`winplay.py` falls back to the direct `powershell.exe` call if the `.vbs` is
missing, so playback never silently stops working.

## Files

| File | Where it belongs | What it is |
|---|---|---|
| `wsl/speak.sh` | `~/.claude/scripts/tts/speak.sh` | Hook entry point. Picks the phrase, tries the daemon, falls back to cold synthesis. |
| `wsl/tts_server.py` | `~/.claude/scripts/tts/tts_server.py` | Resident daemon. Keeps the model in RAM and listens on a Unix socket. |
| `wsl/speak.py` | `~/.claude/scripts/tts/speak.py` | One-shot synthesis. Used as the cold fallback. |
| `wsl/winplay.py` | `~/.claude/scripts/tts/winplay.py` | Plays a WAV through Windows with no window flashing up. Used by both of the above. |
| `windows/play-hidden.vbs` | `%USERPROFILE%\.claude\tts\play-hidden.vbs` | Run by `wscript.exe`. Starts the hidden PowerShell player and waits for it. |
| `wsl/voice_demo.py` | `~/.claude/scripts/tts/voice_demo.py` | Plays sample lines in several voices, to choose one. |
| `wsl/bin-espeak` | `~/bin/espeak` | Stand-in for `espeak`. Lets VS Code extensions that use "local system TTS" use this Kokoro voice. See below. |
| `wsl/requirements.txt` | - | Exact package list of the live venv (Python 3.12.3). |
| `claude-code/settings.hooks.json` | merge into `~/.claude/settings.json` | The six hook entries that call `speak.sh`. |
| `vscode/Machine-settings.eloquent.json` | merge into `~/.vscode-server/data/Machine/settings.json` | Points the Eloquent extension at the local voice. |

The venv itself is **not** in this folder. It is 5.2 GB (PyTorch, CUDA wheels, spaCy, Kokoro). Rebuild it from `requirements.txt`.

## Events that speak

| Hook event | What you hear |
|---|---|
| `Notification` | The actual notification text, e.g. a permission request. |
| `Stop` | One random line from: "All done!", "Finished up!", "Ready when you are.", "Task complete.", "All set!" |
| `PostToolUseFailure` | "`<ToolName>` failed." Rate limited, see below. |
| `PreCompact` | One random line about tidying memory. |
| `SubagentStop` | One random line about a helper task finishing. |
| `SessionStart` | Nothing. It only warms up the daemon so the first real event is fast. |

## Socket protocol

`tts_server.py` listens on `/tmp/claude-tts.sock`. A client connects, sends one
line of UTF-8, and disconnects.

| Line | Effect |
|---|---|
| `<text>` | Synthesize and play it. Fire and forget, no reply. |
| `RENDER\t<wav path>\t<speed>\t<text>` | Synthesize to that WAV path instead of playing. Replies `OK` or `ERR <msg>` on the same connection. |

`speed` is a multiplier, `1.0` is normal. Jobs run one at a time in arrival
order, so a `RENDER` can wait behind a playback. `RENDER_TIMEOUT` in the script
caps that wait at 120 s.

## Eloquent VS Code extension (Read Aloud)

[Eloquent](https://marketplace.visualstudio.com/items?itemName=jshwek.eloquent)
reads selected text aloud. With `eloquent.provider` set to `local` it shells out
to the platform's own voice - and on Linux that is literally:

```
espeak -w <out.wav> -s <words per minute> <text>
```

It then reads the WAV back and plays it in a VS Code panel. So no HTTP server
and no extension patching is needed: `~/bin/espeak` answers that call and
returns a Kokoro WAV instead.

```
Eloquent "Read Aloud"
      |
      |  spawn("espeak", ["-w", f, "-s", wpm, text])     PATH hit: ~/bin/espeak
      v
~/bin/espeak           maps wpm -> speed (175 wpm = 1.0)
      |
      |  RENDER over /tmp/claude-tts.sock
      v
tts_server.py          model already in RAM, writes the WAV  (~1.2 s)
      |
      v
Eloquent reads the file and plays it in a VS Code webview panel
```

**Setup:**

1. Install the extension **in the WSL remote**, not on the Windows side. On
   Windows it would use SAPI and never touch this.
2. `cp wsl/bin-espeak ~/bin/espeak && chmod +x ~/bin/espeak`
3. Set `"eloquent.provider": "local"` in
   `~/.vscode-server/data/Machine/settings.json` (Remote [WSL] settings).

**Why it works here**

- Real `espeak` is **not installed** in this WSL, so there is no clash. If it is
  ever installed, PATH order decides, and `~/bin` comes first.
- `~/bin` is on the VS Code extension host's PATH (via `~/.profile` and
  `~/.bashrc`).
- Playback happens in the VS Code panel, which runs on Windows. WSL needs no
  sound device for this path.
- `eloquent.voice` is ignored by the local provider, so the shim uses
  `CLAUDE_TTS_VOICE` instead - the same voice as everything else here.
- `eloquent.speed` arrives as words per minute and is divided by 175.

**Known rough edge:** Eloquent names its temp file `eloquent-<time>.mp3` even
when the data is a WAV. The webview `<audio>` element normally detects the real
format and plays it anyway. If a read-aloud ever shows "Error loading audio",
that is the cause, and the fix is to encode real MP3 in the shim.

**Test the shim the way Eloquent calls it:**

```bash
~/bin/espeak -w /tmp/t.wav -s 175 "Hello from Kokoro."
~/.claude/scripts/tts/venv/bin/python3 -c "import soundfile as sf; print(sf.info('/tmp/t.wav'))"
```

## Install from scratch

1. **System packages** (WSL):
   ```bash
   sudo apt install -y python3-venv python3-pip jq
   ```
   `jq` is needed by `speak.sh` to read the hook payload.

2. **Create the folder and venv:**
   ```bash
   mkdir -p ~/.claude/scripts/tts
   python3 -m venv ~/.claude/scripts/tts/venv
   ~/.claude/scripts/tts/venv/bin/pip install -r requirements.txt
   ```
   First run downloads the Kokoro-82M model from Hugging Face into
   `~/.cache/huggingface`. After that it is offline.

3. **Copy the scripts:**
   ```bash
   cp wsl/speak.sh wsl/speak.py wsl/tts_server.py wsl/winplay.py wsl/voice_demo.py ~/.claude/scripts/tts/
   chmod +x ~/.claude/scripts/tts/*.py ~/.claude/scripts/tts/speak.sh
   mkdir -p ~/bin && cp wsl/bin-espeak ~/bin/espeak && chmod +x ~/bin/espeak
   ```
   And the one Windows-side file, which keeps the console window from flashing:
   ```bash
   WINHOME="$(wslpath -u "$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')")"
   mkdir -p "$WINHOME/.claude/tts"
   cp windows/play-hidden.vbs "$WINHOME/.claude/tts/"
   ```

4. **Add the hooks.** Merge `claude-code/settings.hooks.json` into
   `~/.claude/settings.json`. Do not replace the file - keep your other keys.
   ```bash
   python3 - <<'PY'
   import json, os
   p = os.path.expanduser("~/.claude/settings.json")
   s = json.load(open(p))
   add = json.load(open("claude-code/settings.hooks.json"))["hooks"]
   s.setdefault("hooks", {}).update(add)
   json.dump(s, open(p, "w"), indent=2, ensure_ascii=False)
   PY
   ```

5. **Test:**
   ```bash
   ~/.claude/scripts/tts/venv/bin/python3 ~/.claude/scripts/tts/speak.py "test one two three"
   ```
   Then start a new Claude Code session, or open `/hooks` once so the config
   reloads.

6. **Optional - wire up the Eloquent VS Code extension.** See
   [Eloquent VS Code extension (Read Aloud)](#eloquent-vs-code-extension-read-aloud)
   for how and why this works.
   ```bash
   code --install-extension jshwek.eloquent     # must land in the WSL remote
   ```
   Then merge `vscode/Machine-settings.eloquent.json` into
   `~/.vscode-server/data/Machine/settings.json`:
   ```bash
   python3 - <<'PY'
   import json, os
   p = os.path.expanduser("~/.vscode-server/data/Machine/settings.json")
   os.makedirs(os.path.dirname(p), exist_ok=True)
   s = json.load(open(p)) if os.path.exists(p) else {}
   s.update(json.load(open("vscode/Machine-settings.eloquent.json")))
   json.dump(s, open(p, "w"), indent=2, ensure_ascii=False)
   PY
   ```
   Reload the VS Code window, select text, press `Ctrl+Shift+R`.
   Step 2 of this list (`~/bin/espeak`) must already be done.

## Settings

| Environment variable | Default | Meaning |
|---|---|---|
| `CLAUDE_TTS_VOICE` | `af_nicole` | Kokoro voice id. Run `voice_demo.py` to compare. |
| `CLAUDE_TTS_ERROR_COOLDOWN` | `45` | Seconds. At most one spoken tool error per window, so a burst of failures is not announced many times. |
| `CLAUDE_TTS_DIR` | `~/.claude/scripts/tts` | Install location, read by `~/bin/espeak` when it talks to the daemon. |
| `CLAUDE_TTS_VBS` | `<Windows user profile>/.claude/tts/play-hidden.vbs` | Where the hidden-window player lives. |

State lives in `~/.claude/scripts/tts/state/`. Logs are `tts.log` and
`tts_server.log` in the same folder.

### Choosing the voice

The default `af_nicole` (soft, breathy, American English) was picked by ear out
of `af_bella`, `af_sky`, `af_nicole` and `bf_emma`. Kokoro-82M has about ten
more; the full list and quality grades are on the
[hexgrad/Kokoro-82M model card](https://huggingface.co/hexgrad/Kokoro-82M).

Set `CLAUDE_TTS_VOICE` in the environment before Claude Code starts, or change
the default in **both** `speak.py` and `tts_server.py` - they must match.
Restart the daemon afterwards: kill it by pid and it comes back on the next
event, or on the `SessionStart` warm-up.

## Testing and troubleshooting

```bash
# Direct one-shot synthesis (slow, no daemon needed):
~/.claude/scripts/tts/venv/bin/python3 ~/.claude/scripts/tts/speak.py "hello there"

# Full hook path (fast once the daemon is warm):
echo '{}' | bash ~/.claude/scripts/tts/speak.sh stop
echo '{"message":"test notification text"}' | bash ~/.claude/scripts/tts/speak.sh notification

# Compare voices:
~/.claude/scripts/tts/venv/bin/python3 ~/.claude/scripts/tts/voice_demo.py

# Is the daemon alive?
ls -la /tmp/claude-tts.sock      # type 's' = listening
pgrep -fa tts_server.py
tail ~/.claude/scripts/tts/tts_server.log
```

| Symptom | Cause | Fix |
|---|---|---|
| Silence, no error | `jq` missing, so `speak.sh` gets an empty message | `sudo apt install jq` |
| Every event takes 10-15 s | Daemon not running | Check `tts_server.log`. `speak.sh` restarts it on the next event. |
| Daemon dies when a hook ends | A plain background job gets SIGHUP when `wsl.exe` tears down | Already handled: the daemon is started with `setsid nohup`. `disown` alone is not enough. |
| No sound at all | `powershell.exe` not reachable from WSL | Check `which powershell.exe`, and that WSL interop is on. |

## Keeping this copy in sync

The live install is the source of truth while it runs. To refresh this folder:

```bash
T=~/.claude/scripts/tts
A=~/projects/claude-audio-feedback
cp $T/speak.sh $T/speak.py $T/tts_server.py $T/winplay.py $T/voice_demo.py $A/wsl/
cp ~/bin/espeak $A/wsl/bin-espeak
jq '{"eloquent.provider"}' ~/.vscode-server/data/Machine/settings.json > $A/vscode/Machine-settings.eloquent.json
$T/venv/bin/pip freeze > $A/wsl/requirements.txt
jq '{hooks: (.hooks | del(.UserPromptExpansion))}' ~/.claude/settings.json > $A/claude-code/settings.hooks.json
```

`UserPromptExpansion` is left out on purpose - that hook belongs to the
[reminder](../reminder/) project.

## Considered and declined: announcing token or context usage

Asked 2026-08-31: announce every 20% of context or token usage. **Not possible
as a hook.** Hooks never receive token, context or cost data - only structural
fields such as `tool_name` and `session_id`. That data is exposed in exactly one
place, the custom `statusLine` command (`context_window.used_percentage`,
`cost.total_cost_usd` and friends arrive on its stdin), but configuring
`statusLine` replaces the whole visible status line rather than adding a silent
hook. Skipped on purpose rather than give up the status line.

Do not re-propose this without a new reason. The trade-off was understood and
declined, not left open.

## Related

The [reminder](../reminder/) project reuses this venv and this Kokoro install to
pre-render its reminder WAV files, and its `play-hidden.vbs` to stay silent on
screen. It does not need the daemon.
