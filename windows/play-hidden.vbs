' Plays a WAV file with no window appearing at all. Called as:
'   wscript.exe //nologo //B play-hidden.vbs "C:\path\to\file.wav"
'
' wscript.exe is a GUI-subsystem program, so Windows never allocates a console
' window for it. Run(cmd, 0, True) then starts the PowerShell helper with
' window style 0 (hidden) and waits for it, so nothing flashes on screen.
Option Explicit
Dim args, wav, cmd, sh
Set args = WScript.Arguments
If args.Count < 1 Then WScript.Quit 1
wav = args(0)
cmd = "powershell.exe -NoProfile -NonInteractive -Command ""(New-Object System.Media.SoundPlayer '" & wav & "').PlaySync()"""
Set sh = CreateObject("WScript.Shell")
WScript.Quit sh.Run(cmd, 0, True)
