# Restart the CrystalPilot workbench server (uvicorn server.app:app on 8010).
# The ONLY sanctioned way to (re)start the server: detached, hidden, logged,
# PID recorded, health-polled. Never start the server as a child of an agent
# shell (a coding-agent session ending takes its children with it).
#
# Process identification (bitten 2026-09-05): `.venv\Scripts\python.exe` is
# the venv *launcher*; the real interpreter it re-executes shows up in
# Win32_Process as `C:\...\pyenv\...\python.exe -X utf8 -m uvicorn ...`, so
# matching on the exe path misses the server and every run "cold starts" on
# an occupied port. Match on the command line (our app + our port) instead,
# kill only the tree roots of those matches, never by bare process name.
#
# INVOCATION RULE: run bare, NEVER pipe stdout (`| tail` etc.) - the spawned
# uvicorn's descendants can inherit the console handle and the pipe never
# sees EOF (bitten live 2026-08-31). Output also goes to
# workdir\restart_server.last.log for post-hoc reading.
#
# Event loop (bitten 2026-09-07, and almost certainly 2026-09-05 19:55 too):
# on the Windows *Proactor* loop one failed overlapped accept - WinError 64,
# "the specified network name is no longer available", i.e. a client that
# resets between AcceptEx and its completion - makes asyncio CLOSE the
# listening socket (asyncio\proactor_events.py, BaseProactorEventLoop.
# _start_serving: it reports "Accept failed on a socket" and then sock.close()).
# The process stays alive, the app keeps running, and nothing is on 8010 any
# more: the server "disappears" with no crash, no exit code and no clue in the
# health poll. The *selector* loop sees the same event as ConnectionAbortedError
# and keeps serving, so pin the loop to it. Cost: select() caps this process at
# 512 concurrent sockets (~20x our real load), and asyncio subprocesses are
# unavailable on it - we use none (the codex SDK spawns app-server with plain
# subprocess.Popen). uvicorn resolves a --loop value it does not recognise as an
# import string for the loop factory itself; tests\test_server_loop.py guards
# both that contract and this flag.
param(
  [int]$Port = 8010,
  [int]$Cores = 4
)
$root = Split-Path -Parent $PSScriptRoot           # H:\CrystalPilot
$workdir = Join-Path $root 'workdir'
if (-not (Test-Path $workdir)) { New-Item -ItemType Directory -Path $workdir | Out-Null }
Start-Transcript -Path (Join-Path $workdir 'restart_server.last.log') -Force | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
Write-Output ("[{0}] restart_server.ps1 port={1} cores={2}" -f $stamp, $Port, $Cores)

$pattern = 'uvicorn server\.app:app.*--port ' + $Port + '(\s|$)'
$all = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match $pattern })
$ids = @($all | ForEach-Object { $_.ProcessId })
$roots = @($all | Where-Object { $ids -notcontains $_.ParentProcessId })
if ($roots.Count -eq 0) { Write-Output 'no existing uvicorn - cold starting' }
foreach ($r in $roots) {
  Write-Output ("killing tree root {0} (started {1}): {2}" -f $r.ProcessId,
    $r.CreationDate, $r.CommandLine.Substring(0, [Math]::Min(110, $r.CommandLine.Length)))
  & taskkill /PID $r.ProcessId /T /F | Write-Output
}
Start-Sleep -Seconds 2
$bound = @(netstat -ano | Select-String (":{0}\s" -f $Port) | Select-String 'LISTENING')
if ($bound.Count -gt 0) {
  Write-Output ("WARNING: port {0} still LISTENING after kill (foreign process?): {1}" -f $Port, ($bound -join ' | '))
}

# codex 0.154 keeps its own log lines in codex-home\logs_2.sqlite. Measured
# 2026-09-16: 1.6 GB after three weeks (~15 MB/min while an engine runs),
# and with a 90+ MB write-ahead log the next app-server start failed with
# "failed to initialize sqlite state runtime" twice in a row. Nothing of
# ours reads it. Rotate it here, when no CrystalPilot codex process can hold
# it (the tree above was just killed; a leftover would be a foreign codex).
$logDb = Join-Path $root 'codex-home\logs_2.sqlite'
$logCap = 256MB
if ((Test-Path $logDb) -and ((Get-Item $logDb).Length -gt $logCap)) {
  $holders = @(Get-CimInstance Win32_Process -Filter "Name='codex.exe'" |
    Where-Object { $_.CommandLine -like ('*' + $root + '\vendor\codex*') })
  if ($holders.Count -eq 0) {
    $mb = [math]::Round((Get-Item $logDb).Length / 1MB)
    foreach ($suffix in @('', '-wal', '-shm')) {
      Remove-Item -LiteralPath ($logDb + $suffix) -Force -ErrorAction SilentlyContinue
    }
    Write-Output ("rotated codex log database ({0} MB) - codex recreates it on start" -f $mb)
  } else {
    Write-Output ("codex log database is {0} MB but a CrystalPilot codex process still holds it; not rotated" -f
      [math]::Round((Get-Item $logDb).Length / 1MB))
  }
}

Set-Location $root
$env:PYTHONUTF8 = '1'
$env:CRYSTALPILOT_CPU_CORES = "$Cores"
$python = Join-Path $root '.venv\Scripts\python.exe'
$p = Start-Process -FilePath $python `
  -ArgumentList '-X','utf8','-m','uvicorn','server.app:app',
    '--loop','asyncio:SelectorEventLoop','--port',"$Port" `
  -WorkingDirectory $root `
  -RedirectStandardOutput (Join-Path $workdir 'uvicorn_r13.log') `
  -RedirectStandardError (Join-Path $workdir 'uvicorn_r13.err.log') `
  -WindowStyle Hidden -PassThru
Set-Content -Path (Join-Path $workdir 'uvicorn_r13.pid') `
  -Value ("launcher_pid={0} started={1} python={2} port={3}" -f $p.Id, $stamp, $python, $Port)

$ok = $false
$health = $null
for ($i = 0; $i -lt 45; $i++) {
  Start-Sleep -Seconds 2
  try {
    $health = Invoke-WebRequest -UseBasicParsing ("http://127.0.0.1:{0}/api/health" -f $Port) -TimeoutSec 5
    if ($health.StatusCode -eq 200) { $ok = $true; break }
  } catch { }
}
if ($ok) {
  $listen = @(netstat -ano | Select-String (":{0}\s" -f $Port) | Select-String 'LISTENING')
  Write-Output ("server up after ~{0}s: {1}" -f (($i + 1) * 2), ($listen -join ' | '))
  Write-Output $health.Content
} else {
  Write-Output ("server NOT up after 90 s - see {0}" -f (Join-Path $workdir 'uvicorn_r13.err.log'))
  exit 1
}
