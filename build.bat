@echo off
title WhatsApp Notifier - Build
setlocal enabledelayedexpansion

echo.
echo  ====================================
echo   WhatsApp Studio Notifier - Build
echo  ====================================
echo.

:: ── Pull latest from git ───────────────────────────────────────────────────
where git >nul 2>&1
if errorlevel 1 (
    echo  [WARN] git not found — skipping auto-update.
) else (
    echo  [1/5] Pulling latest from git...
    git pull --ff-only
    if errorlevel 1 (
        echo.
        echo  [WARN] git pull failed. Continuing with local code.
        echo         If the build is missing recent fixes, run: git pull
        echo.
        timeout /t 3 >nul
    )
)
echo.

:: ── Find Python ────────────────────────────────────────────────────────────
set PYTHON=

python --version >nul 2>&1 && set PYTHON=python
if "%PYTHON%"=="" py --version >nul 2>&1 && set PYTHON=py

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
echo  [2/5] Installing dependencies...
%PYTHON% -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo  [ERROR] pip install failed.
    pause
    exit /b 1
)

:: ── Always rebuild the transparent icon from source PNG ───────────────────
echo  [3/5] Rebuilding transparent icon...
if exist "build_icon.py" (
    %PYTHON% build_icon.py
    if errorlevel 1 (
        echo  [WARN] build_icon.py failed, using existing logo_icon.ico
    )
) else (
    :: Fallback: simple conversion if build_icon.py missing
    %PYTHON% -c "from PIL import Image; img=Image.open('logo_icon.png').convert('RGBA'); img.save('logo_icon.ico', format='ICO', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
)

:: ── Clean previous build artifacts so nothing is stale ─────────────────────
echo  [4/5] Cleaning old build artifacts...
if exist "build" rmdir /S /Q "build"
if exist "dist"  rmdir /S /Q "dist"

:: ── Build ──────────────────────────────────────────────────────────────────
echo  [5/5] Building exe (this can take a minute)...
%PYTHON% -m PyInstaller SendMessage.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo  [ERROR] Build failed — see errors above.
    pause
    exit /b 1
)

:: ── Copy to Desktop ────────────────────────────────────────────────────────
echo.
echo  Copying to Desktop...
copy /Y "dist\WhatsApp_Notifier.exe" "%USERPROFILE%\Desktop\WhatsApp_Notifier.exe" >nul
if errorlevel 1 (
    echo  [WARN] Could not copy to Desktop (file in use?). Close the app and re-run.
) else (
    echo  [OK] Desktop shortcut updated.
)

:: ── Nudge Windows to refresh the icon cache ────────────────────────────────
echo.
echo  Refreshing icon cache...
ie4uinit.exe -show >nul 2>&1

echo.
echo  ====================================
echo   Done! Updated on Desktop.
echo  ====================================
echo.
echo  Tip: If Desktop still shows the old icon, right-click it -^> Delete,
echo       then re-run this script. Or log out / log in once.
echo.
pause
