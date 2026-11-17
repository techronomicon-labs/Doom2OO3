param(
    [Parameter(Mandatory)]
    [ValidateSet('DoomII', 'DBP50', 'Gallery', 'Flashlight')]
    [string]$Game,

    [Parameter(Mandatory)]
    [string]$Exe,

    [Parameter(Mandatory)]
    [string]$Doom2,

    [Parameter(Mandatory)]
    [string]$Packages,

    [string]$DBP50,

    [switch]$Relief,

    [switch]$SpriteRelief,

    [switch]$ReliefStock,

    [switch]$EmitterLighting,

    [switch]$DesktopShortcut
)

$ErrorActionPreference = 'Stop'
$engine = (Get-Item -LiteralPath $Exe).FullName
$iwad = (Get-Item -LiteralPath $Doom2).FullName
$root = (Get-Item -LiteralPath $Packages).FullName
$gameFiles = @()
$map = 'MAP01'
$uber = 'true'
$weapon = 'true'
$width = '1280'
$spritePreview = $Game -eq 'DoomII' -and $SpriteRelief -and !$ReliefStock -and !$EmitterLighting
$preview = $Game -eq 'DoomII' -and $Relief -and !$ReliefStock -and !$spritePreview -and !$EmitterLighting

if ($EmitterLighting -and $Game -ne 'DoomII') { throw 'The authored emitter evaluation requires -Game DoomII.' }
if ($ReliefStock -and !$Relief -and !$SpriteRelief) { throw '-ReliefStock requires -Relief or -SpriteRelief.' }
if ($Relief -or $SpriteRelief) {
    if ($Game -notin 'DoomII', 'DBP50') { throw 'Relief requires -Game DoomII or -Game DBP50.' }
    $uber = 'false'
    if ($preview -or $spritePreview) {
        $map = if ($spritePreview) { 'RSP001' } else { 'RPV001' }
        $weapon = 'false'
        $width = '960'
    }
}
if ($EmitterLighting) {
    $uber = 'false'
}

switch ($Game) {
    'DBP50' {
        if (!$DBP50) { throw 'Supply -DBP50 with the DBP50 PWAD path.' }
        $gameFiles += (Get-Item -LiteralPath $DBP50).FullName
    }
    'Gallery' {
        $map = 'SGSHOW'
        $uber = 'false'
        $weapon = 'false'
    }
}
if ($Game -in 'DoomII', 'DBP50') {
    $gameFiles += Join-Path $root "$Game-NormalPBR.pk3"
    $gameFiles += Join-Path $root "$Game-SpritePBR.pk3"
}
if ($Game -eq 'Gallery') {
    $gameFiles += Join-Path $root 'DoomII-Material-Gallery.pk3'
} else {
    $gameFiles += Join-Path $root 'Local-Flashlight.pk3'
}
if ($preview) {
    $gameFiles += Join-Path $root 'DoomII-Relief-Preview.pk3'
}
if ($spritePreview) {
    $gameFiles += Join-Path $root 'DoomII-Sprite-Relief-Preview.pk3'
}
if ($EmitterLighting) {
    $gameFiles += Join-Path $root 'DoomII-Emitter-Lighting.pk3'
}
foreach ($file in $gameFiles) {
    if (!(Test-Path -LiteralPath $file -PathType Leaf)) { throw "Package missing: $file" }
}

