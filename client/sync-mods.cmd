@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Set this once before sharing. The pack must be publicly readable.
set "PACKWIZ_SYNC_URL=https://YOUR-USERNAME.github.io/YOUR-REPO/pack.toml"

rem Double-click from anywhere (for example Downloads): the pack is installed to
rem %APPDATA%\.minecraft\modpacks\<pack name>, and a copy of this script is put there.
rem To choose the folder instead, put this file alone in an empty folder and run it there.
rem Close Minecraft and the launcher before running. With the official Minecraft
rem Launcher, it installs the pack's NeoForge version and creates a launcher profile
rem named after the game folder. Set PACKWIZ_SYNC_SKIP_LAUNCHER=1 to skip that step.
rem The updater downloads its own portable Java 21; it does not configure game Java.
rem Keep packwiz.json: the installer uses it to track the files it manages.

set "PACKWIZ_SYNC_SCRIPT=%~f0"
rem A module path inherited from PowerShell 7 breaks Windows PowerShell's built-in modules.
set "PSModulePath="
powershell.exe -NoLogo -NoProfile -Command "$ErrorActionPreference = 'Stop'; $lines = @(Get-Content -LiteralPath $env:PACKWIZ_SYNC_SCRIPT); $marker = [Array]::IndexOf($lines, '# POWERSHELL START'); if ($marker -lt 0) { throw 'Script is incomplete.' }; & ([scriptblock]::Create(($lines[($marker + 1)..($lines.Length - 1)] -join [Environment]::NewLine)))"
set "PACKWIZ_SYNC_EXIT=%ERRORLEVEL%"
if not "%PACKWIZ_SYNC_EXIT%"=="0" echo Synchronization failed. See the error above.
echo.
pause
exit /b %PACKWIZ_SYNC_EXIT%

# POWERSHELL START
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Get-Download {
    param([string]$Url, [string]$Destination, [string]$Sha256)
    $uri = [uri]$Url
    if (-not $uri.IsAbsoluteUri -or $uri.Scheme -ne 'https') {
        throw 'Downloads must use absolute HTTPS URLs.'
    }
    $partial = $Destination + '.' + [guid]::NewGuid().ToString('N') + '.partial'
    try {
        Invoke-WebRequest -Uri $Url -UseBasicParsing -OutFile $partial -TimeoutSec 300
        if ((Get-Item -LiteralPath $partial).Length -eq 0) {
            throw "Empty download: $Url"
        }
        if ($Sha256) {
            if ($Sha256 -notmatch '^[a-fA-F0-9]{64}$') { throw 'Invalid expected SHA-256 checksum.' }
            $stream = [IO.File]::OpenRead($partial)
            try { $actual = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($stream)).Replace('-', '') }
            finally { $stream.Dispose() }
            if ($actual -ne $Sha256) {
                throw "Checksum mismatch: $Url"
            }
        }
        Move-Item -LiteralPath $partial -Destination $Destination -Force
    }
    finally {
        if (Test-Path -LiteralPath $partial) {
            Remove-Item -LiteralPath $partial -Force
        }
    }
}

function Test-LauncherRunning {
    return [bool](Get-Process -Name 'MinecraftLauncher' -ErrorAction SilentlyContinue)
}

function Wait-LauncherClosed {
    while (Test-LauncherRunning) {
        Write-Host 'The Minecraft Launcher is open. It would overwrite the profile settings.' -ForegroundColor Yellow
        Write-Host 'Close the launcher completely (also check the system tray), then press Enter.'
        [void](Read-Host)
    }
}

function Install-NeoForge {
    param([string]$Version, [string]$MinecraftDir, [string]$Java, [string]$Cache)
    $versionJson = Join-Path $MinecraftDir "versions\neoforge-$Version\neoforge-$Version.json"
    if (Test-Path -LiteralPath $versionJson -PathType Leaf) {
        Write-Host "NeoForge $Version is already installed."
        return
    }
    Write-Host "Installing NeoForge $Version into the Minecraft Launcher..."
    $base = "https://maven.neoforged.net/releases/net/neoforged/neoforge/$Version/neoforge-$Version-installer.jar"
    $checksum = (Invoke-WebRequest -Uri ($base + '.sha256') -UseBasicParsing -TimeoutSec 60).Content
    if ($checksum -is [byte[]]) { $checksum = [Text.Encoding]::ASCII.GetString($checksum) }
    if ($checksum -notmatch '([a-fA-F0-9]{64})') { throw 'NeoForge did not publish a valid installer checksum.' }
    $installer = Join-Path $Cache "neoforge-$Version-installer.jar"
    Get-Download -Url $base -Destination $installer -Sha256 $Matches[1]
    # The installer writes installer.log to the working directory; keep it in the cache.
    Push-Location -LiteralPath $Cache
    try {
        & $Java -jar $installer --install-client $MinecraftDir
        if ($LASTEXITCODE -ne 0) { throw "NeoForge installer exited with code $LASTEXITCODE." }
    }
    finally {
        Pop-Location
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path -LiteralPath $versionJson -PathType Leaf)) {
        throw "NeoForge $Version did not install correctly."
    }
}

