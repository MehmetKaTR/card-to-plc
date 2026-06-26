@echo off
REM ============================================================
REM  Kart -> PLC  |  KALDIRMA
REM ============================================================
echo Uygulama kapatiliyor...
taskkill /IM CardToPLC.exe /F >nul 2>&1

echo Kisayollar siliniyor...
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\CardToPLC.lnk" >nul 2>&1
del "%USERPROFILE%\Desktop\CardToPLC.lnk" >nul 2>&1

echo Dosyalar siliniyor...
rmdir /S /Q "%LOCALAPPDATA%\CardToPLC" >nul 2>&1

echo.
echo Kaldirma tamamlandi.
pause