$profile = if ($EmitterLighting) { 'DoomII-Emitter-Lighting' } elseif ($spritePreview) { 'DoomII-Sprite-Relief-Preview' } elseif ($preview) { 'DoomII-Relief-Preview' } elseif ($Relief -or $SpriteRelief) { "$Game-Relief" } else { $Game }
$config = Join-Path $root "$profile.ini"
$save = Join-Path $root "$profile-saves"
New-Item -ItemType Directory -Force -Path $save | Out-Null
$argv = @('-iwad', $iwad, '-noautoload', '-noautoexec', '-file') + $gameFiles + @(
    '-config', $config, '-savedir', $save, '-window', '-width', $width, '-height', '720',
    '+vid_rendermode', '4', '+gl_viewmodel_lighting', '2',
    '+gl_spritelight', '2', '+gl_lights', 'true', '+gl_light_sprites', 'true',
    '+gl_light_particles', 'true', '+gl_lightprobe', 'true', '+gl_customshader', 'true',
    '+gl_ubershaders', $uber, '+r_drawplayersprites', $weapon, '+gl_levelmesh', 'false',
    '+gl_light_shadows', '0', '+vk_rayquery', 'false', '+cl_capfps', 'true', '+gl_precache', 'true',
    '+map', $map
)
if ($Game -eq 'Gallery') {
    $argv += @('+bind', 'F1', 'openmenu MaterialGalleryMenu')
}
if ($Game -eq 'DBP50') {
    $argv += @('+bind', 'F1', 'openmenu PBRMaterialMenu')
}
if ($Relief -or $SpriteRelief -or $EmitterLighting) {
    $argv += @('+bind', 'L', 'netevent SDVKFlashlightToggle')
}
if ($EmitterLighting) {
    $argv += @('+gl_emitter_lighting', 'false', '+gl_ssao', '0',
              '+bind', 'B', 'toggle gl_emitter_lighting', '+bind', 'F1', 'openmenu DoomIIEmitterLightingMenu')
}
if ($Relief) {
    $argv += @('+gl_world_relief', 'true', '+gl_world_relief_depth', '5',
              '+gl_world_relief_orientation', '5', '+gl_world_relief_exaggeration', '1.25',
              '+bind', 'R', 'toggle gl_world_relief')
}
if ($SpriteRelief) {
    $argv += @('+gl_sprite_lighting_relief', 'true', '+bind', 'V', 'toggle gl_sprite_lighting_relief')
}
if ($preview -or $spritePreview) {
    $menu = if ($spritePreview) { 'DoomIISpriteReliefMenu' } else { 'DoomIIReliefPreviewMenu' }
    $compare = if ($spritePreview) { 'toggle gl_sprite_lighting_relief' } else { 'toggle gl_world_relief' }
    $fov = if ($spritePreview) { '65' } else { '90' }
    $argv += @('+vid_setsize', $width, '720', '+fov', $fov, '+screenblocks', '12', '+crosshair', '0',
              '+con_notifytime', '0',
              '+bind', 'R', $compare, '+bind', 'MOUSE3', $compare,
              '+bind', 'F1', "openmenu $menu",
              '+bind', 'PGUP', 'nextsecret', '+bind', 'PGDN', 'nextmap',
              '+bind', 'MWHEELUP', 'nextsecret', '+bind', 'MWHEELDOWN', 'nextmap')
}
# All filesystem arguments are resolved Windows paths, where double quotes
# are invalid. Quoting each argument also preserves whitespace in paths.
$arguments = ($argv | ForEach-Object { '"' + $_ + '"' }) -join ' '
$workingDir = Split-Path -Parent $engine
if ($DesktopShortcut) {
    $names = @{
        DoomII = 'Doom II Materials'
        DBP50 = 'DBP50 Materials'
        Gallery = 'Doom II Material Gallery'
        Flashlight = 'Doom II Flashlight'
    }
    $desktop = [Environment]::GetFolderPath('Desktop')
    $gameLabel = if ($Game -eq 'DoomII') { 'Doom II' } else { $Game }
    $name = if ($EmitterLighting) { 'Doom II Emitter Lighting' } elseif ($spritePreview) { 'Doom II Sprite Relief Rooms' } elseif ($preview) { 'Doom II Relief Preview Rooms' } elseif ($Relief -or $SpriteRelief) { "$gameLabel Relief Evaluation" } else { $names[$Game] }
    $path = Join-Path $desktop "ShadeDoomVK - $name (Hardware).lnk"
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $engine
    $link.Arguments = $arguments
    $link.WorkingDirectory = $workingDir
    $link.IconLocation = "$engine,0"
    $link.Save()
    Write-Output $path
} else {
    Start-Process -FilePath $engine -WorkingDirectory $workingDir -ArgumentList $arguments -WindowStyle Normal
}
