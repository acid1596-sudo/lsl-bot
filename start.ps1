<#
.SYNOPSIS
    Sets up lsl-bot on the first run, then starts it. Safe to run again any time.
#>

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Root = $PSScriptRoot
$EnvFile = Join-Path $Root '.env'
$DataDir = Join-Path $Root 'data'
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'

function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-ExitCode([string]$What) {
    if ($LASTEXITCODE -ne 0) {
        throw "Something went wrong while $What (exit code $LASTEXITCODE). See the messages above."
    }
}

function Write-Utf8File([string]$Path, [string]$Text) {
    # Windows PowerShell's Set-Content adds a byte-order mark, which
    # python-dotenv would read as part of the first line.
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding $false))
}

function Get-EnvValue([string]$Path, [string]$Name) {
    $pattern = '^\s*' + [regex]::Escape($Name) + '\s*=(.*)$'
    $value = ''
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        if ($line -match $pattern) {
            $value = $Matches[1].Trim().Trim([char[]]@('"', "'"))
        }
    }
    return $value
}

function Set-EnvValue([string]$Path, [string]$Name, [string]$Value) {
    $pattern = '^\s*' + [regex]::Escape($Name) + '\s*='
    $found = $false
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        if ($line -match $pattern) {
            $lines.Add("$Name=$Value")
            $found = $true
        } else {
            $lines.Add($line)
        }
    }
    if (-not $found) {
        $lines.Add("$Name=$Value")
    }
    Write-Utf8File $Path (($lines -join "`n") + "`n")
}

function New-Secret {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return -join ($bytes | ForEach-Object { $_.ToString('x2') })
}

function Read-Secret([string]$Prompt) {
    $secure = Read-Host -Prompt $Prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim()
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Update-SessionPath {
    # winget records PATH changes in the registry; this window only sees them after a reload.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Install-WithWinget([string]$Id, [string]$Name, [string]$ManualUrl) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "$Name isn't installed, and winget isn't available to install it automatically. Install it from $ManualUrl, then run start.cmd again."
    }
    Write-Host "Installing $Name (Windows may ask for permission)..."
    # Out-Host keeps winget's text on screen instead of in this function's
    # return value, which would otherwise leak into callers like Start-Tunnel.
    & winget install --exact --id $Id --accept-package-agreements --accept-source-agreements | Out-Host
    Update-SessionPath
}

