@echo off
REM ============================================================
REM  Kart -> PLC  |  Tek tikla EXE derleme (Windows)
REM  Python 3.9+ kurulu olmali. Bu dosyayi cift tiklayin.
REM ============================================================
cd /d "%~dp0"

echo.
echo [1/3] Gerekli paketler kuruluyor...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo HATA: paket kurulumu basarisiz. Python kurulu mu?
    pause
    exit /b 1
)

echo.
echo Calisan eski surum (varsa) kapatiliyor...
taskkill /IM CardToPLC.exe /F >nul 2>&1
echo Eski derleme klasorleri temizleniyor...
rmdir /S /Q build >nul 2>&1
rmdir /S /Q dist >nul 2>&1
del /Q CardToPLC.spec >nul 2>&1

echo.
echo [2/3] EXE derleniyor (CardToPLC.exe)...
REM --windowed : konsol penceresi acilmaz (tepside calisir)
REM --onefile  : tek exe dosyasi
pyinstaller --noconfirm --onefile --windowed --name "CardToPLC" card_to_plc.py
if errorlevel 1 (
    echo HATA: derleme basarisiz.
    pause
    exit /b 1
)

echo.
echo [3/3] Tamamlandi.
echo EXE konumu:  dist\CardToPLC.exe
echo config.json EXE ile ayni klasorde olusur.
echo.
pause