function Set-LauncherProfile {
    param([string]$ProfilesPath, [string]$Key, [string]$Name, [string]$Version, [string]$GameDir)
    $json = [IO.File]::ReadAllText($ProfilesPath)
    $data = $json | ConvertFrom-Json
    if (-not $data.profiles) { throw 'launcher_profiles.json has no profiles section.' }
    $now = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    $launcherProfile = $data.profiles.$Key
    if (-not $launcherProfile) {
        $memory = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
        $heap = if ($memory -ge 16) { '8G' } elseif ($memory -ge 12) { '6G' } else { '4G' }
        $launcherProfile = [pscustomobject]@{
            created = $now
            icon = 'Furnace'
            type = 'custom'
            javaArgs = "-Xmx$heap -XX:+UseG1GC -XX:+UnlockExperimentalVMOptions -XX:G1NewSizePercent=20 -XX:G1ReservePercent=20 -XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M"
        }
        $data.profiles | Add-Member -NotePropertyName $Key -NotePropertyValue $launcherProfile
    }
    # Keep any memory settings the player changed; always correct the version and folder.
    foreach ($field in @{ name = $Name; lastVersionId = $Version; gameDir = $GameDir; lastUsed = $now }.GetEnumerator()) {
        $launcherProfile | Add-Member -NotePropertyName $field.Key -NotePropertyValue $field.Value -Force
    }
    Copy-Item -LiteralPath $ProfilesPath -Destination ($ProfilesPath + '.bak-packwiz') -Force
    $temp = $ProfilesPath + '.packwiz.tmp'
    [IO.File]::WriteAllText($temp, ($data | ConvertTo-Json -Depth 32), (New-Object Text.UTF8Encoding $false))
    Move-Item -LiteralPath $temp -Destination $ProfilesPath -Force
}

