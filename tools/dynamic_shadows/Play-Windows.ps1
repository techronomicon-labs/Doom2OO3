param(
    [string]$Iwad,
    [switch]$LegacyLighting,
    [switch]$SkipMaterialBuild,
    [switch]$SkipActorShadows
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$exe = Join-Path $root 'runtime\vkdoom.exe'
if (!(Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "Source-matched Windows executable missing: $exe"
}

if (!$Iwad) {
    Add-Type -AssemblyName System.Windows.Forms
    $picker = New-Object System.Windows.Forms.OpenFileDialog
    $picker.Filter = 'Doom-family WAD|*.wad|All files|*.*'
    $picker.Title = 'Select your own Doom II IWAD'
    if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
    $Iwad = $picker.FileName
}
$iwadPath = (Get-Item -LiteralPath $Iwad -ErrorAction Stop).FullName
$files = New-Object 'System.Collections.Generic.List[string]'
$flashlight = Join-Path $root 'Local-Flashlight.pk3'

$stock = @('DoomII-NormalPBR.pk3','DoomII-SpritePBR.pk3')
$wadHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $iwadPath).Hash.ToLowerInvariant()
$materialRoot = Join-Path $root ('local-materials\' + $wadHash)
if (!$SkipMaterialBuild -and !(Test-Path -LiteralPath (Join-Path $materialRoot $stock[0]))) {
    $python = Get-Command py -ErrorAction SilentlyContinue
    $generator = Join-Path $root 'tools\dynamic_shadows\build_pr190_materials.py'
    if ($python -and (Test-Path -LiteralPath $generator)) {
        Write-Host 'Generating the ORIGINAL PR #190 material profiles for this WAD...' -ForegroundColor Cyan
        & $python.Source -3 $generator --doom2 $iwadPath --out $materialRoot
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'Original PR #190 PBR generation was unavailable; source lighting still starts.'
        }
    }
}
foreach ($name in $stock) {
    $item = Join-Path $materialRoot $name
    if (Test-Path -LiteralPath $item -PathType Leaf) { $files.Add($item) }
}
if (Test-Path -LiteralPath $flashlight -PathType Leaf) { $files.Add($flashlight) }

Write-Host 'ShadeDoomVK SHADOW-002 research: light-facing source-alpha occlusion; native visual qualification pending.' -ForegroundColor Yellow
Write-Host "Engine: $exe"
Write-Host "IWAD SHA256: $wadHash"
Write-Host "PBR packs loaded: $(@($files | Where-Object { $_ -like '*PBR.pk3' }).Count) / 2"
if (@($files | Where-Object { $_ -like '*PBR.pk3' }).Count -ne 2) {
    Write-Warning 'Original PR #190 PBR packs are missing: for faithful appearance install Python 3.11+ NumPy/Pillow or copy generated packs.'
}
$argv = @('-iwad', $iwadPath, '-noautoload', '-noautoexec')
if ($files.Count) { $argv += @('-file') + @($files) }
$actor = if ($SkipActorShadows -or $LegacyLighting) { 'false' } else { 'true' }
$world = if ($LegacyLighting) { '0' } else { '1' }
$argv += @(
    '-window', '-width', '1280', '-height', '720',
    '+vid_rendermode', '4',
    '+gl_lights', 'true', '+gl_light_sprites', 'true', '+gl_light_particles', 'true',
    '+gl_spritelight', '2', '+gl_viewmodel_lighting', '2',
    '+gl_lightprobe', 'true', '+gl_customshader', 'true', '+gl_ubershaders', 'false',
    '+gl_levelmesh', 'false', '+gl_light_shadows', $world,
    '+gl_actor_light_shadows', $actor, '+r_actorspriteshadow', '0',
    '+map', 'MAP01'
)
# Running the program is the purpose of this script. Never print-only.
& $exe @argv
exit $LASTEXITCODE
