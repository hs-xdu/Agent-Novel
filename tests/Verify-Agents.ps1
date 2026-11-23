$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$actual = [System.IO.File]::ReadAllText((Join-Path $root 'AGENTS.md'), [System.Text.Encoding]::UTF8)
$expected = @"
注意事项
- 每次改动完成后，都必须创建一个对应的 Git commit，以便后续追踪和回滚。
- 每次改动后，都必须编写或更新相关测试，并在交付给用户前，确保所有测试和验证全部通过。
"@
$expected = $expected.Replace("`r`n", "`n").TrimEnd("`r", "`n") + "`n"
if ($actual.Replace("`r`n", "`n") -cne $expected) {
    throw 'AGENTS.md content does not match the requested instructions.'
}
Write-Output 'PASS: AGENTS.md matches the requested instructions and uses real line breaks.'