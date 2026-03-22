$ErrorActionPreference = "Stop"

$n = 50
$url = "http://localhost:8000/chunks"
$times = @()

for ($i = 0; $i -lt $n; $i++) {
    $body = @{
        snapshot_id = 1
        kind = "rust_baseline"
        lang = "rust"
        content = "fn f$i() {}"
        meta = @{ file = "src/lib.rs" }
    } | ConvertTo-Json -Compress

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        Invoke-RestMethod -Method Post -Uri $url -ContentType "application/json" -Body $body | Out-Null
    } catch {
        Invoke-RestMethod -Method Post -Uri "http://localhost:8000/projects" -ContentType "application/json" -Body '{"name":"bench"}' | Out-Null
        Invoke-RestMethod -Method Post -Uri "http://localhost:8000/snapshots" -ContentType "application/json" -Body '{"project_id":1,"commit_sha":"bench"}' | Out-Null
        Invoke-RestMethod -Method Post -Uri $url -ContentType "application/json" -Body $body | Out-Null
    }
    $sw.Stop()
    $times += $sw.ElapsedMilliseconds
}

$sorted = $times | Sort-Object
$p95Index = [Math]::Ceiling($n * 0.95) - 1
$p95 = $sorted[$p95Index]

@{
    n = $n
    p95_ms = $p95
    max_ms = ($sorted[-1])
    min_ms = ($sorted[0])
} | ConvertTo-Json -Compress | Write-Output
