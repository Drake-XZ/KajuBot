Set sh = CreateObject("WScript.Shell")
cmd = "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""D:\JiashuBot\bot_setup\bot-panel.ps1"""
For Each a In WScript.Arguments
    cmd = cmd & " """ & a & """"
Next
sh.Run cmd, 0, False