function Remove-CacheDirectory {
    param([string]$Path, [string]$CacheRoot)
    $resolvedCache = [IO.Path]::GetFullPath($CacheRoot).TrimEnd('\') + '\'
    $resolvedTarget = [IO.Path]::GetFullPath($Path)
    if (-not $resolvedTarget.StartsWith($resolvedCache, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Refusing cleanup outside the updater cache.'
    }
    if (Test-Path -LiteralPath $resolvedTarget) {
        Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
    }
}

$lock = $null
$result = 1
try {
    $packUrl = $env:PACKWIZ_SYNC_URL
    if ([string]::IsNullOrWhiteSpace($packUrl) -or $packUrl -match 'YOUR-USERNAME|YOUR-REPO') {
        throw 'Edit PACKWIZ_SYNC_URL near the top of this file to point to your hosted pack.toml.'
    }
    $packUri = [uri]$packUrl
    if (-not $packUri.IsAbsoluteUri -or $packUri.Scheme -ne 'https' -or
        -not $packUri.AbsolutePath.EndsWith('/pack.toml', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'PACKWIZ_SYNC_URL must be an absolute HTTPS URL to pack.toml.'
    }

    $architecture = $env:PROCESSOR_ARCHITEW6432
    if (-not $architecture) { $architecture = $env:PROCESSOR_ARCHITECTURE }
    if ($architecture -ne 'AMD64') {
        throw 'This script requires Windows x64 (Intel or AMD).'
    }

    $scriptDir = [IO.Path]::GetDirectoryName($env:PACKWIZ_SYNC_SCRIPT)
    if (((Test-Path -LiteralPath (Join-Path $scriptDir 'pack.toml')) -and
         (Test-Path -LiteralPath (Join-Path $scriptDir 'index.toml'))) -or
        (Test-Path -LiteralPath (Join-Path $scriptDir 'sources\mods.json')) -or
        (Test-Path -LiteralPath (Join-Path $scriptDir '..\sources\mods.json'))) {
        throw 'This looks like the pack source repository. Run the published copy of this script instead.'
    }

    # Fail before downloading Java if the pack URL is missing or returns a web page.
    $packResponse = Invoke-WebRequest -Uri $packUrl -UseBasicParsing -TimeoutSec 60
    $packContent = if ($packResponse.Content -is [byte[]]) {
        [Text.Encoding]::UTF8.GetString($packResponse.Content)
    } else { [string]$packResponse.Content }
    if ($packContent -notmatch '(?m)^\s*pack-format\s*=\s*"packwiz:') {
        throw 'The pack URL did not return a packwiz pack.toml. Check the hosting URL.'
    }
    $neoForgeVersion = if ($packContent -match '(?m)^\s*neoforge\s*=\s*"([^"]*)"') { $Matches[1] }
    $packName = if ($packContent -match '(?m)^\s*name\s*=\s*"([^"]*)"') { $Matches[1] }
    if ($packName -notmatch '^[\w.()+-][\w .()+-]{0,63}$' -or $packName.EndsWith('.')) { $packName = 'Modpack' }

    # An empty folder (apart from this script) or an existing instance is used as the game folder.
    # Run from anywhere else (Downloads, Desktop, ...), the pack goes to .minecraft\modpacks\<pack>.
    $minecraftDir = Join-Path $env:APPDATA '.minecraft'
    $scriptName = [IO.Path]::GetFileName($env:PACKWIZ_SYNC_SCRIPT)
    $otherFiles = @(Get-ChildItem -LiteralPath $scriptDir -Force | Where-Object { $_.Name -ne $scriptName })
    if ((Test-Path -LiteralPath (Join-Path $scriptDir 'packwiz.json') -PathType Leaf) -or $otherFiles.Count -eq 0) {
        $instance = $scriptDir
    } else {
        if (-not (Test-Path -LiteralPath (Join-Path $minecraftDir 'launcher_profiles.json') -PathType Leaf)) {
            throw 'Official Minecraft Launcher not found. Put this script in an empty folder (or your launcher''s instance folder) and run it there.'
        }
        $instance = Join-Path $minecraftDir "modpacks\$packName"
        [void][IO.Directory]::CreateDirectory($instance)
        # Keep a copy beside the pack so updates can also be run from there.
        $instanceScript = Join-Path $instance $scriptName
        if ([IO.Path]::GetFullPath($instanceScript) -ne [IO.Path]::GetFullPath($env:PACKWIZ_SYNC_SCRIPT)) {
            Copy-Item -LiteralPath $env:PACKWIZ_SYNC_SCRIPT -Destination $instanceScript -Force
        }
    }
    Set-Location -LiteralPath $instance

    $cache = Join-Path $instance '.packwiz-sync'
    [void][IO.Directory]::CreateDirectory($cache)
    try {
        $lock = [IO.File]::Open((Join-Path $cache 'sync.lock'), [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    }
    catch {
        throw 'Cannot lock the instance. Close any other sync window and check folder permissions.'
    }

    Write-Host "Instance: $instance"
    Write-Host "Pack:     $packUrl"
    Write-Host ''

    # The launcher profile is named after this folder; each folder gets its own profile.
    $profileName = [IO.Path]::GetFileName($instance.TrimEnd('\'))
    if ($profileName.Length -gt 64) { $profileName = $profileName.Substring(0, 64) }
    if ([string]::IsNullOrWhiteSpace($profileName)) { $profileName = 'Modpack' }
    $pathHash = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash(
        [Text.Encoding]::UTF8.GetBytes($instance.TrimEnd('\').ToLowerInvariant()))).Replace('-', '')
    $profileKey = 'packwiz-' + $pathHash.Substring(0, 16).ToLowerInvariant()

    # Official Minecraft Launcher setup. Other launchers (Prism, CurseForge, ...) skip this.
    $profilesPath = Join-Path $minecraftDir 'launcher_profiles.json'
    $setupLauncher = $env:PACKWIZ_SYNC_SKIP_LAUNCHER -ne '1'
    if ($setupLauncher -and -not (Test-Path -LiteralPath $profilesPath -PathType Leaf)) {
        Write-Host 'Official Minecraft Launcher not found; skipping NeoForge and profile setup.' -ForegroundColor Yellow
        Write-Host 'If you use it, start it once, close it, and run this script again.'
        $setupLauncher = $false
    }
    if ($setupLauncher) {
        if ($neoForgeVersion -notmatch '^\d+\.\d+\.\d+(-beta)?$') {
            throw 'pack.toml does not name a valid NeoForge version.'
        }
        Wait-LauncherClosed
    }

    $javaHomeForSync = Join-Path $cache 'java-21'
    $javaExeForSync = Join-Path $javaHomeForSync 'bin\java.exe'
    if (-not (Test-Path -LiteralPath $javaExeForSync -PathType Leaf)) {
        Write-Host 'Downloading portable Java 21 for the updater (first run)...'
        $api = 'https://api.adoptium.net/v3/assets/latest/21/hotspot?architecture=x64&image_type=jre&os=windows&vendor=eclipse'
        $releases = @(Invoke-RestMethod -Uri $api -TimeoutSec 60)
        $release = $releases | Where-Object {
            $_.binary.architecture -eq 'x64' -and
            $_.binary.os -eq 'windows' -and
            $_.binary.image_type -eq 'jre'
        } | Select-Object -First 1
        if (-not $release) { throw 'No Windows x64 Java 21 runtime was returned by Adoptium.' }
        $package = $release.binary.package
        if ($package.checksum -notmatch '^[a-fA-F0-9]{64}$') {
            throw 'Adoptium did not return a valid Java download checksum.'
        }
        $javaZip = Join-Path $cache 'java-21.zip'
        $staging = Join-Path $cache ('java-extract-' + [guid]::NewGuid().ToString('N'))
        try {
            Get-Download -Url $package.link -Destination $javaZip -Sha256 $package.checksum
            Expand-Archive -LiteralPath $javaZip -DestinationPath $staging
            $javaDirs = @(Get-ChildItem -LiteralPath $staging -Directory | Where-Object {
                Test-Path -LiteralPath (Join-Path $_.FullName 'bin\java.exe') -PathType Leaf
            })
            if ($javaDirs.Count -ne 1) { throw 'Unexpected Java archive layout.' }
            if (Test-Path -LiteralPath $javaHomeForSync) {
                Remove-CacheDirectory -Path $javaHomeForSync -CacheRoot $cache
            }
            $resolvedStaging = [IO.Path]::GetFullPath($staging).TrimEnd('\') + '\'
            $resolvedSource = [IO.Path]::GetFullPath($javaDirs[0].FullName)
            $resolvedDestination = [IO.Path]::GetFullPath($javaHomeForSync)
            $resolvedCache = [IO.Path]::GetFullPath($cache).TrimEnd('\') + '\'
            if (-not $resolvedSource.StartsWith($resolvedStaging, [StringComparison]::OrdinalIgnoreCase) -or
                -not $resolvedDestination.StartsWith($resolvedCache, [StringComparison]::OrdinalIgnoreCase)) {
                throw 'Unexpected Java installation paths.'
            }
            Move-Item -LiteralPath $resolvedSource -Destination $resolvedDestination
        }
        finally {
            Remove-CacheDirectory -Path $staging -CacheRoot $cache
            if (Test-Path -LiteralPath $javaZip) { Remove-Item -LiteralPath $javaZip -Force }
        }
    }

    $bootstrap = Join-Path $cache 'packwiz-installer-bootstrap.jar'
    if (-not (Test-Path -LiteralPath $bootstrap -PathType Leaf)) {
        Write-Host 'Downloading packwiz installer bootstrap...'
        Get-Download -Url 'https://github.com/packwiz/packwiz-installer-bootstrap/releases/download/v0.0.3/packwiz-installer-bootstrap.jar' -Destination $bootstrap
    }

    if ($setupLauncher) {
        Install-NeoForge -Version $neoForgeVersion -MinecraftDir $minecraftDir -Java $javaExeForSync -Cache $cache
        # The launcher may have been reopened while NeoForge installed.
        Wait-LauncherClosed
        Set-LauncherProfile -ProfilesPath $profilesPath -Key $profileKey `
            -Name $profileName -Version "neoforge-$neoForgeVersion" -GameDir $instance
        Write-Host "Minecraft Launcher profile '$profileName' points to this folder."
    }

    Write-Host 'Synchronizing mods...'
    # Keep the working directory at the game instance. Never use .packwiz-sync here.
    & $javaExeForSync -jar $bootstrap -g -s client --pack-folder $instance $packUrl
    $result = $LASTEXITCODE
    if ($result -ne 0) { throw "packwiz-installer exited with code $result." }
    Write-Host ''
    if ($setupLauncher) {
        Write-Host "Synchronization complete. Open the Minecraft Launcher, pick '$profileName' and press Play."
    } else {
        Write-Host 'Synchronization complete. You can start Minecraft.'
    }
}
catch {
    Write-Host ''
    Write-Host $_.Exception.Message -ForegroundColor Red
    if ($result -eq 0) { $result = 1 }
}
finally {
    if ($lock) { $lock.Dispose() }
}
exit $result
