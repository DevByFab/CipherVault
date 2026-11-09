@echo off
rem CipherVault Launcher Wrapper
rem Garante que o PowerShell corre com permissoes de execucao corretas
title CipherVault v1.9.0

powershell -ExecutionPolicy Bypass -File "%~dp0launcher\launcher.ps1"
if %errorlevel% neq 0 (
    echo.
    echo [ERRO] Ocorreu um erro critico ao iniciar o launcher.
    pause
)
