@echo off
REM ============================================================
REM  Kart -> PLC  |  Hedef bilgisayara KURULUM
REM  Bu PC'de Python GEREKMEZ. CardToPLC.exe ile ayni
REM  klasorde bu dosyayi cift tiklayin.
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist "CardToPLC.exe" (
    echo HATA: CardToPLC.exe bu klasorde bulunamadi.
    echo Lutfen install.bat'i exe ile ayni klasore koyun.
    pause
    exit /b 1
)

set "APPDIR=%LOCALAPPDATA%\CardToPLC"
echo Kurulum klasoru: %APPDIR%
if not exist "%APPDIR%" mkdir "%APPDIR%"

echo Dosyalar kopyalaniyor...
copy /Y "CardToPLC.exe" "%APPDIR%\" >nul
if exist "config.json" copy /Y "config.json" "%APPDIR%\" >nul

REM --- Windows acilisinda otomatik baslat (Startup klasoru) ---
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%STARTUP%\CardToPLC.lnk'); $s.TargetPath='%APPDIR%\CardToPLC.exe'; $s.WorkingDirectory='%APPDIR%'; $s.Save()"

REM --- Masaustu kisayolu ---
powershell -NoProfile -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut($d+'\CardToPLC.lnk'); $s.TargetPath='%APPDIR%\CardToPLC.exe'; $s.WorkingDirectory='%APPDIR%'; $s.Save()"

echo.
echo Uygulama simdi baslatiliyor (tepside calisacak)...
start "" "%APPDIR%\CardToPLC.exe"

echo.
echo TAMAMLANDI.
echo - Uygulama sistem tepsisinde (sag alt) calisiyor.
echo - Her Windows acilisinda otomatik baslayacak.
echo - Ayar icin tepsi ikonuna cift tiklayin.
echo - Kaldirmak icin uninstall.bat'i calistirin.
pause
