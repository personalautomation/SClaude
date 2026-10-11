' Starts KeepAwake.ps1 completely hidden, at logon.
'
' It lives in the startup folder rather than in Task Scheduler: schtasks refuses
' with "Access is denied" on any logon trigger (ONLOGON), because such a trigger
' counts as privileged, and PowerShell from WSL is unprivileged. The startup
' folder needs no administrator rights and does exactly the same thing.
'
' The wrapper is worth having in its own right: a shortcut to powershell.exe
' blinks a console window at every logon, while WScript.Shell with flag 0 shows
' nothing at all.
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & _
  sh.ExpandEnvironmentStrings("%USERPROFILE%") & "\.keepawake\KeepAwake.ps1""", 0, False
