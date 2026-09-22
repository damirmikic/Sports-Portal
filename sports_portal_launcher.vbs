Set shell = CreateObject("WScript.Shell")

shell.Run "powershell.exe -NoProfile -WindowStyle Hidden -Command ""$p=Get-NetTCPConnection -LocalPort 5003 -State Listen -ErrorAction SilentlyContinue; if(-not $p){Start-Process -FilePath 'C:\Users\dkecm\AppData\Local\Programs\Python\Python313\python.exe' -ArgumentList 'app.py' -WorkingDirectory 'C:\Users\dkecm\Desktop\sports portal' -WindowStyle Hidden}""", 0, False

WScript.Sleep 3000

shell.Run "chrome.exe http://127.0.0.1:5003/portal", 1, False
