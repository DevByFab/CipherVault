@echo off
rem CipherVault GUI Launcher Wrapper
rem Bootstraps the venv, checks for updates, then opens the GUI.
title CipherVault GUI
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher\launcher_gui.ps1"
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to start the GUI launcher.
    pause
)
