@echo off
title WhatsApp Notifier — Build

echo.
echo  ====================================
echo   WhatsApp Studio Notifier — Build
echo  ====================================
echo.

:: Install / update dependencies
echo  [1/3] Installing dependencies...
python -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo  [ERROR] pip install failed. Is Python installed and in PATH?
    pause
    exit /b 1
)

:: Make sure logo_icon.ico exists (create from png if missing)
if not exist "logo_icon.ico" (
    echo  [INFO] logo_icon.ico missing — generating from logo_icon.png...
    python -c "from PIL import Image; img=Image.open('logo_icon.png').convert('RGBA'); img.save('logo_icon.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(256,256)]); print('  logo_icon.ico created.')"
    if errorlevel 1 (
        echo  [ERROR] Could not create logo_icon.ico
        pause
        exit /b 1
    )
)

:: Build
echo.
echo  [2/3] Building exe...
python -m PyInstaller SendMessage.spec --noconfirm
if errorlevel 1 (
    echo.
    echo  [ERROR] PyInstaller build failed — see errors above.
    pause
    exit /b 1
)

:: Copy to Desktop
echo.
echo  [3/3] Copying to Desktop...
copy /Y "dist\WhatsApp_Notifier.exe" "%USERPROFILE%\Desktop\WhatsApp_Notifier.exe" >nul
if errorlevel 1 (
    echo  [ERROR] Could not copy to Desktop.
    pause
    exit /b 1
)

echo.
echo  ====================================
echo   Done! Updated on Desktop.
echo  ====================================
echo.
pause