function Find-Python {
    # A fresh Windows often has a "python" that only opens the Microsoft Store,
    # so each candidate is actually run before it's trusted. The probe avoids
    # double quotes, which Windows PowerShell mangles when passing arguments.
    $probe = 'import sys; print(sys.executable) if sys.version_info >= (3, 9) else None'
    $candidates = @()
    foreach ($name in @('py', 'python', 'python3')) {
        $candidates += @(Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | ForEach-Object { $_.Path })
    }
    foreach ($pattern in @("$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "$env:ProgramFiles\Python3*\python.exe")) {
        $candidates += @(Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    }
    foreach ($exe in $candidates) {
        $prefix = @()
        if ([IO.Path]::GetFileNameWithoutExtension($exe) -eq 'py') {
            $prefix = @('-3')
        }
        try {
            $output = & $exe @prefix -c $probe 2>$null
        } catch {
            continue
        }
        if ($LASTEXITCODE -eq 0 -and $output) {
            $path = "$(@($output)[-1])".Trim()
            if ($path) {
                return $path
            }
        }
    }
    return $null
}

function Initialize-EnvFile {
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        Copy-Item -LiteralPath (Join-Path $Root '.env.example') -Destination $EnvFile
    }

    if (-not (Get-EnvValue $EnvFile 'OPENAI_API_KEY') -and -not (Get-EnvValue $EnvFile 'ANTHROPIC_API_KEY')) {
        Write-Step 'Your API keys'
        Write-Host 'Paste each key and press Enter (the text stays hidden). Press Enter on its own to skip one.'
        Write-Host 'They are saved only in the .env file in this folder.'
        Write-Host '  OpenAI (ChatGPT) keys:   https://platform.openai.com/api-keys'
        Write-Host '  Anthropic (Claude) keys: https://console.anthropic.com/settings/keys'
        $openai = Read-Secret 'OpenAI API key'
        $anthropic = Read-Secret 'Anthropic API key'
        if (-not $openai -and -not $anthropic) {
            throw 'The bot needs at least one API key. ChatGPT Plus and Claude Pro subscriptions do not include API access, so create a key at one of the links above, then run start.cmd again.'
        }
        $providers = @()
        if ($openai) {
            $providers += 'openai'
            Set-EnvValue $EnvFile 'OPENAI_API_KEY' $openai
            Write-Host "Saved OpenAI key ending ...$($openai.Substring([Math]::Max(0, $openai.Length - 4)))"
        }
        if ($anthropic) {
            $providers += 'anthropic'
            Set-EnvValue $EnvFile 'ANTHROPIC_API_KEY' $anthropic
            Write-Host "Saved Anthropic key ending ...$($anthropic.Substring([Math]::Max(0, $anthropic.Length - 4)))"
        }
        Set-EnvValue $EnvFile 'PRIMARY_PROVIDERS' ($providers -join ',')
    }

    if (-not (Get-EnvValue $EnvFile 'BOT_SHARED_SECRET')) {
        Set-EnvValue $EnvFile 'BOT_SHARED_SECRET' (New-Secret)
    }

    # Earlier versions capped Claude's replies at 1024 tokens, too short for a
    # complete script. Only that old default is raised; a value someone chose stays.
    if ((Get-EnvValue $EnvFile 'ANTHROPIC_MAX_TOKENS') -eq '1024') {
        Set-EnvValue $EnvFile 'ANTHROPIC_MAX_TOKENS' '16000'
    }
}

function Get-TunnelChoice {
    $choice = Get-EnvValue $EnvFile 'PUBLIC_TUNNEL'
    if ($choice -eq 'yes' -or $choice -eq 'no') {
        return ($choice -eq 'yes')
    }
    Write-Step 'Using the bot from outside this PC (optional)'
    Write-Host 'Only needed for Second Life, or to use the chat page from another device such as your phone.'
    Write-Host 'A free Cloudflare tunnel gives the bot a public web address without any router changes;'
    Write-Host 'every request still needs the bot''s secret key.'
    $answer = Read-Host 'Open a Cloudflare tunnel each time the bot starts? [y/N]'
    $yes = $answer -match '^\s*y'
    Set-EnvValue $EnvFile 'PUBLIC_TUNNEL' $(if ($yes) { 'yes' } else { 'no' })
    return $yes
}

function Initialize-Python {
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        Write-Step 'Setting up Python for the bot'
        $python = Find-Python
        if (-not $python) {
            Install-WithWinget -Id 'Python.Python.3.12' -Name 'Python' -ManualUrl 'https://www.python.org/downloads/'
            $python = Find-Python
        }
        if (-not $python) {
            throw 'Python is installed, but this window cannot see it yet. Close this window and run start.cmd again.'
        }
        & $python -m venv (Join-Path $Root '.venv')
        Assert-ExitCode 'creating the Python environment'
    }

    $requirements = Join-Path $Root 'requirements.txt'
    $stamp = Join-Path $Root '.venv\requirements.sha256'
    $hash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
    if (-not (Test-Path -LiteralPath $stamp) -or [IO.File]::ReadAllText($stamp).Trim() -ne $hash) {
        Write-Step 'Installing the bot''s Python packages'
        & $VenvPython -m pip install --disable-pip-version-check --quiet -r $requirements
        Assert-ExitCode 'installing Python packages'
        Write-Utf8File $stamp $hash
    }
}

