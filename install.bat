@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo === Cutline: installation ===

where py >nul 2>nul || (echo Python 3.12 is required: https://www.python.org/downloads/ & pause & exit /b 1)
py -3.12 --version >nul 2>nul || (echo Python 3.12 is required: https://www.python.org/downloads/ & pause & exit /b 1)

where node >nul 2>nul || (
  echo Node.js not found, installing via winget...
  winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
  echo If Node.js was just installed, close this window and run install.bat again.
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  py -3.12 -m venv .venv || (pause & exit /b 1)
)
echo Installing packages (this can take several minutes)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.lock || (pause & exit /b 1)

if not exist "tools\ffmpeg\ffmpeg.exe" (
  echo Downloading FFmpeg...
  powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; $z=Join-Path $env:TEMP 'cutline-ffmpeg.zip'; Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $z; $d=Join-Path $env:TEMP 'cutline-ffmpeg'; if(Test-Path $d){Remove-Item $d -Recurse -Force}; Expand-Archive $z $d; New-Item -ItemType Directory -Force 'tools\ffmpeg' | Out-Null; Copy-Item (Get-ChildItem $d -Recurse -Filter ffmpeg.exe | Select-Object -First 1).FullName 'tools\ffmpeg\ffmpeg.exe'; Copy-Item (Get-ChildItem $d -Recurse -Filter ffprobe.exe | Select-Object -First 1).FullName 'tools\ffmpeg\ffprobe.exe'" || (pause & exit /b 1)
)

echo Downloading the speech model (about 1.6 GB, once)...
".venv\Scripts\python.exe" -c "from faster_whisper.utils import download_model; download_model('large-v3-turbo', cache_dir='models')" || echo Model download failed. It will be retried on the first run.

echo Building Cutline.exe and the desktop shortcut...
".venv\Scripts\pyinstaller.exe" --noconfirm --onefile --windowed --name Cutline --icon "%~dp0assets\logo.ico" --distpath "%TEMP%\cutline-dist" --workpath "%TEMP%\cutline-build" --specpath "%TEMP%\cutline-build" scripts\cutline_launcher.py >nul 2>nul
if exist "%TEMP%\cutline-dist\Cutline.exe" copy /y "%TEMP%\cutline-dist\Cutline.exe" "%~dp0Cutline.exe" >nul
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Cutline.lnk'); $t=if(Test-Path '%~dp0Cutline.exe'){'%~dp0Cutline.exe'}else{'%~dp0Cutline.bat'}; $s.TargetPath=$t; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0assets\icon-x.ico,0'; $s.Save()"

echo.
echo Done. Start Cutline from the desktop shortcut or Cutline.bat.
pause
