' CipherVault - Silent GUI Launcher
' Runs the Smart GUI Launcher (venv bootstrap + auto-update + GUI start)
' completely hidden, so double-clicking this file opens straight into the app.
Set WshShell = CreateObject("WScript.Shell")
strPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
strLauncher = strPath & "\launcher\launcher_gui.ps1"
cmd = "powershell -NoProfile -ExecutionPolicy Bypass -File " & chr(34) & strLauncher & chr(34)
WshShell.Run cmd, 0, False
