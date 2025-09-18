# Starts the Flask server for the Lavanderia OS project
# Usage: Right-click -> Run with PowerShell (or double-click if your PowerShell execution policy allows it)

$ErrorActionPreference = 'Stop'

function Write-Info($msg) {
    Write-Host "[INFO] $msg" -ForegroundColor Cyan
}
function Write-Warn($msg) {
    Write-Host "[WARN] $msg" -ForegroundColor Yellow
}
function Write-Err($msg) {
    Write-Host "[ERROR] $msg" -ForegroundColor Red
}

try {
    # Go to the script directory (project root)
    Set-Location -Path $PSScriptRoot

    Write-Info "Projeto: $PSScriptRoot"

    $venvPython = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"

    # Create venv if missing
    if (-not (Test-Path $venvPython)) {
        Write-Warn ".venv não encontrado. Criando ambiente virtual..."
        python -m venv .venv
        if (-not (Test-Path $venvPython)) {
            throw "Falha ao criar o ambiente virtual (.venv). Verifique se o Python está instalado no PATH."
        }
    }

    # Upgrade pip
    Write-Info "Atualizando pip..."
    & $venvPython -m pip install --upgrade pip | Out-Host

    # Install requirements if requirements.txt exists
    $req = Join-Path $PSScriptRoot "requirements.txt"
    if (Test-Path $req) {
        Write-Info "Instalando dependências de requirements.txt..."
        & $venvPython -m pip install -r $req | Out-Host
    } else {
        Write-Warn "requirements.txt não encontrado. Pulando instalação de dependências."
    }

    # Start the Flask server
    Write-Info "Iniciando o servidor Flask (http://127.0.0.1:5000)..."
    & $venvPython run.py
}
catch {
    Write-Err $_
}
finally {
    # Keep window open if started by double-click
    try {
        if ($Host.Name -notmatch 'Visual Studio Code') {
            Write-Host ""; Read-Host "Pressione Enter para sair"
        }
    } catch {}
}
