Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
baseDir = fso.GetParentFolderName(WScript.ScriptFullName)

pythonExe = "python"
venvPy = baseDir & "\.venv\Scripts\python.exe"
If fso.FileExists(venvPy) Then
    pythonExe = """" & venvPy & """"
End If

cmd = "cmd /c " & _
      "cd /d """ & baseDir & """ && " & _
      "set ""PYTHONUTF8=1"" && " & _
      "set ""PYTHONIOENCODING=utf-8"" && " & _
      "echo [launcher] started at %date% %time%>> newsbot_log.txt && " & _
      ":loop && " & _
      pythonExe & " -X utf8 newsbot.py >> newsbot_log.txt 2>&1 && " & _
      "echo [launcher] newsbot exited at %date% %time%, restart in 15s>> newsbot_log.txt && " & _
      "timeout /t 15 /nobreak >nul && goto loop"

ws.Run cmd, 0, False
MsgBox "News bot started in background.", 64, "News Bot"
