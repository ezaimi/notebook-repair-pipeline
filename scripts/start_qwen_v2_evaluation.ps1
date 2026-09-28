param(
    [string]$RunId = ("qwen-v2-shared-comparison-evaluation-" + (Get-Date -Format "yyyyMMddTHHmmssZ"))
)

$ErrorActionPreference = "Stop"

# The preflight and Python provider load KISTE_API_TOKEN from the local .env
# file when it is not already exported. Neither prints or persists the token.

py -3 scripts\preflight_qwen_v2.py
if ($LASTEXITCODE -ne 0) {
    throw "Qwen V2 preflight failed; the evaluation was not started."
}

$metadataDb = "C:\Users\zaimi\i8-eval-local-cache\upstream_pmc_docker_db.sqlite"
$attemptDatabase = Join-Path $env:TEMP ("$RunId.sqlite")

py -3 scripts\run_evaluation.py `
    --split evaluation `
    --i-understand-this-touches-the-reserved-split `
    --run-id $RunId `
    --model Qwen3.6-35B-A3B-MLX-8bit `
    --max-rounds 2 `
    --explainer-config config/llm_explainer.v2.qwen.yaml `
    --repair-config config/rag_repair.v2.qwen-shared-comparison.yaml `
    --fix-config config/fix_applicator.v2.qwen.local.yaml `
    --i2-path data/context-classification-v2/dependency_error_contexts.jsonl `
    --repository-metadata-db-path $metadataDb `
    --database-path $attemptDatabase
