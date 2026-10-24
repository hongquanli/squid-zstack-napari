# Create a desktop shortcut to the drag-and-drop launcher.
# Drop acquisition folders onto the shortcut (or into its window) to open them in napari.
$repo = $PSScriptRoot
$pythonw = Join-Path (Split-Path (Get-Command python).Source) "pythonw.exe"
$lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "Z-stack Viewer.lnk"
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = $pythonw
$s.Arguments = "`"$repo\launcher.py`""
$s.WorkingDirectory = $repo
$s.IconLocation = "$repo\icon.ico"
$s.Description = "Open Squid z-stacks in napari (drag and drop folders here)"
$s.Save()
Write-Output "Created $lnk"
