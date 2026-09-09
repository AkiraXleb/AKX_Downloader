<#
    build.ps1  -  Compila AKX Downloader a .exe con PyInstaller
    ------------------------------------------------------------
    Uso desde PowerShell (en la carpeta del proyecto):
        powershell -ExecutionPolicy Bypass -File build.ps1

    Opciones:
        -Modo onefile   : un solo .exe (~40-60 MB, arranca lento)
        -Modo onedir    : carpeta con .exe y DLLs (arranca rapido) [default]
        -NoLimpio       : no borrar build\ ni dist\ previos
#>

param(
    [ValidateSet('onefile', 'onedir')]
    [string]$Modo = 'onedir',
    [switch]$NoLimpio
)

$ErrorActionPreference = 'Continue'

$Script  = 'akx_downloader.py'
$Icono   = 'icon.ico'
$Nombre  = 'AKX Downloader'

# ---------- Verificaciones ----------
Write-Host ""
Write-Host "=== Build AKX Downloader ($Modo) ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $Script)) {
    Write-Host "No encuentro $Script en la carpeta actual." -ForegroundColor Red
    Write-Host "  Ejecuta este script desde la carpeta del proyecto." -ForegroundColor Yellow
    exit 1
}

$hasIcon = Test-Path $Icono
if (-not $hasIcon) {
    Write-Host "No hay $Icono - se compilara sin icono personalizado." -ForegroundColor Yellow
    Write-Host "  Para agregar uno: py make_icon.py logo.png" -ForegroundColor Yellow
    Write-Host ""
}

# PyInstaller: siempre pip install (es idempotente, si ya esta no hace nada)
Write-Host "Verificando PyInstaller..." -ForegroundColor Yellow
py -3.10 -m pip install --quiet pyinstaller 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "No se pudo instalar PyInstaller." -ForegroundColor Red
    Write-Host "Prueba manualmente: py -3.10 -m pip install pyinstaller" -ForegroundColor Yellow
    exit 1
}

# ---------- Limpiar ----------
if (-not $NoLimpio) {
    foreach ($d in 'build', 'dist') {
        if (Test-Path $d) {
            Write-Host "Borrando $d\ ..." -ForegroundColor DarkGray
            Remove-Item -Recurse -Force $d
        }
    }
    Get-ChildItem -Filter '*.spec' | Remove-Item -Force -ErrorAction SilentlyContinue
}

# ---------- Compilar ----------
$pyiArgs = @(
    '-m', 'PyInstaller',
    "--$Modo",
    '--windowed',
    '--name', $Nombre,
    '--noconfirm',
    '--hidden-import', 'telethon.crypto.aes',
    '--hidden-import', 'pyaes',
    '--hidden-import', 'rsa',
    '--hidden-import', 'pyasn1',
    # El código real vive en akx/ (paquete Python normal, PyInstaller lo
    # bundlea solo por análisis estático de imports). Lo único que necesita
    # --add-data explícito es el frontend, que ya no es un string embebido
    # sino un archivo real que se carga con webview.create_window(url=...).
    '--add-data', 'akx/ui/index.html;akx/ui',
    '--exclude-module', 'webview.platforms.cef',
    '--exclude-module', 'webview.platforms.gtk',
    '--exclude-module', 'webview.platforms.qt',
    '--exclude-module', 'webview.platforms.cocoa',
    '--exclude-module', 'tkinter',
    '--exclude-module', 'matplotlib',
    '--exclude-module', 'numpy',
    '--exclude-module', 'scipy',
    '--exclude-module', 'test'
)
if ($hasIcon) { $pyiArgs += @('--icon', $Icono) }
$pyiArgs += $Script

Write-Host "Compilando... (2-5 min la primera vez)" -ForegroundColor Yellow
Write-Host ""
& py -3.10 @pyiArgs

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Fallo la compilacion (codigo $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

# ---------- Reporte ----------
Write-Host ""
Write-Host "======================================================" -ForegroundColor Green
Write-Host "  Compilacion exitosa" -ForegroundColor Green
Write-Host "======================================================" -ForegroundColor Green
Write-Host ""

if ($Modo -eq 'onefile') {
    $exe = "dist\$Nombre.exe"
    if (Test-Path $exe) {
        $mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
        $tam = "$mb MB"
        Write-Host "  Ejecutable: $exe ($tam)" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  Se puede compartir directamente. Primer arranque es lento" -ForegroundColor White
        Write-Host "  porque descomprime el runtime a temp." -ForegroundColor White
    }
} else {
    $dir = "dist\$Nombre"
    $exe = "$dir\$Nombre.exe"
    if (Test-Path $exe) {
        $total = (Get-ChildItem $dir -Recurse | Measure-Object Length -Sum).Sum
        $mb = [math]::Round($total / 1MB, 1)
        $tam = "$mb MB total"
        Write-Host "  Carpeta: $dir ($tam)" -ForegroundColor Cyan
        Write-Host "  Ejecutable: $exe" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  Para compartir, zippea toda la carpeta:" -ForegroundColor White
        Write-Host "    Compress-Archive -Path '$dir' -DestinationPath 'AKX-Downloader.zip'" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "  Probalo con doble click." -ForegroundColor Yellow
Write-Host ""
