$ErrorActionPreference = "Stop"

$containerName = "proj_postgres"
$image = "pgvector/pgvector:pg15"
$user = "root"
$password = "root"
$db = "postgres"
$rootDir = Split-Path -Parent $PSScriptRoot
$schemaPath = Join-Path $rootDir "db\\schema.sql"
$lexicalPath = Join-Path $rootDir "retrieval\\sql\\lexical_search.sql"

$exists = (docker ps -a --format "{{.Names}}" | Select-String -SimpleMatch $containerName) -ne $null
if (-not $exists) {
    docker run -d --name $containerName -e POSTGRES_USER=$user -e POSTGRES_PASSWORD=$password -e POSTGRES_DB=$db -p 5432:5432 $image | Out-Host
}

for ($i = 0; $i -lt 60; $i++) {
    $ok = $true
    try {
        docker exec $containerName pg_isready -U $user -d $db | Out-Null
    } catch {
        $ok = $false
    }
    if ($ok) {
        break
    }
    Start-Sleep -Seconds 1
}

$env:PGPASSWORD = $password
Get-Content $schemaPath -Raw | docker exec -i $containerName psql -U $user -d $db | Out-Host
Get-Content $lexicalPath -Raw | docker exec -i $containerName psql -U $user -d $db | Out-Host
