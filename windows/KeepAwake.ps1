# Keeps Windows from sleeping while there is someone in WSL to work.
#
# The only source of the decision is the state file that WSL writes:
# C:\Users\<user>\.keepawake\state.json. This script only reads it, and any
# read failure means "release", not "hold": the cost of the two mistakes is not
# symmetric. Failing to sleep means a battery flattened overnight; sleeping too
# early means pressing a button in Telegram. Hence fail-safe everywhere here.
#
# Started by the startup folder at logon and lives for the whole session. A copy
# of the script sits next to the state rather than in the WSL repository: over
# \\wsl$ it would be unreachable exactly when it is needed — with WSL stopped.
#
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File <path>\KeepAwake.ps1
#
# The file must sit on the Windows drive as UTF-8 WITH a BOM. PowerShell 5.1
# reads UTF-8 without a BOM as ANSI, and any non-ASCII byte in the file then
# decodes to something else, string lengths drift apart, and the parser loses
# block boundaries — the script fails on "Missing closing }" at a spot where
# everything is written correctly. install.sh adds the BOM when copying.

$ErrorActionPreference = 'Stop'

$Root      = Join-Path $env:USERPROFILE '.keepawake'
$StateFile = Join-Path $Root 'state.json'
$LogFile   = Join-Path $Root 'keepawake-ps.log'

# The state file's schema. We do not try to read a foreign version — we go
# fail-safe rather than guess what unfamiliar fields mean.
$SchemaVersion = 1

# This many seconds without the file being updated and we consider WSL dead.
# The detector runs once a minute, so fifteen minutes of silence is a failure,
# not a lull. There is nobody left to keep the laptop awake. The value must
# match STALE_AFTER in keepawake/state.py.
$StaleAfter = 900

# Polling twice as often as the minute-long detector, so that "Let it sleep"
# takes effect almost at once, and an order of magnitude cheaper than Windows'
# fifteen-minute idle window.
$PollSeconds = 30

$LogMaxBytes = 1MB

# --- the hold ----------------------------------------------------------------

# The flags are written as decimal [uint32] literals rather than hex:
# PowerShell 5.1 parses 0x80000000 as a signed Int32, gets -2147483648 and fails
# on the cast to uint. That is the first thing to break in a script like this.
$ES_CONTINUOUS       = [uint32]2147483648   # 0x80000000
$ES_SYSTEM_REQUIRED  = [uint32]1            # 0x00000001

# ES_DISPLAY_REQUIRED is deliberately not used: it is the system that needs
# holding, and the screen may go dark. A panel lit all night is wear and power
# drain, and it has no effect on holding the system.

if (-not ('KeepAwake.Native' -as [type])) {
  Add-Type -Namespace KeepAwake -Name Native -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true)]
public static extern uint SetThreadExecutionState(uint esFlags);
'@
}

function Write-Log([string]$Message) {
  try {
    if ((Test-Path $LogFile) -and (Get-Item $LogFile).Length -gt $LogMaxBytes) {
      # We trim to the tail rather than delete: the last lines are the only
      # thing that shows how it all ended.
      $tail = Get-Content $LogFile -Tail 200
      Set-Content -Path $LogFile -Value $tail -Encoding UTF8
    }
    $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    Add-Content -Path $LogFile -Value "$stamp  $Message" -Encoding UTF8
  } catch {
    # The log is no reason to fall over. If it will not write, the work
    # matters more than the record of it.
  }
}

function Set-Hold([bool]$Hold) {
  # The assignment is in two lines rather than an if-expression: PowerShell 5.1
  # cannot do "variable = if (...) {} else {}" and breaks parsing of the whole
  # rest of the file at that spot.
  $flags = $ES_CONTINUOUS
  if ($Hold) { $flags = $ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED }
  $prev  = [KeepAwake.Native]::SetThreadExecutionState($flags)
  if ($prev -eq 0) {
    # Zero is the only sign the API refused. Knowing about it matters:
    # powercfg /requests needs an administrator and is out of reach in ordinary
    # diagnostics.
    $err = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
    Write-Log "ERROR: SetThreadExecutionState returned 0 (GetLastError=$err)"
    return $false
  }
  return $true
}

# --- state -------------------------------------------------------------------

