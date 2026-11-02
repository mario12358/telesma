# Telesma installer for Windows. Gets what Telesma needs (Git for Windows, Python, Claude Code),
# then Telesma itself, signs in to Claude and puts a "Telesma" shortcut on the desktop that opens
# the start menu (telesma.sh --home) in a Git Bash window - after this a person never types a
# path or a command. In PowerShell:
#
#   irm https://raw.githubusercontent.com/mario12358/telesma/main/install.ps1 | iex
#
# Every installation asks first. Running it again keeps what is there and updates Telesma.
# ASCII only: Windows PowerShell 5.1 reads a file without a BOM in the ANSI code page. The lines a
# person reads come from templates/messages/<lang>.txt (fetched first, English when there is none).
# Failures `return` from Install-Telesma instead of `exit`: under `| iex` exit closes the window.
# Overrides (tests, forks): TELESMA_REPO (a URL or a local clone), TELESMA_BRANCH,
# TELESMA_INSTALL_DIR, TELESMA_PROJECTS, TELESMA_DESKTOP.

$ErrorActionPreference = 'Continue'   # 'Stop' turns a native command's stderr into an exception in 5.1

function Get-Setting($name, $default) {
    $v = [Environment]::GetEnvironmentVariable($name)
    if ($v) { return $v } else { return $default }
}

$Repo = Get-Setting 'TELESMA_REPO' 'https://github.com/mario12358/telesma.git'
$Branch = Get-Setting 'TELESMA_BRANCH' 'main'
$Dest = Get-Setting 'TELESMA_INSTALL_DIR' (Join-Path $HOME '.telesma')
# Projects not in Documents, which OneDrive often syncs (a synced project loses file contents to the
# cloud and breaks); the real Desktop folder, which may be redirected to OneDrive
$Projects = Get-Setting 'TELESMA_PROJECTS' (Join-Path $HOME 'Telesma')
$Desktop = Get-Setting 'TELESMA_DESKTOP' ([Environment]::GetFolderPath('Desktop'))

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

# --- messages: the catalog of templates/messages/msg.sh, `KEY = text` with %s placeholders --------
$Catalog = @{}
$Lang = (Get-UICulture).TwoLetterISOLanguageName
if ($Lang -and $Lang -ne 'en') {
    try {
        if (Test-Path $Repo) {
            $text = Get-Content -Raw -Encoding UTF8 (Join-Path $Repo "templates/messages/$Lang.txt")
        } else {
            $text = (Invoke-WebRequest -UseBasicParsing "https://raw.githubusercontent.com/mario12358/telesma/$Branch/templates/messages/$Lang.txt").Content
        }
        foreach ($line in ($text -split "`n")) {
            if ($line -match '^([a-z0-9_.]+) = (.*)$') { $Catalog[$Matches[1]] = $Matches[2].TrimEnd("`r") }
        }
    } catch {}
}

function msg {
    param([string]$Key, [string]$Text)
    if ($Catalog.ContainsKey($Key)) { $Text = $Catalog[$Key] }
    foreach ($a in $args) {
        $i = $Text.IndexOf('%s')
        if ($i -ge 0) { $Text = $Text.Substring(0, $i) + $a + $Text.Substring($i + 2) }
    }
    return $Text
}

# yes/no with "yes" as the default
function Ask($question) {
    $a = (Read-Host "$question [$(msg yes.no 'Y/n')]").Trim().ToLower()
    return ($a -eq '' -or $a -eq 'y' -or $a -eq 'yes' -or $a -eq (msg yes.short 'y') -or $a -eq (msg yes.word 'yes'))
}

function Step($text) { Write-Host ''; Write-Host $text -ForegroundColor Green }
function Ok($text) { Write-Host "  OK  $text" }
function Say($text) { Write-Host "  $text" }
function Fail($text) { Write-Host $text -ForegroundColor Red }

# A new install is visible in this window only after the PATH is read again
function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

