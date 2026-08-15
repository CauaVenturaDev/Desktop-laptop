# Instalador do PeriShare para Windows 10/11.
# Cria um ambiente virtual em %LOCALAPPDATA%\perishare, instala o pacote a
# partir desta cópia do repositório e gera um atalho de linha de comando.
#
# Uso (PowerShell, na raiz do repositório ou nesta pasta):
#   powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1
#
# Requisito: Python 3.11+ (https://www.python.org/downloads/ — marque
# "Add python.exe to PATH" na instalação).

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$installDir = Join-Path $env:LOCALAPPDATA "perishare"
$venvDir = Join-Path $installDir "venv"

function Find-Python {
    foreach ($candidate in @("py -3", "python")) {
        try {
            $version = & $candidate.Split(" ")[0] $candidate.Split(" ")[1..10] --version 2>$null
            if ($LASTEXITCODE -eq 0 -and $version -match "Python 3\.(1[1-9]|[2-9][0-9])") {
                return $candidate
            }
        } catch {}
    }
    throw "Python 3.11+ nao encontrado. Instale em https://www.python.org/downloads/ e marque 'Add python.exe to PATH'."
}

$python = Find-Python
Write-Host "Usando: $python"
Write-Host "Criando ambiente virtual em $venvDir ..."
& $python.Split(" ")[0] $python.Split(" ")[1..10] -m venv $venvDir

$pip = Join-Path $venvDir "Scripts\pip.exe"
& $pip install --upgrade pip | Out-Null
Write-Host "Instalando o PeriShare (isso baixa pynput, sounddevice e cryptography)..."
& $pip install "$repoRoot"

# Atalho .cmd para usar "perishare" de qualquer terminal.
$cmdPath = Join-Path $installDir "perishare.cmd"
"@echo off`r`n`"$venvDir\Scripts\perishare.exe`" %*" | Set-Content -Path $cmdPath -Encoding ASCII

Write-Host ""
Write-Host "Instalado com sucesso!"
Write-Host "  Executavel : $venvDir\Scripts\perishare.exe"
Write-Host "  Atalho     : $cmdPath"
Write-Host ""
Write-Host "Proximos passos:"
Write-Host "  1. `"$cmdPath`" init          (cria a configuracao)"
Write-Host "  2. Edite %APPDATA%\perishare\config.toml (mesmo 'secret' nas duas maquinas)"
Write-Host "  3. `"$cmdPath`" devices       (lista dispositivos de audio)"
Write-Host "  4. `"$cmdPath`" gui           (abre o painel grafico)"
Write-Host ""
Write-Host "Dica: adicione $installDir ao PATH para digitar apenas 'perishare'."
Write-Host "Firewall: na primeira execucao como servidor, permita o acesso do"
Write-Host "Python em redes privadas quando o Windows perguntar."
