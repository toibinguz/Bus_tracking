param(
    [ValidateSet("up", "health", "down")]
    [string]$Action = "health"
)

$composeFile = Join-Path $PSScriptRoot "..\docker-compose.hdfs.yml"

switch ($Action) {
    "up" {
        docker compose -f $composeFile up --build -d
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        docker compose -f $composeFile exec namenode hdfs dfs -mkdir -p /bus-eta/v1/bronze/telemetry /bus-eta/v1/silver /bus-eta/v1/gold /bus-eta/v1/_checkpoints
    }
    "health" {
        docker compose -f $composeFile exec namenode hdfs dfsadmin -report
    }
    "down" {
        docker compose -f $composeFile down
    }
}
