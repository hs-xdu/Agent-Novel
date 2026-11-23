$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$documents = @(Get-ChildItem -LiteralPath (Join-Path $root 'docs') -Filter 'MVP设计文档.md' -File)
if ($documents.Count -ne 1) { throw 'Expected exactly one MVP design document.' }
$actual = (Get-FileHash -LiteralPath $documents[0].FullName -Algorithm SHA256).Hash
if ($actual -ne 'A1481FDA80BF6BBCAF4B7FC01706FA9905D50AF4457B3047FA6E2D6F42E4B628') { throw 'Design document differs from the supplied V0.1 source; review and update this snapshot when intentionally changing the design.' }
$utf8 = [System.Text.UTF8Encoding]::new($false, $true)
$content = $utf8.GetString([System.IO.File]::ReadAllBytes($documents[0].FullName))
if ([regex]::Matches($content, '(?m)^## \d+\. ').Count -ne 10) { throw 'Expected ten main sections.' }
Write-Output 'PASS: MVP design document preserves the source exactly, is valid UTF-8, and contains all ten sections.'