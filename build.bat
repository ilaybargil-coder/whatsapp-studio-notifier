@echo off
title WhatsApp Notifier — Build

echo.
echo  ====================================
echo   WhatsApp Studio Notifier — Build
echo  ====================================
echo.

:: ── Find Python ────────────────────────────────────────────────────────────
set PYTHON=

:: Try common commands first
python --version >nul 2>&1 && set PYTHON=python
if "%PYTHON%"=="" py --version >nul 2>&1 && set PYTHON=py

:: Search common install locations
if "%PYTHON%"=="" (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "C:\Python313\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
        "C:\Python310\python.exe"
    ) do (
        if exist %%P (
            set PYTHON=%%P
            goto :found_python
        )
    )
)

:found_python
if "%PYTHON%"=="" (
    echo  [ERROR] Python not found!
    echo.
    echo  Please install Python from https://www.python.org/downloads/
    echo  Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo  [OK] Using Python: %PYTHON%
echo.

:: ── Install dependencies ───────────────────────────────────────────────────
echo  [1/3] Installing dependencies...
%PYTHON% -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo  [ERROR] pip install failed.
    pause
    exit /b 1
)

:: ── Make sure logo_icon.ico exists ─────────────────────────────────────────
if not exist "logo_icon.ico" (
    echo  [INFO] Generating logo_icon.ico...
    %PYTHON% -c "from PIL import Image; img=Image.open('logo_icon.png').convert('RGBA'); img.save('logo_icon.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(256,256)])"
)

:: ── Build ──────────────────────────────────────────────────────────────────
echo  [2/3] Building exe...
%PYTHON% -m PyInstaller SendMessage.spec --noconfirm
if errorlevel 1 (
    echo.
    echo  [ERROR] Build failed — see errors above.
    pause
    exit /b 1
)

:: ── Copy to Desktop ────────────────────────────────────────────────────────
echo.
echo  [3/3] Copying to Desktop...
copy /Y "dist\WhatsApp_Notifier.exe" "%USERPROFILE%\Desktop\WhatsApp_Notifier.exe" >nul

echo.
echo  ====================================
echo   Done! Updated on Desktop.
echo  ====================================
echo.
pause
