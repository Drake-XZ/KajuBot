' Kaju bot QQ watchdog: run qq-watchdog.ps1 with no visible window (0 = hidden), wait for it to finish.
CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""D:\JiashuBot\bot_setup\qq-watchdog.ps1""", 0, True
