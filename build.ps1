# Build script for Windows using PyInstaller
# Run from project root in PowerShell:
#   .\build.ps1  (script can also live in a `build` subfolder)

$ErrorActionPreference = 'Stop'
# Urči adresář skriptu (build/) a potom rodičovský adresář projektu
# Determine script directory and project root.
# If this script lives in a `build` subfolder, the project root is its parent.
# If the script is in the project root, use that as the project root.
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
if ((Split-Path -Leaf $scriptDir) -ieq 'build') {
    $proj = Split-Path -Parent $scriptDir
} else {
    $proj = $scriptDir
}
Set-Location $proj

# Ensure build dir exists
$buildDir = Join-Path $proj 'build'
New-Item -ItemType Directory -Path $buildDir -Force | Out-Null

function Ensure-PythonModule($module, $importName) {
    try {
        python -c "import $importName" > $null 2>&1
    } catch {
        Write-Host "Python module $importName not found. Installing..."
        & python -m pip install --user $module
    }
}

# Ensure PyInstaller and Pillow are available
Ensure-PythonModule PyInstaller PyInstaller
Ensure-PythonModule pillow PIL

# Convert logo.png -> build/logo.ico (if exists)
$logo = Join-Path $proj 'logo.png'
$ico = Join-Path $buildDir 'logo.ico'
if (Test-Path $logo) {
    Write-Host "Converting logo.png -> build\logo.ico"
    $iconScriptRoot = Join-Path $proj 'build_icon.py'
    $iconScriptBuild = Join-Path (Join-Path $proj 'build') 'build_icon.py'
    if (Test-Path $iconScriptRoot) {
        & python $iconScriptRoot
    } elseif (Test-Path $iconScriptBuild) {
        & python $iconScriptBuild
    } else {
        Write-Host "Icon script not found; skipping icon conversion"
    }
    if (-not (Test-Path $ico)) {
        Write-Host "Icon conversion did not produce logo.ico; continuing without explicit icon"
        $iconArg = ""
    } else {
        # správné escapování uvozovek v PowerShellu pro předání cesty s mezerami
        $iconArg = "--icon=`"$ico`""
    }
} else {
    Write-Host "logo.png not found in project root; building without icon"
    $iconArg = ""
}

# Prepare --add-data arguments for PyInstaller (bundle data folders)
$addDataArgs = @()
$audioSrc = Join-Path $proj 'audio'
if (Test-Path $audioSrc) { $addDataArgs += "`"$audioSrc;audio`"" }
$linesSrc = Join-Path $proj 'lines'
if (Test-Path $linesSrc) { $addDataArgs += "`"$linesSrc;lines`"" }
$logoSrc = Join-Path $proj 'logo.png'
if (Test-Path $logoSrc) { $addDataArgs += "`"$logoSrc;.`"" }

# Build a single start.exe (contains main as imported module) into build directory using python -m PyInstaller
Write-Host "Building single start.exe (onefile) with bundled data..."

# výsledný název exe
$outputName = 'mhd-hk-sim'
$pyiArgs = @('--noconfirm','--onefile','--windowed','--distpath',$buildDir,'--name',$outputName)
if ($iconArg -ne "") { $pyiArgs += $iconArg }

foreach ($d in $addDataArgs) { $pyiArgs += ('--add-data'); $pyiArgs += $d }
$pyiArgs += (Join-Path $proj 'start.py')

Write-Host "pyinstaller args: $pyiArgs"
& python -m PyInstaller @pyiArgs

Write-Host "Build finished. Binary is in: $buildDir\$outputName.exe"

# Attempt to sign the built exe using signtool (Local Machine cert by subject name "Petr Vurm")
$exePath = Join-Path $buildDir "$outputName.exe"
if (Test-Path $exePath) {
    # try to find signtool in PATH
    $signtool = Get-Command signtool -ErrorAction SilentlyContinue
    if ($signtool) {
        Write-Host "signtool found: attempting to sign $exePath with Local Machine cert subject 'Petr Vurm'"
        try {
            # /sm = store in local machine; /n = subject name; /fd = file digest algorithm
            & signtool sign /sm /n "Petr Vurm" /fd SHA256 /v $exePath
            Write-Host "Signing attempted (check signtool output above)."
        } catch {
            Write-Host "Signing failed: $_"
        }
    } else {
        Write-Host "signtool not found in PATH. To sign locally, install Windows SDK or use signtool, then run:"
        Write-Host "    signtool sign /sm /n \"Petr Vurm\" /fd SHA256 \"$exePath\""
    }
} else {
    Write-Host "Built exe not found at $exePath; skipping signing."
}
