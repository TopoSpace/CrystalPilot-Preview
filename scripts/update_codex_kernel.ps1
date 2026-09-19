# Install (or upgrade) the official Codex CLI kernel the workbench drives.
#
# The Python SDK (openai-codex) pins an older codex build; the npm package
# @openai/codex ships the current release (0.155.0 on 2026-09-17). This
# script installs it under vendor/codex (git-ignored); the workbench picks
# the newest installed build automatically (crystalpilot/workbench/kernel.py)
# and each project's engine uses it on its next (re)start.
#
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/update_codex_kernel.ps1 [-Version 0.154.0]
#
# Before switching versions, probe the new build against an isolated copy of
# codex-home (scripts/probe_codex_kernel.py + scripts/diff_codex_schema.py:
# protocol schema diff, --strict-config, initialize/model list/MCP status,
# one cheap turn) and check the old build still opens the migrated state
# database -
# the 0.154 -> 0.155 step (2026-09-18) added one migration and was
# backward-openable.
param(
  [string]$Version = "latest"
)
$root = Split-Path -Parent $PSScriptRoot
$dir = Join-Path $root 'vendor\codex'
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
Set-Location $dir
if (-not (Test-Path (Join-Path $dir 'package.json'))) {
  '{ "name": "crystalpilot-codex-kernel", "private": true }' | Set-Content -Path (Join-Path $dir 'package.json') -Encoding UTF8
}
Write-Output ("installing @openai/codex@{0} into {1}" -f $Version, $dir)
& npm install --no-audit --no-fund --silent "@openai/codex@$Version"
if ($LASTEXITCODE -ne 0) { Write-Error "npm install failed"; exit 1 }
# npm parks the package being replaced under a hidden .codex-<pkg>-<rand>
# directory while a running server still holds its exe open; report the
# freshly installed build, not that leftover (2026-09-10: printed 0.153.4
# after a successful 0.154.0 install)
$exe = Get-ChildItem -Path (Join-Path $dir 'node_modules\@openai') -Recurse -Filter 'codex.exe' |
  Where-Object { $_.FullName -notmatch '\\.codex-' } | Select-Object -First 1
if ($null -eq $exe) { Write-Error "no codex.exe found after install"; exit 1 }
$ver = & $exe.FullName --version
Write-Output ("installed: {0}" -f $ver)
Write-Output ("path: {0}" -f $exe.FullName)
Write-Output "Open projects keep their running engine; restart the server (scripts/restart_server.ps1) or reopen a project to use the new kernel."
