' VBScript de khoi chay crawler ngam trong background (khong hien cua so console)
Set WshShell = CreateObject("WScript.Shell")
strCurDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\.."
WshShell.CurrentDirectory = strCurDir
WshShell.Run "python scripts\run_production_crawler.py", 0, False