function Read-State {
  # rename is atomic for the content, but Windows can still open the file at
  # the very moment of the swap and get an IOException. Three tries, 200 ms
  # apart.
  for ($i = 0; $i -lt 3; $i++) {
    try {
      $raw = Get-Content -Path $StateFile -Raw -ErrorAction Stop
      if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
      return $raw | ConvertFrom-Json -ErrorAction Stop
    } catch {
      Start-Sleep -Milliseconds 200
    }
  }
  return $null
}

function Test-Hold($State, [long]$Now) {
  # A word-for-word twin of should_hold in keepawake/state.py. A divergence
  # between them is a laptop that sleeps at the wrong moment, so the conditions
  # are listed in the same order and with the same boundaries.
  if ($null -eq $State)                     { return $false }
  if ($State.version -ne $SchemaVersion)    { return $false }

  $updated = $State.updated_ts -as [long]
  if ($null -eq $updated)                   { return $false }

  # A stale heartbeat cancels everything, hard holds included: a WSL that has
  # been silent for fifteen minutes cannot confirm anything.
  if ($updated -le ($Now - $StaleAfter))    { return $false }

  # A hard holder — a live SSH session, a terminal in code-server, traffic
  # going through the tailnet — means a person is at the machine. With one
  # present we do not look at the deadline at all.
  if ($State.hard_hold -eq $true)           { return $true }

  $until = $State.until_ts -as [long]
  if ($null -eq $until)                     { return $false }
  return ($until -gt $Now)
}

# --- the loop ----------------------------------------------------------------

# A single instance. Two scripts do not stop each other from holding the system
# — the hold is not counted, it is either there or not — but each keeps its own
# $held and writes to a shared log, which stops the log being a source of truth.
# Debug runs have already left two processes behind, and untangling their
# interleaving afterwards cost more than this check.
$mutex = New-Object System.Threading.Mutex($false, "Global\KeepAwakeSingleton")
if (-not $mutex.WaitOne(0, $false)) {
  Write-Log "exit: KeepAwake.ps1 is already running (this one's pid is $PID)"
  exit 0
}

Write-Log "start: pid=$PID, state=$StateFile"

# ES_CONTINUOUS applies to a thread and lives as long as the thread that set
# it. Hence one long-lived single-threaded process rather than a task started on
# a schedule.
$held    = $null  # nothing decided yet
$broken  = $false # report an API refusal once, not every 30 seconds
$loggedUntil = 0  # the deadline already written to the log

# How often to remind the log that the hold is alive. Without this the entry
# stayed from the moment it was switched on, and an hour later looked as though
# the script had hung or was holding the system until a long-past time. Once
# every ten minutes is often enough that the log does not lie, and rare enough
# that it does not grow.
$LogEverySeconds = 600
$lastLog = 0

while ($true) {
  try {
    $now   = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $state = Read-State
    $want  = Test-Hold $state $now

    if ($want -ne $held) {
      if (Set-Hold $want) {
        $broken = $false
        if ($want) {
          if ($state.hard_hold -eq $true) {
            Write-Log "hold set: a person is at the machine"
          } else {
            $untilLocal = [DateTimeOffset]::FromUnixTimeSeconds($state.until_ts).ToLocalTime().ToString('HH:mm')
            Write-Log "hold set, until $untilLocal"
          }
          $loggedUntil = $state.until_ts
          $lastLog = $now
        } else {
          Write-Log 'hold released'
          $loggedUntil = 0
          $lastLog = $now
        }
        $held = $want
      } elseif (-not $broken) {
        $broken = $true
      }
    } elseif ($want) {
      # We repeat the call with the same flags: harmless, and it refreshes the
      # state if something has reset it.
      [void][KeepAwake.Native]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED)

      # The deadline creeps forward while there are holders and the mode does
      # not change — without this entry the log would show the moment the hold
      # was switched on for ever.
      if (($now - $lastLog) -ge $LogEverySeconds -and $state.until_ts -ne $loggedUntil) {
        $untilLocal = [DateTimeOffset]::FromUnixTimeSeconds($state.until_ts).ToLocalTime().ToString('HH:mm')
        Write-Log "holding, until $untilLocal"
        $loggedUntil = $state.until_ts
        $lastLog = $now
      }
    }
  } catch {
    # No error may kill the loop: a dead script will not release the hold, and
    # the startup folder only brings it back at the next logon.
    Write-Log "ERROR in the loop: $($_.Exception.Message)"
    if ($held -ne $false) {
      [void](Set-Hold $false)
      $held = $false
    }
  }
  Start-Sleep -Seconds $PollSeconds
}
