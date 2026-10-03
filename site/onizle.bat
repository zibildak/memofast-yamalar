@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Site hazirlaniyor (yama listesi GitHub'dan cekiliyor)...
set SITE_URL=http://localhost:8765/
python build.py --out _onizleme
if errorlevel 1 (
  echo Site hazirlanamadi.
  pause
  exit /b 1
)
echo.
echo Onizleme: http://localhost:8765
echo Kapatmak icin bu pencereyi kapat.
start "" http://localhost:8765
python -m http.server 8765 --directory _onizleme
