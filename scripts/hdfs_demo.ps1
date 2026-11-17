param(
    [ValidateSet("up", "health", "down")]
    [string]$Action = "health"
)

$composeFile = Join-Path $PSScriptRoot "..\docker-compose.hdfs.yml"

switch ($Action) {
    "up" {
        docker compose -f $composeFile up --build -d --wait --wait-timeout 180
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        docker compose -f $composeFile exec -T namenode hdfs dfsadmin -safemode wait
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Get-Content -Raw (Join-Path $PSScriptRoot 'hdfs_provision_namespace.sh') | docker compose -f $composeFile exec -T namenode sh -c "tr -d '\r' | sh"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    "health" {
        $clusterReport = docker compose -f $composeFile exec -T namenode hdfs dfsadmin -report | Out-String
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Output $clusterReport
        if ($clusterReport -notmatch 'Live datanodes \(2\):') { throw 'Expected two live HDFS DataNodes' }
    }
    "down" {
        docker compose -f $composeFile --profile '*' down
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
}