function Test-Url([string]$Url) {
    try {
        Invoke-RestMethod -Uri $Url -TimeoutSec 5 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Wait-ForUrl([string]$Url, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        if (Test-Url $Url) {
            return $true
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Test-OllamaModel([string]$BaseUrl, [string]$Model) {
    $wanted = $Model
    if ($wanted -notlike '*:*') {
        $wanted = "$($wanted):latest"
    }
    try {
        $tags = Invoke-RestMethod -Uri "$BaseUrl/api/tags" -TimeoutSec 10
    } catch {
        return $false
    }
    foreach ($installed in @($tags.models)) {
        if ($installed -and $installed.name -eq $wanted) {
            return $true
        }
    }
    return $false
}

function Get-OllamaUrl {
    # Asks the bot's own code, so this sets up the Ollama the bot will use: an
    # OLLAMA_HOST set in Windows wins over .env, and 0.0.0.0 means this PC.
    try {
        $url = @(& $VenvPython -m lslbot.ollama_host)
        if ($LASTEXITCODE -eq 0 -and $url.Count -gt 0 -and $url[-1]) {
            return ([string]$url[-1]).Trim()
        }
    } catch {
        # Fall back to where Ollama listens unless told otherwise.
    }
    return 'http://127.0.0.1:11434'
}

function Initialize-Ollama {
    $baseUrl = Get-OllamaUrl
    $model = Get-EnvValue $EnvFile 'OLLAMA_MODEL'
    if (-not $model) {
        $model = 'llama3'
    }

    if ($baseUrl -ne 'http://127.0.0.1:11434') {
        Write-Host "OLLAMA_HOST is $baseUrl, so this script leaves Ollama for you to run there."
        return
    }

    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        Write-Step 'Installing Ollama (runs the local fallback model)'
        Install-WithWinget -Id 'Ollama.Ollama' -Name 'Ollama' -ManualUrl 'https://ollama.com/download'
        if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
            throw 'Ollama is installed, but this window cannot see it yet. Close this window and run start.cmd again.'
        }
    }

    if (-not (Test-Url "$baseUrl/api/tags")) {
        Write-Host 'Starting Ollama...'
        Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden
        if (-not (Wait-ForUrl "$baseUrl/api/tags" 30)) {
            throw 'Ollama did not start. Open the Ollama app from the Start menu, then run start.cmd again.'
        }
    }

    if (-not (Test-OllamaModel $baseUrl $model)) {
        Write-Step "Downloading the fallback model '$model' (one time only, several GB)"
        & ollama pull $model
        Assert-ExitCode "downloading the Ollama model '$model'"
    }
}

function Read-SharedText([string]$Path) {
    # cloudflared keeps its log open while we read it, so open it shared.
    try {
        $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    } catch {
        return ''
    }
    try {
        return (New-Object IO.StreamReader($stream)).ReadToEnd()
    } finally {
        $stream.Dispose()
    }
}

function Find-TunnelUrl([string]$Text) {
    # (?!api\.) skips api.trycloudflare.com, which appears in error messages.
    $match = [regex]::Match($Text, 'https://(?!api\.)[-a-z0-9]+\.trycloudflare\.com')
    if ($match.Success) {
        return $match.Value
    }
    return ''
}

function Start-Tunnel([string]$LocalUrl) {
    if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
        Write-Step 'Installing cloudflared (for the free Cloudflare tunnel)'
        Install-WithWinget -Id 'Cloudflare.cloudflared' -Name 'cloudflared' -ManualUrl 'https://github.com/cloudflare/cloudflared/releases'
        if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
            throw 'cloudflared is installed, but this window cannot see it yet. Close this window and run start.cmd again.'
        }
    }

    Write-Step 'Opening the Cloudflare tunnel'
    $log = Join-Path $DataDir 'cloudflared.log'
    $consoleLog = Join-Path $DataDir 'cloudflared-console.log'
    foreach ($file in @($log, $consoleLog)) {
        if (Test-Path -LiteralPath $file) {
            Remove-Item -LiteralPath $file -Force
        }
    }
    # -NoNewWindow keeps cloudflared attached to this window, so closing the
    # window or pressing Ctrl+C stops it along with the bot.
    $process = Start-Process -FilePath 'cloudflared' -NoNewWindow -PassThru `
        -RedirectStandardError $consoleLog `
        -ArgumentList @('tunnel', '--no-autoupdate', '--logfile', "`"$log`"", '--url', $LocalUrl)

    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        if ($process.HasExited) {
            throw "cloudflared stopped unexpectedly. Its log is in $log"
        }
        foreach ($file in @($log, $consoleLog)) {
            $url = Find-TunnelUrl (Read-SharedText $file)
            if ($url) {
                return @{ Process = $process; Url = $url }
            }
        }
        Start-Sleep -Seconds 1
    }
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    throw "Timed out waiting for the Cloudflare tunnel. Its log is in $log"
}

function Write-LslScript([string]$Url, [string]$Secret) {
    $template = [IO.File]::ReadAllText((Join-Path $Root 'scripts/chatbot.lsl'))
    $script = $template.Replace('BOT_URL_HERE', $Url).Replace('BOT_SECRET_HERE', $Secret)
    $path = Join-Path $DataDir 'chatbot.lsl'
    Write-Utf8File $path $script
    try {
        Set-Clipboard -Value $script
    } catch {
        # The clipboard is only a shortcut; the saved file is what matters.
    }
    return $path
}

function Get-Port {
    $port = Get-EnvValue $EnvFile 'PORT'
    if ($port) {
        return $port
    }
    return '8080'
}

function Open-ChatPage([string]$Port) {
    # The key rides in the #fragment, which browsers never send to the server;
    # the page saves it and then wipes it from the address bar.
    $key = [uri]::EscapeDataString((Get-EnvValue $EnvFile 'BOT_SHARED_SECRET'))
    Start-Process "http://127.0.0.1:$Port/#key=$key"
}

function Install-DesktopShortcut {
    if ((Get-EnvValue $EnvFile 'DESKTOP_SHORTCUT') -eq 'no') {
        return
    }
    # A convenience only: failing to make it must never stop the bot starting.
    try {
        $path = Join-Path ([Environment]::GetFolderPath('Desktop')) 'lsl-bot.lnk'
        if (Test-Path -LiteralPath $path) {
            return
        }
        $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
        $shortcut.TargetPath = Join-Path $Root 'start.cmd'
        $shortcut.WorkingDirectory = $Root
        $shortcut.IconLocation = (Join-Path $Root 'assets\lsl-bot.ico') + ',0'
        $shortcut.Description = 'Start lsl-bot and open its chat page'
        $shortcut.Save()
        Write-Host 'Added an lsl-bot shortcut to your desktop.'
    } catch {
        Write-Host "Couldn't add a desktop shortcut ($($_.Exception.Message)). start.cmd still works."
    }
}

function Start-Server([string]$Port) {
    $server = Start-Process -FilePath $VenvPython -ArgumentList "`"$(Join-Path $Root 'run_server.py')`"" `
        -WorkingDirectory $Root -NoNewWindow -PassThru
    # Without touching Handle first, Windows PowerShell can lose the exit code.
    $null = $server.Handle
    $deadline = (Get-Date).AddSeconds(60)
    while (-not $server.HasExited -and (Get-Date) -lt $deadline) {
        if (Test-Url "http://127.0.0.1:$Port/health") {
            Open-ChatPage $Port
            break
        }
        Start-Sleep -Milliseconds 500
    }
    $server.WaitForExit()
    # 0xC000013A is how Windows reports a program stopped with Ctrl+C.
    if ($server.ExitCode -ne 0 -and $server.ExitCode -ne -1073741510) {
        throw "The bot stopped with an error (exit code $($server.ExitCode)). See the messages above."
    }
}

try {
    Set-Location -LiteralPath $Root
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    # Pick up tools an earlier run installed, even if this window predates them.
    Update-SessionPath

    if (-not (Test-Path -LiteralPath $VenvPython)) {
        Write-Host 'lsl-bot: the first run downloads Python, Ollama and a several-GB model, so it takes a while.'
    }
    Initialize-EnvFile
    Install-DesktopShortcut

    $port = Get-Port
    if (Test-Url "http://127.0.0.1:$port/health") {
        Write-Host 'lsl-bot is already running, so this just opens the chat page.'
        Open-ChatPage $port
        exit 0
    }

    $usePublic = Get-TunnelChoice
    Initialize-Python
    Initialize-Ollama

    $tunnel = $null
    try {
        $lslPath = ''
        if ($usePublic) {
            $tunnel = Start-Tunnel "http://127.0.0.1:$port"
            $lslPath = Write-LslScript "$($tunnel.Url)/chat" (Get-EnvValue $EnvFile 'BOT_SHARED_SECRET')
        }

        Write-Step 'lsl-bot is running'
        Write-Host "Chat page:  http://127.0.0.1:$port (opening in your browser)"
        Write-Host "Other apps: use http://127.0.0.1:$port/v1 as their OpenAI API address, and BOT_SHARED_SECRET"
        Write-Host '            from the .env file in this folder as their API key.'
        if ($tunnel) {
            Write-Host "Public:     $($tunnel.Url) (for Second Life, or the chat page on another device)"
            Write-Host "Second Life script: $lslPath (also copied to your clipboard). The public address"
            Write-Host 'changes each time the bot starts, so paste the script into your object again after a restart.'
        }
        Write-Host 'Keep this window open while you use the bot. Press Ctrl+C or close it to stop.'
        Write-Host ''

        Start-Server $port
    } finally {
        if ($tunnel -and -not $tunnel.Process.HasExited) {
            Stop-Process -Id $tunnel.Process.Id -Force -ErrorAction SilentlyContinue
        }
    }
} catch {
    Write-Host ''
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
