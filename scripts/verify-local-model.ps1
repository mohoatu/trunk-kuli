#Requires -Version 5.1
<#
    Verify kuli against a real local model, once, and write down what happened.

    T7 and T10 in docs/05-provider-tasks.md are built and tested against real
    HTTP endpoints, and have never met a real model deciding for itself which
    tool to call. This script closes that gap and records the evidence rather
    than asserting it.

    It installs Ollama if it is missing, keeps the model files off C: (which is
    the tight drive on this machine), pulls a model small enough to fit in
    6 GB of VRAM, then runs kuli against it and saves a transcript.

    Nothing here is required to use kuli. It is a one-off errand, kept in the
    repository so that anyone can repeat it rather than trust this paragraph.

    Run it from anywhere:
        powershell -ExecutionPolicy Bypass -File scripts\verify-local-model.ps1
#>

param(
    [string]$Repo   = (Split-Path -Parent $PSScriptRoot),
    [string]$Model  = "qwen3:4b",
    [string]$Store  = "D:\ollama-models",
    [string]$Report = (Join-Path ([Environment]::GetFolderPath("Desktop")) "kuli-local-model-verification.txt")
)

$ErrorActionPreference = "Stop"
$script:Lines = New-Object System.Collections.Generic.List[string]

function Say($text) { Write-Host "`n$text" -ForegroundColor Cyan }

function Note($text) {
    $script:Lines.Add($text)
}

function Flush {
    $script:Lines -join [Environment]::NewLine |
        Set-Content -Path $Report -Encoding utf8
}

function Record($title, [scriptblock]$block) {
    Say $title
    Note ""
    Note "=== $title ==="
    Note ""
    # Two rules this script broke on its first run, both of them rules this
    # repository states elsewhere.
    #
    # A step that fails must be recorded rather than fatal. With
    # $ErrorActionPreference = Stop, a native command writing to stderr
    # becomes a terminating error, so `kuli ask` exiting 2 -- which is a
    # verdict, not a crash -- killed the whole errand.
    #
    # And the transcript is flushed after every step. Writing it once at the
    # end meant the first failure lost every piece of evidence gathered
    # before it, which is the opposite of what a recorder is for.
    try {
        $previous = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $out = (& $block 2>&1 | Out-String).TrimEnd()
        Note $out
        Write-Host $out
    } catch {
        $failure = "THIS STEP FAILED: " + $_.Exception.Message
        Note $failure
        Write-Host $failure -ForegroundColor Yellow
    } finally {
        $ErrorActionPreference = $previous
        Flush
    }
}

function HasOllama { [bool](Get-Command ollama -ErrorAction SilentlyContinue) }

function RefreshPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user    = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
    $installed = Join-Path $env:LOCALAPPDATA "Programs\Ollama"
    if (Test-Path $installed) { $env:Path = "$installed;$env:Path" }
}

function PortOpen($port) {
    $client = New-Object Net.Sockets.TcpClient
    try {
        $client.Connect("127.0.0.1", $port)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

# A proxy configured for the browser would send a request for 127.0.0.1 out to
# the internet, where it would fail in a way that looks like a kuli bug.
$env:NO_PROXY  = "127.0.0.1,localhost"
$env:no_proxy  = $env:NO_PROXY

# kuli sends UTF-8. PowerShell 5.1 decodes a child process's output using the
# console's legacy code page unless told otherwise, so an em dash arrives as
# `ΓÇö` and is written into the transcript that way — the mojibake happens
# here, in the capture, not in the program that produced it.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# ---- 1. Ollama ------------------------------------------------------------

if (-not (HasOllama)) {
    Say "Installing Ollama (about 1 GB) with winget..."
    winget install --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
    RefreshPath
}
if (-not (HasOllama)) {
    throw "ollama is still not on PATH. Close this window, open a new one, and run the script again."
}

# ---- 2. Keep the models off C: -------------------------------------------

New-Item -ItemType Directory -Force -Path $Store | Out-Null
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $Store, "User")
$env:OLLAMA_MODELS = $Store
Say "Model files will live in $Store"

# ---- 3. The server -------------------------------------------------------

if (-not (PortOpen 11434)) {
    Say "Starting the Ollama server..."
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden | Out-Null
    for ($waited = 0; $waited -lt 90 -and -not (PortOpen 11434); $waited++) {
        Start-Sleep -Seconds 1
    }
}
if (-not (PortOpen 11434)) {
    throw "Nothing is listening on 127.0.0.1:11434. Run 'ollama serve' in another window and try again."
}

# The tag has to exist in the registry and has to support tool calling, or
# T9 cannot be verified at all. Fallbacks rather than one guess, because a
# missing tag would otherwise end the errand three minutes in.
$candidates = @($Model, "qwen3:4b", "qwen2.5:3b", "llama3.2:3b") |
              Select-Object -Unique
$pulled = $null
foreach ($candidate in $candidates) {
    Say "Pulling $candidate. First time only, a few GB."
    ollama pull $candidate
    if ($LASTEXITCODE -eq 0) { $pulled = $candidate; break }
    Write-Host "  $candidate did not pull; trying the next one." -ForegroundColor Yellow
}
if (-not $pulled) { throw "No model could be pulled. Check the network and try again." }
$Model = $pulled

# ---- 4. kuli against it --------------------------------------------------

Set-Location $Repo
$env:KULI_LOCAL_MODEL = $Model

# An L3 path for the refusal case, outside the repository so it is never
# committed by accident.
$secretDir = Join-Path $env:TEMP "kuli-verify"
New-Item -ItemType Directory -Force -Path $secretDir | Out-Null
$secret = Join-Path $secretDir ".env"
Set-Content -Path $secret -Value "API_KEY=this-should-never-reach-a-model" -Encoding utf8

Note "kuli local-model verification"
Note ("run at " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " on " + $env:COMPUTERNAME)
Note ("repo " + $Repo)

Record "versions" { ollama --version; python --version }
Record "models present" { ollama list }
Record "the suite" { python tests/run.py }
Record "the registry, and what each provider has earned" {
    python -m kuli.cli providers
}

# A cold 4B model has to be loaded into VRAM before it answers a word, and
# qwen3 reasons at length before it speaks. kuli's own default is 60 seconds,
# which is right for a warm endpoint and far too short for the first call --
# and a timeout here reads as "the endpoint could not be reached", which looks
# like a kuli bug rather than a laptop.
$slow = 300

Record "T7 - one completion through the boundary" {
    python -m kuli.cli ask --provider local-llm --timeout $slow --prompt "Say hello in exactly five words."
    "exit code: $LASTEXITCODE"
}

Record "T7 - a secret in the context refuses before a socket opens" {
    python -m kuli.cli ask --provider local-llm --timeout $slow --context $secret --prompt "What is in this file?"
    "exit code: $LASTEXITCODE (2 is correct here: the gate could not judge, so nothing passed)"
}

Record "T9 and T10 - the loop, with the model choosing its own tools" {
    python -m kuli.cli run --provider local-llm --steps 6 --timeout $slow --prompt "List the files in the docs directory, then read docs/02-fleet.md, then tell me in one sentence what that document is for."
    "exit code: $LASTEXITCODE"
}

Record "the trail the loop wrote" { python -m kuli.cli trail --last 14 }
Record "and the chain still verifies" { python -m kuli.cli audit }

Remove-Item $secret -Force -ErrorAction SilentlyContinue

# ---- 5. The transcript ---------------------------------------------------

Flush
Say "Written to $Report"
Write-Host "Send that file back and T7 and T10 can be marked done." -ForegroundColor Green
