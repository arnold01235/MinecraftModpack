@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Set this once before sharing. The pack must be publicly readable.
set "PACKWIZ_SYNC_URL=https://YOUR-USERNAME.github.io/YOUR-REPO/pack.toml"

rem The pack is an add-on for a CurseForge modpack (named in pack.toml's description).
rem Players install that modpack in the CurseForge app first, then double-click this from
rem anywhere (for example Downloads) and pick the profile; the pack's extra mods and config
rem changes are added to it. A copy of this script is put in the profile; run that copy to update.
rem After CurseForge updates the modpack, run it again to restore the pack's changes.
rem Close Minecraft before running.
rem The updater downloads its own portable Java 21; it does not configure game Java.
rem Keep packwiz.json: the installer uses it to track the files it manages.
rem PACKWIZ_SYNC_PLAIN=1 turns off the animation; PACKWIZ_SYNC_NO_PAUSE=1 skips the final key press.

set "PACKWIZ_SYNC_SCRIPT=%~f0"
rem A module path inherited from PowerShell 7 breaks Windows PowerShell's built-in modules.
set "PSModulePath="
powershell.exe -NoLogo -NoProfile -Command "$ErrorActionPreference = 'Stop'; $lines = @(Get-Content -LiteralPath $env:PACKWIZ_SYNC_SCRIPT -Encoding UTF8); $marker = [Array]::IndexOf($lines, '# POWERSHELL START'); if ($marker -lt 0) { throw 'Script is incomplete.' }; & ([scriptblock]::Create(($lines[($marker + 1)..($lines.Length - 1)] -join [Environment]::NewLine)))"
set "PACKWIZ_SYNC_EXIT=%ERRORLEVEL%"
rem The updater waits for a key itself and exits with 0 (done) or 2 (failed, already shown).
rem Anything else means PowerShell could not run it, so keep that error on screen.
if not "%PACKWIZ_SYNC_EXIT%"=="0" if not "%PACKWIZ_SYNC_EXIT%"=="2" (
    echo Synchronization failed. See the error above.
    pause
)
exit /b %PACKWIZ_SYNC_EXIT%

# POWERSHELL START
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$E = [char]27
$script:Ui = $null
$script:Entries = New-Object Collections.Generic.List[object]
$script:Status = $null
$script:RunLog = $null

# --- Screen ------------------------------------------------------------------
# With a capable console the top shows the "aurora fjord" scene from ascii.rest
# (MIT, pre-rendered by client/visuals/render-frames.mjs) and the bottom shows a
# boot-log style panel. Otherwise the same lines are printed as plain text.

$script:Kinds = @{
    OK   = @{ Label = '  OK  '; Rgb = '120;220;140'; Color = 'Green' }
    INFO = @{ Label = ' INFO '; Rgb = '127;153;198'; Color = 'Cyan' }
    WARN = @{ Label = ' WARN '; Rgb = '255;197;110'; Color = 'Yellow' }
    FAIL = @{ Label = 'FAILED'; Rgb = '255;74;61'; Color = 'Red' }
}
$script:Spinner = @('*     ', '**    ', '***   ', ' ***  ', '  *** ', '   ***', '    **', '     *',
    '    **', '   ***', '  *** ', ' ***  ', '***   ', '**    ')
$script:Eighths = ' ' + [string][char]0x258F + [char]0x258E + [char]0x258D + [char]0x258C + [char]0x258B + [char]0x258A + [char]0x2589
$script:Full = [string][char]0x2588
$script:Shade = [string][char]0x2591
$script:Ground = '7;11;22'
$script:Ink = '217;228;241'
$script:Dim = '110;128;160'

function Enable-VirtualTerminal {
    Add-Type -Namespace PackwizSync -Name NativeConsole -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern IntPtr GetStdHandle(int handle);
[DllImport("kernel32.dll")] public static extern bool GetConsoleMode(IntPtr handle, out uint mode);
[DllImport("kernel32.dll")] public static extern bool SetConsoleMode(IntPtr handle, uint mode);
'@
    $handle = [PackwizSync.NativeConsole]::GetStdHandle(-11)
    [uint32]$mode = 0
    if (-not [PackwizSync.NativeConsole]::GetConsoleMode($handle, [ref]$mode)) { return $false }
    # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    return [PackwizSync.NativeConsole]::SetConsoleMode($handle, ($mode -bor 4))
}

function Start-Ui {
    param([string]$FramesPath, [string]$Title)
    if ($env:PACKWIZ_SYNC_PLAIN -eq '1' -or [Console]::IsOutputRedirected) { return }
    if (-not (Test-Path -LiteralPath $FramesPath -PathType Leaf)) { return }
    try {
        if ([Console]::WindowWidth -lt 120 -or [Console]::WindowHeight -lt 30) {
            # Classic console windows can be resized; Windows Terminal ignores this.
            try {
                if ([Console]::BufferWidth -lt 120) { [Console]::BufferWidth = 120 }
                if ([Console]::BufferHeight -lt 30) { [Console]::BufferHeight = 30 }
                [Console]::SetWindowSize(120, 30)
            } catch { }
        }
        if ([Console]::WindowWidth -lt 120 -or [Console]::WindowHeight -lt 26) { return }
        if (-not (Enable-VirtualTerminal)) { return }
        $file = [IO.File]::OpenRead($FramesPath)
        try {
            $gzip = New-Object IO.Compression.GZipStream($file, [IO.Compression.CompressionMode]::Decompress)
            $text = (New-Object IO.StreamReader($gzip, [Text.Encoding]::UTF8)).ReadToEnd()
        } finally { $file.Dispose() }
        $newline = $text.IndexOf("`n")
        $header = $text.Substring(0, $newline).Split(' ')
        if ($header[0] -ne 'ASCIIFRAMES1' -or [int]$header[1] -gt 120 -or
            [Console]::WindowHeight -lt [int]$header[2] + 4) { return }
        $frames = $text.Substring($newline + 1).Split([char]12)
        [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false
        $script:Ui = @{
            Frames = $frames; Rows = [int]$header[2]; Fps = [int]$header[3]; PingPong = $header -contains 'pingpong'
            Clock = [Diagnostics.Stopwatch]::StartNew(); Shown = -1; Tick = -1; Title = $Title
        }
        [Console]::Out.Write("$E[?1049h$E[?25l$E[48;2;$($script:Ground)m$E[2J")
        Update-Ui -Force
    }
    catch {
        $script:Ui = $null
    }
}

function Stop-Ui {
    if (-not $script:Ui) { return }
    $script:Ui = $null
    [Console]::Out.Write("$E[0m$E[?25h$E[?1049l")
    # Leave the whole log on the normal screen.
    foreach ($entry in $script:Entries) { Write-PlainEntry $entry }
}

function Format-Fit {
    param([string]$Text, [int]$Width)
    if ($Text.Length -gt $Width) { return $Text.Substring(0, $Width - 1) + [char]0x2026 }
    return $Text.PadRight($Width)
}

function Format-Bar {
    param([double]$Fraction, [int]$Width)
    $Fraction = [Math]::Max(0, [Math]::Min(1, $Fraction))
    $eighths = [int][Math]::Floor($Fraction * $Width * 8)
    $whole = [int][Math]::Floor($eighths / 8)
    $bar = $script:Full * $whole
    if ($whole -lt $Width) {
        $part = $eighths % 8
        $bar += $(if ($part) { $script:Eighths[$part] } else { $script:Shade })
        $bar += $script:Shade * ($Width - $whole - 1)
    }
    return $bar
}

function Format-Panel {
    param([int]$Tick)
    $ui = $script:Ui
    $height = [Math]::Min([Console]::WindowHeight, 80)
    $top = $ui.Rows + 1
    $logRows = $height - $top - 1
    $base = "$E[48;2;$($script:Ground)m"
    $out = New-Object Text.StringBuilder
    [void]$out.Append("$E[$top;1H$base$E[38;2;$($script:Dim)m" + (Format-Fit (' ' + $ui.Title) 120))
    $first = [Math]::Max(0, $script:Entries.Count - $logRows)
    for ($i = 0; $i -lt $logRows; $i++) {
        [void]$out.Append("$E[$($top + 1 + $i);1H$base")
        $index = $first + $i
        if ($index -lt $script:Entries.Count) {
            $entry = $script:Entries[$index]
            $kind = $script:Kinds[$entry.Kind]
            [void]$out.Append("$E[38;2;$($script:Ink)m[$E[1;38;2;$($kind.Rgb)m$($kind.Label)$E[22;38;2;$($script:Ink)m] " +
                (Format-Fit $entry.Text 111))
        } else {
            [void]$out.Append(' ' * 120)
        }
    }
    [void]$out.Append("$E[$height;1H$base")
    $status = $script:Status
    if ($status) {
        $spin = $script:Spinner[$Tick % $script:Spinner.Count]
        $line = "$E[38;2;$($script:Ink)m[$E[1;38;2;255;74;61m$spin$E[22;38;2;$($script:Ink)m] "
        $width = 111
        if ($status.Total -gt 0) {
            $count = if ($status.Bytes) {
                '{0,6:N1} / {1:N1} MB' -f ($status.Done / 1MB), ($status.Total / 1MB)
            } else { '{0,4} / {1}' -f $status.Done, $status.Total }
            $label = Format-Fit $status.Text 34
            $bar = Format-Bar ($status.Done / $status.Total) 30
            $detail = Format-Fit ('  ' + $count + '  ' + $status.Detail) ($width - 34 - 31)
            $line += "$label $E[38;2;255;197;110m$bar$E[38;2;$($script:Dim)m$detail"
        } else {
            $line += (Format-Fit $status.Text 40) + "$E[38;2;$($script:Dim)m" + (Format-Fit ('  ' + $status.Detail) ($width - 40))
        }
        [void]$out.Append($line)
    } else {
        [void]$out.Append(' ' * 120)
    }
    return $out.ToString()
}

function Update-Ui {
    param([switch]$Force)
    $ui = $script:Ui
    if (-not $ui) { return }
    $seconds = $ui.Clock.Elapsed.TotalSeconds
    $count = $ui.Frames.Count
    if ($ui.PingPong -and $count -gt 2) {
        # Forward then backward, so a scene that never repeats has no visible seam.
        $index = [int][Math]::Floor($seconds * $ui.Fps) % (2 * $count - 2)
        if ($index -ge $count) { $index = 2 * $count - 2 - $index }
    } else {
        $index = [int][Math]::Floor($seconds * $ui.Fps) % $count
    }
    $tick = [int][Math]::Floor($seconds * 10)
    if (-not $Force -and $index -eq $ui.Shown -and $tick -eq $ui.Tick) { return }
    $out = ''
    if ($Force -or $index -ne $ui.Shown) { $out = $ui.Frames[$index]; $ui.Shown = $index }
    $ui.Tick = $tick
    [Console]::Out.Write($out + (Format-Panel $tick))
}

function Write-PlainEntry {
    param($Entry)
    $kind = $script:Kinds[$Entry.Kind]
    Write-Host '[' -NoNewline
    Write-Host $kind.Label -NoNewline -ForegroundColor $kind.Color
    Write-Host "] $($Entry.Text)"
}

function Write-Log {
    param([ValidateSet('OK', 'INFO', 'WARN', 'FAIL')][string]$Kind, [string]$Text)
    $entry = [pscustomobject]@{ Kind = $Kind; Text = $Text }
    $script:Entries.Add($entry)
    if ($script:RunLog) {
        try { [IO.File]::AppendAllText($script:RunLog, ('[{0}] {1}{2}' -f $script:Kinds[$Kind].Label, $Text, [Environment]::NewLine)) } catch { }
    }
    if ($script:Ui) { Update-Ui -Force } else { Write-PlainEntry $entry }
}

function Set-Status {
    param([string]$Text, [string]$Detail = '', [double]$Done = 0, [double]$Total = 0, [switch]$Bytes)
    $previous = $script:Status
    $script:Status = if ($Text) {
        [pscustomobject]@{ Text = $Text; Detail = $Detail; Done = $Done; Total = $Total; Bytes = [bool]$Bytes }
    } else { $null }
    if ($script:Ui) {
        Update-Ui
    } elseif ($Text -and (-not $previous -or $previous.Text -ne $Text)) {
        Write-Host "         $Text..." -ForegroundColor DarkGray
    }
}

function Wait-Ui {
    param([int]$Milliseconds)
    $until = [DateTime]::UtcNow.AddMilliseconds($Milliseconds)
    do {
        Update-Ui
        Start-Sleep -Milliseconds $(if ($script:Ui) { 25 } else { 250 })
    } while ([DateTime]::UtcNow -lt $until)
}

# --- Work ----------------------------------------------------------------------

function Get-Download {
    param([string]$Url, [string]$Destination, [string]$Sha256, [string]$Label)
    $uri = [uri]$Url
    if (-not $uri.IsAbsoluteUri -or $uri.Scheme -ne 'https') {
        throw 'Downloads must use absolute HTTPS URLs.'
    }
    if ($Sha256 -and $Sha256 -notmatch '^[a-fA-F0-9]{64}$') { throw 'Invalid expected SHA-256 checksum.' }
    $partial = $Destination + '.' + [guid]::NewGuid().ToString('N') + '.partial'
    try {
        $request = [Net.HttpWebRequest]::Create($uri)
        $request.UserAgent = 'MinecraftModded-sync/1.0'
        $request.Timeout = 60000
        $request.ReadWriteTimeout = 120000
        $response = $request.GetResponse()
        $hash = [Security.Cryptography.SHA256]::Create()
        $done = 0
        try {
            if ($response.ResponseUri.Scheme -ne 'https') { throw 'A download was redirected away from HTTPS.' }
            $total = $response.ContentLength
            $source = $response.GetResponseStream()
            $output = [IO.File]::Create($partial)
            try {
                $buffer = New-Object byte[] 65536
                while (($read = $source.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $output.Write($buffer, 0, $read)
                    [void]$hash.TransformBlock($buffer, 0, $read, $null, 0)
                    $done += $read
                    if ($Label) { Set-Status $Label -Done $done -Total $total -Bytes }
                }
                [void]$hash.TransformFinalBlock($buffer, 0, 0)
            }
            finally {
                $output.Dispose()
                $source.Dispose()
            }
        }
        finally {
            $response.Dispose()
        }
        if ($done -eq 0) { throw "Empty download: $Url" }
        if ($Sha256 -and [BitConverter]::ToString($hash.Hash).Replace('-', '') -ne $Sha256) {
            throw "Checksum mismatch: $Url"
        }
        Move-Item -LiteralPath $partial -Destination $Destination -Force
    }
    finally {
        if (Test-Path -LiteralPath $partial) {
            Remove-Item -LiteralPath $partial -Force
        }
    }
}

function Get-Text {
    param([string]$Url)
    $client = New-Object Net.WebClient
    $client.Headers['User-Agent'] = 'MinecraftModded-sync/1.0'
    $client.Encoding = [Text.Encoding]::UTF8
    try { return $client.DownloadString($Url) } finally { $client.Dispose() }
}

function Format-Argument {
    param([string]$Value)
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"'
}

# Runs a program while the screen keeps animating; every output line goes to $OnLine.
function Invoke-Tool {
    param([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory, [scriptblock]$OnLine)
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $FilePath
    $info.Arguments = ($Arguments | ForEach-Object { Format-Argument $_ }) -join ' '
    $info.WorkingDirectory = $WorkingDirectory
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($info)
    $readers = @($process.StandardOutput, $process.StandardError)
    $pending = @($readers[0].ReadLineAsync(), $readers[1].ReadLineAsync())
    $tail = New-Object Collections.Generic.List[string]
    while ($pending[0] -or $pending[1]) {
        $idle = $true
        for ($i = 0; $i -lt 2; $i++) {
            if ($pending[$i] -and $pending[$i].IsCompleted) {
                $line = $pending[$i].Result
                if ($null -eq $line) {
                    $pending[$i] = $null
                } else {
                    $idle = $false
                    $tail.Add($line)
                    if ($tail.Count -gt 40) { $tail.RemoveAt(0) }
                    & $OnLine $line
                    $pending[$i] = $readers[$i].ReadLineAsync()
                }
            }
        }
        if ($idle) { Wait-Ui 20 }
    }
    $process.WaitForExit()
    return [pscustomobject]@{ ExitCode = $process.ExitCode; Tail = $tail }
}

function Write-ToolFailure {
    param($Run, [string]$Message)
    foreach ($line in ($Run.Tail | Where-Object { $_ -match '\S' -and $_ -notmatch '^\s+at ' } | Select-Object -Last 6)) {
        Write-Log FAIL $line.Trim()
    }
    throw $Message
}

# --- CurseForge ------------------------------------------------------------------
# The pack is an add-on: the player installs the base modpack (Craftoria) in the CurseForge app,
# which keeps managing it, and this script adds the pack's extra mods and config changes to that
# profile. A CurseForge profile is a folder with minecraftinstance.json.

function Read-CurseForgeProfile {
    param([string]$Folder, [int]$ModpackId = 0)
    $path = Join-Path $Folder 'minecraftinstance.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    $text = [IO.File]::ReadAllText($path)
    # Skip a full parse of profiles that cannot be from the base modpack (the files are megabytes).
    if ($ModpackId -and $text -notmatch ('"addonID"\s*:\s*' + $ModpackId + '\b')) { return $null }
    # ConvertFrom-Json in Windows PowerShell rejects files this large; this parser takes a limit.
    Add-Type -AssemblyName System.Web.Extensions
    $parser = New-Object Web.Script.Serialization.JavaScriptSerializer
    $parser.MaxJsonLength = [int]::MaxValue
    $parser.RecursionLimit = 256
    try { $data = $parser.DeserializeObject($text) } catch { return $null }
    $modpack = $data['installedModpack']
    $file = if ($modpack) { $modpack['installedFile'] }
    $name = if ($data['name']) { [string]$data['name'] } else { [IO.Path]::GetFileName($Folder) }
    return [pscustomobject]@{
        Folder = $Folder
        Name = $name
        Minecraft = [string]$data['gameVersion']
        Loader = if ($data['baseModLoader']) { [string]$data['baseModLoader']['name'] } else { '' }
        ModpackId = if ($modpack) { [int64]$modpack['addonID'] } else { 0 }
        ModpackFileId = if ($file) { [int64]$file['id'] } else { 0 }
        ModpackFile = if ($file) { [string]$file['fileName'] } else { '' }
        Synced = Test-Path -LiteralPath (Join-Path $Folder 'packwiz.json') -PathType Leaf
    }
}

function Get-CurseForgeProfiles {
    param([int64]$ModpackId, [string]$Minecraft, [int]$Limit)
    $root = Join-Path $env:USERPROFILE 'curseforge\minecraft\Instances'
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { return @() }
    # Newest first, so recently installed profiles fit in the menu.
    return @(Get-ChildItem -LiteralPath $root -Directory | Where-Object {
            Test-Path -LiteralPath (Join-Path $_.FullName 'minecraftinstance.json') -PathType Leaf
        } | Sort-Object { (Get-Item -LiteralPath (Join-Path $_.FullName 'minecraftinstance.json')).LastWriteTime } -Descending |
        ForEach-Object { Read-CurseForgeProfile $_.FullName -ModpackId $ModpackId } |
        Where-Object { $_ -and $_.ModpackId -eq $ModpackId -and $_.Minecraft -eq $Minecraft } |
        Select-Object -First $Limit)
}

function Select-Target {
    param([object[]]$Targets, [string]$PackName)
    if ($Targets.Count -eq 1 -or [Console]::IsInputRedirected) { return $Targets[0] }
    Write-Host ''
    Write-Host "  Which CurseForge profile should get $PackName?" -ForegroundColor White
    for ($i = 0; $i -lt $Targets.Count; $i++) {
        Write-Host ('   {0})  {1}' -f ($i + 1), $Targets[$i].Label)
        Write-Host ('        {0}' -f $Targets[$i].Note) -ForegroundColor DarkGray
    }
    Write-Host ''
    Write-Host "  Press 1-$($Targets.Count), or Esc to cancel." -ForegroundColor DarkGray
    while ($true) {
        $key = [Console]::ReadKey($true)
        if ($key.Key -eq 'Escape') { return $null }
        $number = 0
        if ([int]::TryParse([string]$key.KeyChar, [ref]$number) -and $number -ge 1 -and $number -le $Targets.Count) {
            Write-Host ''
            return $Targets[$number - 1]
        }
    }
}

function Assert-CurseForgeProfile {
    # Returns a warning to show once the log is visible, or $null.
    param([object]$Instance, [string]$Minecraft, [object]$Base)
    if ($Instance.ModpackId -ne $Base.ProjectId) {
        throw ("The CurseForge profile '$($Instance.Name)' was not installed from $($Base.Label). In the CurseForge app, " +
            "install $($Base.Label) (Browse modpacks), then run this again.")
    }
    if ($Instance.Minecraft -ne $Minecraft) {
        throw "The CurseForge profile '$($Instance.Name)' is for Minecraft $($Instance.Minecraft), not $Minecraft."
    }
    # CurseForge file IDs increase with every upload, so a lower ID is an older release.
    if ($Instance.ModpackFileId -lt $Base.FileId) {
        throw ("The CurseForge profile '$($Instance.Name)' has $($Instance.ModpackFile), but this pack needs $($Base.Label). " +
            "In CurseForge, update the profile (its Update button), then run this again.")
    }
    if ($Instance.ModpackFileId -gt $Base.FileId) {
        return ("'$($Instance.Name)' has $($Instance.ModpackFile), newer than the $($Base.Label) this pack was made for. " +
            'It usually still works; tell the pack maintainer if something breaks.')
    }
    return $null
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

function Wait-Close {
    param([string]$Message)
    if ($env:PACKWIZ_SYNC_NO_PAUSE -eq '1') { return }
    try {
        if ([Console]::IsInputRedirected) { return }
        Write-Log INFO $Message
        while (-not [Console]::KeyAvailable) { Wait-Ui 100 }
        [void][Console]::ReadKey($true)
    }
    catch { }
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
        (Test-Path -LiteralPath (Join-Path $scriptDir 'sources\pack.json')) -or
        (Test-Path -LiteralPath (Join-Path $scriptDir '..\sources\pack.json'))) {
        throw 'This looks like the pack source repository. Run the published copy of this script instead.'
    }

    # Fail before downloading Java if the pack URL is missing or returns a web page.
    Write-Host 'Reading the modpack...' -ForegroundColor DarkGray
    $packContent = Get-Text $packUrl
    if ($packContent -notmatch '(?m)^\s*pack-format\s*=\s*"packwiz:') {
        throw 'The pack URL did not return a packwiz pack.toml. Check the hosting URL.'
    }
    $neoForgeVersion = if ($packContent -match '(?m)^\s*neoforge\s*=\s*"([^"]*)"') { $Matches[1] }
    $minecraftVersion = if ($packContent -match '(?m)^\s*minecraft\s*=\s*"([^"]*)"') { $Matches[1] }
    $packVersion = if ($packContent -match '(?m)^\s*version\s*=\s*"([^"]*)"') { $Matches[1] }
    $packName = if ($packContent -match '(?m)^\s*name\s*=\s*"([^"]*)"') { $Matches[1] }
    if ($packName -notmatch '^[\w.()+-][\w .()+-]{0,63}$' -or $packName.EndsWith('.')) { $packName = 'Modpack' }

    $baseMatch = [regex]::Match($packContent, '(?m)^\s*description\s*=\s*"Add-on for (.+?) \(CurseForge modpack (\d+), file (\d+)\)')
    if (-not $baseMatch.Success) { throw 'pack.toml does not name the CurseForge modpack it builds on.' }
    $base = [pscustomobject]@{ Label = $baseMatch.Groups[1].Value; ProjectId = [int64]$baseMatch.Groups[2].Value
        FileId = [int64]$baseMatch.Groups[3].Value }
    $baseName = $base.Label -replace '\s+\S+$', ''

    # Run inside a CurseForge profile, the script uses that profile. Run from anywhere else
    # (Downloads, Desktop, ...), the player picks one of their profiles of the base modpack.
    $scriptName = [IO.Path]::GetFileName($env:PACKWIZ_SYNC_SCRIPT)
    $curseForge = Read-CurseForgeProfile $scriptDir
    if (-not $curseForge) {
        $targets = @(foreach ($found in (Get-CurseForgeProfiles -ModpackId $base.ProjectId -Minecraft $minecraftVersion -Limit 9)) {
            $update = if ($found.Synced) { ' (update)' } else { '' }
            [pscustomobject]@{ Profile = $found; Label = "CurseForge profile '$($found.Name)'$update"
                Note = "$($found.ModpackFile)  -  $($found.Folder)" }
        })
        if ($targets.Count -eq 0) {
            throw ("No CurseForge profile with $baseName was found. In the CurseForge app, install the modpack " +
                "$($base.Label) (Browse modpacks), then run this again. If you moved the CurseForge folder, put this " +
                'script in the profile folder (the profile''s menu, Open Folder) and run it there.')
        }
        $target = Select-Target -Targets $targets -PackName $packName
        if (-not $target) {
            Write-Host 'Cancelled. Nothing was changed.'
            exit 0
        }
        $curseForge = $target.Profile
        # Keep a copy in the profile so updates can also be run from there.
        $instanceScript = Join-Path $curseForge.Folder $scriptName
        if ([IO.Path]::GetFullPath($instanceScript) -ne [IO.Path]::GetFullPath($env:PACKWIZ_SYNC_SCRIPT)) {
            Copy-Item -LiteralPath $env:PACKWIZ_SYNC_SCRIPT -Destination $instanceScript -Force
        }
    }
    $baseWarning = Assert-CurseForgeProfile $curseForge -Minecraft $minecraftVersion -Base $base
    $instance = $curseForge.Folder
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
    $script:RunLog = Join-Path $instance 'last-run.log'
    [IO.File]::WriteAllText($script:RunLog, "$(Get-Date -Format s)  $packUrl$([Environment]::NewLine)")

    # The animation is optional: without it (or with a small window) the log is plain text.
    # Windows Terminal's fonts have Braille, which draws the scene sharp and unscaled; the
    # classic console's fonts do not, so it gets the softer half-block version. It is
    # fetched each run so new art reaches everyone; a cached copy covers network errors.
    $style = if ($env:WT_SESSION) { 'scene' } else { 'scene-blocks' }
    Get-ChildItem -LiteralPath $cache -Filter 'snow-train*' | Remove-Item -Force
    $frames = Join-Path $cache "$style.frames.gz"
    if ($env:PACKWIZ_SYNC_PLAIN -ne '1') {
        try {
            Get-Download -Url ($packUrl -replace '/pack\.toml$', "/installer/$style.frames.gz") -Destination $frames
        } catch { }
    }
    Start-Ui -FramesPath $frames -Title ("$packName $packVersion  " + [char]0x00B7 + "  Minecraft $minecraftVersion  " +
        [char]0x00B7 + "  NeoForge $neoForgeVersion")

    Write-Log INFO "game folder $instance"
    Write-Log OK "read pack $packName $packVersion from $($packUri.Host)"

    if ($baseWarning) { Write-Log WARN $baseWarning }

    $javaHomeForSync = Join-Path $cache 'java-21'
    $javaExeForSync = Join-Path $javaHomeForSync 'bin\java.exe'
    if (-not (Test-Path -LiteralPath $javaExeForSync -PathType Leaf)) {
        Set-Status 'finding portable Java 21'
        $api = 'https://api.adoptium.net/v3/assets/latest/21/hotspot?architecture=x64&image_type=jre&os=windows&vendor=eclipse'
        # Assigning first unrolls the JSON array (Windows PowerShell returns it as one object).
        $releases = (Get-Text $api) | ConvertFrom-Json
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
            Get-Download -Url $package.link -Destination $javaZip -Sha256 $package.checksum -Label 'downloading portable Java 21'
            Set-Status 'unpacking portable Java 21'
            Update-Ui -Force
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
        Set-Status ''
        Write-Log OK "portable Java 21 ready ($($release.version.semver))"
    } else {
        Write-Log OK 'portable Java 21 ready'
    }

    $bootstrap = Join-Path $cache 'packwiz-installer-bootstrap.jar'
    if (-not (Test-Path -LiteralPath $bootstrap -PathType Leaf)) {
        Get-Download -Url 'https://github.com/packwiz/packwiz-installer-bootstrap/releases/download/v0.0.3/packwiz-installer-bootstrap.jar' -Destination $bootstrap -Label 'downloading packwiz installer'
        Set-Status ''
    }
    Write-Log OK 'packwiz installer ready'

    # Keep the working directory at the game instance. Never use .packwiz-sync here.
    $script:ModsDone = 0
    Set-Status 'checking mods'
    $run = Invoke-Tool -FilePath $javaExeForSync -WorkingDirectory $instance -Arguments @(
        '-jar', $bootstrap, '-g', '-s', 'client', '--pack-folder', $instance, $packUrl) -OnLine {
        param($line)
        if ($line -match 'already up to date') {
            Set-Status 'checking mods' -Detail $line.Trim()
        } elseif ($line -match '^\((\d+)/(\d+)\)\s+(.*)$') {
            $script:ModsDone = [int]$Matches[1]
            Set-Status 'downloading mods' -Done ([int]$Matches[1]) -Total ([int]$Matches[2]) -Detail $Matches[3]
            if (-not $script:Ui) { Write-Host "         $line" -ForegroundColor DarkGray }
        } elseif ($line -match '^(Loading|Checking|Comparing|Modpack name)') {
            Set-Status 'checking mods' -Detail $line.Trim()
        }
    }
    if ($run.ExitCode -ne 0) { Write-ToolFailure $run "packwiz-installer exited with code $($run.ExitCode)." }
    Set-Status ''
    if ($script:ModsDone) {
        Write-Log OK "downloaded $($script:ModsDone) mod files"
    } else {
        Write-Log OK 'all mods are up to date'
    }
    Write-Log INFO "$baseName needs at least 8 GB of memory: CurseForge settings, Minecraft, Java Settings."
    Write-Log OK "ready. Open CurseForge, pick '$($curseForge.Name)' and press Play."
    $result = 0
}
catch {
    $result = 2
    Set-Status ''
    Write-Log FAIL $_.Exception.Message
}
finally {
    if ($lock) { $lock.Dispose() }
}
Wait-Close $(if ($result -eq 0) { 'press any key to close' } else { 'synchronization failed. Press any key to close.' })
Stop-Ui
if ($result -ne 0 -and $script:RunLog) { Write-Host "Log saved to $($script:RunLog)" -ForegroundColor DarkGray }
exit $result
