# Script Launcher Inteligente v1.6.0
# Orquestra a instalação, atualização e execução do CipherVault

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path "$ScriptDir\..").Path
$VenvPath = "$ProjectRoot\.venv"
$PythonExe = "$VenvPath\Scripts\python.exe"
$PipExe = "$VenvPath\Scripts\pip.exe"
$UpdaterScript = "$ProjectRoot\launcher\updater.py"
$MainScript = "$ProjectRoot\src\main.py"
$ReqFile = "$ProjectRoot\requirements.txt"
$VersionFile = "$ProjectRoot\src\ciphervault\__init__.py"

# Obter versão dinâmica
$LauncherVersion = "Unknown"
if (Test-Path $VersionFile) {
    $Content = Get-Content $VersionFile -Raw
    if ($Content -match '__version__\s*=\s*["'']([^"'']+)["'']') {
        $LauncherVersion = $Matches[1]
    }
}

Write-Host "===== CipherVault Launcher v$LauncherVersion =====" -ForegroundColor Cyan

# 1. Bootstrapping: Verificar e Criar Ambiente Virtual
if (-not (Test-Path $VenvPath)) {
    Write-Host "[INIT] Primeira execucao detetada. A configurar ambiente..." -ForegroundColor Yellow
    Write-Host "       Isto pode demorar alguns minutos."
    
    # Tentar encontrar python no sistema
    try {
        python -m venv $VenvPath
    } catch {
        Write-Error "Python nao encontrado no PATH. Por favor instale Python 3.10+."
        exit 1
    }
    
    if (Test-Path $ReqFile) {
        Write-Host "[INIT] A instalar dependencias..." -ForegroundColor Yellow
        & $PipExe install -r $ReqFile | Out-Null
    }
    Write-Host "[INIT] Ambiente configurado com sucesso." -ForegroundColor Green
}

# Garantir que dependencias do updater estao instaladas (mesmo se requirements.txt for antigo)
& $PipExe install requests packaging | Out-Null

# 2. Verificar Atualizacoes
if (Test-Path $UpdaterScript) {
    Write-Host "[CHECK] A verificar atualizacoes..." -ForegroundColor Gray
    try {
        & $PythonExe $UpdaterScript --check-only
        if ($LASTEXITCODE -eq 1) {
            Write-Host "[UPDATE] Nova versao encontrada! A iniciar atualizacao..." -ForegroundColor Magenta
            & $PythonExe $UpdaterScript --perform-update
            
            # Reinstalar dependencias caso tenham mudado
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[UPDATE] A verificar novas dependencias..."
                & $PipExe install -r $ReqFile | Out-Null
                Write-Host "[UPDATE] Sistema atualizado com sucesso." -ForegroundColor Green
            } else {
                Write-Host "[ERROR] Falha na atualizacao. A continuar com versao local." -ForegroundColor Red
            }
        }
    } catch {
        Write-Host "[WARN] Nao foi possivel verificar atualizacoes (sem internet?)." -ForegroundColor DarkGray
    }
}

# 3. Executar Aplicação
Write-Host "[RUN] A iniciar CipherVault..." -ForegroundColor Cyan
Write-Host ""
& $PythonExe $MainScript
