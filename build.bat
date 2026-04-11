@echo off
title WhatsApp Notifier — Build

echo.
echo  ====================================
echo   Building WhatsApp Studio Notifier
echo  ====================================
echo.

python -m PyInstaller SendMessage.spec --noconfirm
if errorlevel 1 (
    echo.
    echo  [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo  Copying to Desktop...
copy /Y "dist\WhatsApp_Notifier.exe" "%USERPROFILE%\Desktop\WhatsApp_Notifier.exe" >nul

echo.
echo  ====================================
echo   Done! Updated on Desktop.
echo  ====================================
echo.
pause
