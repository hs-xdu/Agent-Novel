$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$path = Join-Path $root 'docs/MVP技术方案.md'
$utf8 = [System.Text.UTF8Encoding]::new($false, $true)
$content = $utf8.GetString([System.IO.File]::ReadAllBytes($path))
if (-not $content.StartsWith('# AI 网文写作 Agent MVP 技术方案')) { throw 'Unexpected technical proposal title.' }
$headings = [regex]::Matches($content, '(?m)^## (\d+)\. ')
if ($headings.Count -ne 11) { throw 'Expected eleven main sections.' }
for ($i = 0; $i -lt $headings.Count; $i++) {
    if ([int]$headings[$i].Groups[1].Value -ne ($i + 1)) { throw 'Section numbering is inconsistent.' }
}
foreach ($term in @('NiceGUI', 'Pydantic', 'pytest', 'uv.lock', 'Markdown + JSON', '更新失败', '恢复', '5 章')) {
    if (-not $content.Contains($term)) { throw "Missing agreed technology or acceptance topic: $term" }
}
foreach ($link in [regex]::Matches($content, '\]\(([^)]+)\)')) {
    $target = $link.Groups[1].Value
    if ($target -notmatch '^https?://' -and -not (Test-Path -LiteralPath (Join-Path (Split-Path $path -Parent) $target))) {
        throw "Broken document reference: $target"
    }
}
Write-Output 'PASS: technical proposal is valid UTF-8, covers the agreed scope, has consistent sections and valid local references.'