# Put a folder at the front of the user's PATH (before the Store's python3 placeholder)
function Add-UserPath($dir) {
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $parts = @(($user -split ';') | Where-Object { $_ -and ($_.TrimEnd('\') -ne $dir.TrimEnd('\')) })
    [Environment]::SetEnvironmentVariable('Path', (@($dir) + $parts) -join ';', 'User')
    Update-SessionPath
}

function Install-WithWinget($id, $extra) {
    $wingetArgs = @('install', '--id', $id, '-e', '--source', 'winget', '--accept-source-agreements', '--accept-package-agreements') + $extra
    & winget @wingetArgs
    Update-SessionPath
}

function Find-GitBash {
    foreach ($p in @("$env:ProgramFiles\Git\git-bash.exe", "${env:ProgramFiles(x86)}\Git\git-bash.exe", "$env:LOCALAPPDATA\Programs\Git\git-bash.exe")) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        $p = Join-Path (Split-Path (Split-Path $git.Source)) 'git-bash.exe'
        if (Test-Path $p) { return $p }
    }
    return $null
}

# The real python.exe (3.9+): `py -3` or `python`; the Store placeholder prints nothing useful
function Find-Python {
    foreach ($c in @(@('py', '-3'), @('python'), @('python3'))) {
        if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
        $rest = @($c | Select-Object -Skip 1)
        $out = & $c[0] @rest -c 'import sys; print(sys.version_info >= (3, 9)); print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $out -and $out[0] -eq 'True') { return $out[1] }
    }
    return $null
}

function Test-Python3 {
    if (-not (Get-Command python3 -ErrorAction SilentlyContinue)) { return $false }
    $out = & python3 -c 'import sys; print(sys.version_info >= (3, 9))' 2>$null
    return ($LASTEXITCODE -eq 0 -and $out -eq 'True')
}

function Install-Telesma {
    Write-Host (msg inst.title '=== Telesma - installation ===') -ForegroundColor Green
    Write-Host (msg inst.intro 'Telesma builds programs with Claude Code. This installs what it needs and asks before each step.')
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail (msg inst.winget 'winget is missing: update "App Installer" in the Microsoft Store, then run the installer again.')
        return
    }

    # --- 1. Git for Windows (git and the Git Bash window Telesma runs in) ---
    Step (msg inst.s.git.win '1/5  Git for Windows')
    $gitBash = Find-GitBash
    if (-not $gitBash) {
        Say (msg inst.git.win 'Git for Windows is needed: it brings git and the window Telesma works in.')
        if (-not (Ask ('  ' + (msg inst.ok 'Go ahead?')))) { Fail (msg inst.stop 'Stopped. Run the installer again when you are ready.'); return }
        Install-WithWinget 'Git.Git' @()
        $gitBash = Find-GitBash
        if (-not $gitBash) { Fail (msg inst.fail 'The installation did not finish - see the lines above, then run the installer again.'); return }
    }
    Ok (& git --version)

    # --- 2. Python, callable as python3 (hooks, checks and tools call it by that name) ---
    Step (msg inst.s.py.win '2/5  Python')
    if (-not (Test-Python3)) {
        $exe = Find-Python
        if (-not $exe) {
            Say (msg inst.py.win 'Python is needed for the checks Telesma runs.')
            if (-not (Ask ('  ' + (msg inst.ok 'Go ahead?')))) { Fail (msg inst.stop 'Stopped. Run the installer again when you are ready.'); return }
            Install-WithWinget 'Python.Python.3.13' @('--override', '/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=0')
            $exe = Find-Python
            if (-not $exe) {
                $guess = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
                if (Test-Path $guess) { $exe = $guess }
            }
            if (-not $exe) { Fail (msg inst.fail 'The installation did not finish - see the lines above, then run the installer again.'); return }
        }
        # python.org installs python.exe; python3 is the Store placeholder - a copy under that name, first on PATH
        $dir = Split-Path $exe
        try {
            if (-not (Test-Path (Join-Path $dir 'python3.exe'))) { Copy-Item $exe (Join-Path $dir 'python3.exe') -ErrorAction Stop }
        } catch {
            # Python for all users (Program Files): the copy needs an administrator
            Fail (msg inst.py.admin 'Could not create python3.exe in %s - run PowerShell as administrator and the installer again.' $dir)
            return
        }
        Add-UserPath (Join-Path $dir 'Scripts')
        Add-UserPath $dir
        if (-not (Test-Python3)) {
            Fail (msg pre.py.win3 'Then turn off the Store placeholders: Settings -> Apps -> Advanced app settings -> App execution aliases -> python.exe and python3.exe off.')
            return
        }
    }
    Ok (& python3 --version)

    # --- 3. Telesma itself (LF line endings: Bash cannot read CRLF) ---
    Step (msg inst.s.telesma.win '3/5  Telesma')
    # The source and branch asked for, not the ones of the last run (another TELESMA_REPO/BRANCH).
    # A clone that cannot get there (another history, files git does not know, edits) is moved
    # aside whole - nothing in it is lost - and Telesma is downloaded again.
    if (Test-Path (Join-Path $Dest '.git')) {
        & git -C $Dest remote set-url origin $Repo 2>$null
        & git -C $Dest fetch -q origin $Branch 2>$null
        $updated = ($LASTEXITCODE -eq 0)
        if ($updated) {
            & git -C $Dest checkout -q $Branch 2>$null
            if ($LASTEXITCODE -ne 0) {
                # Only a branch that is not there yet is made; one that is there but would not switch is not
                & git -C $Dest show-ref --verify --quiet "refs/heads/$Branch" 2>$null
                if ($LASTEXITCODE -eq 0) { $updated = $false } else {
                    & git -C $Dest checkout -q -b $Branch FETCH_HEAD 2>$null
                    $updated = ($LASTEXITCODE -eq 0)
                }
            }
        }
        if ($updated) { & git -C $Dest merge -q --ff-only FETCH_HEAD 2>$null; $updated = ($LASTEXITCODE -eq 0) }
        if (-not $updated) {
            $aside = $Dest + '.old-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
            try { Move-Item -LiteralPath $Dest -Destination $aside -ErrorAction Stop } catch {
                Fail (msg inst.pull 'Telesma in %s could not be updated (changed by hand?).' $Dest); return
            }
            Say (msg inst.aside 'The Telesma in %s could not be updated; it is kept as %s.' $Dest $aside)
        }
    }
    if (Test-Path (Join-Path $Dest '.git')) {
        Ok (msg inst.updated 'Telesma updated: %s' $Dest)
    } elseif (Test-Path $Dest) {
        Fail (msg inst.exists '%s already exists and is not Telesma - move it away and run the installer again.' $Dest); return
    } else {
        & git clone -q -c core.autocrlf=false --branch $Branch $Repo $Dest
        if ($LASTEXITCODE -ne 0) { Fail (msg inst.fail 'The installation did not finish - see the lines above, then run the installer again.'); return }
        Ok (msg inst.cloned 'Telesma downloaded: %s' $Dest)
    }

    # --- 4. Claude Code and the sign-in ---
    Step (msg inst.s.claude.win '4/5  Claude Code')
    $localBin = Join-Path $HOME '.local\bin'
    if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
        Say (msg inst.claude 'Claude Code is not installed. It needs a Claude account with a paid plan (Pro or Max).')
        if (-not (Ask ('  ' + (msg inst.claude.ask 'Install it now (the official installer from claude.ai)?')))) { Fail (msg inst.stop 'Stopped. Run the installer again when you are ready.'); return }
        Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression
        if ((Test-Path (Join-Path $localBin 'claude.exe')) -and -not (Get-Command claude -ErrorAction SilentlyContinue)) { Add-UserPath $localBin }
        Update-SessionPath
        if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { Fail (msg inst.claude.fail 'Claude Code did not install - see the lines above.'); return }
    }
    Ok ("Claude Code (" + ((& claude --version 2>$null) | Select-Object -First 1) + ")")
    if (-not $env:ANTHROPIC_API_KEY -and ((& claude auth status 2>$null) -join ' ') -match '"loggedIn":\s*false') {
        Say (msg inst.login 'Now sign in to your Claude account: a browser window opens.')
        & claude auth login
        if (((& claude auth status 2>$null) -join ' ') -match '"loggedIn":\s*false') {
            Write-Host ('  ' + (msg inst.login.later 'Not signed in yet - Telesma asks again when it starts.')) -ForegroundColor Yellow
        }
    }

    # --- 5. The projects folder and the shortcut: Git Bash runs telesma.sh --home in its own window ---
    Step (msg inst.s.shortcut.win '5/5  The shortcut')
    New-Item -ItemType Directory -Force -Path $Projects | Out-Null
    $script = Join-Path $Dest 'telesma.sh'
    $arguments = "--no-cd `"$script`" --home `"$Projects`""
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path $Desktop 'Telesma.lnk'))
    $link.TargetPath = $gitBash
    $link.Arguments = $arguments
    $link.WorkingDirectory = $Projects
    $link.IconLocation = "$gitBash,0"
    $link.Description = 'Telesma'
    $link.Save()
    Ok (msg inst.shortcut 'On the desktop: <Telesma>. Your projects will be in %s.' $Projects)

    Write-Host ''
    Write-Host (msg inst.done 'Done. From now on: double-click <Telesma> on the desktop.') -ForegroundColor Green
    if (Ask (msg inst.start 'Start Telesma now?')) {
        Start-Process -FilePath $gitBash -ArgumentList $arguments -WorkingDirectory $Projects
    }
}

Install-Telesma
