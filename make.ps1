param(
    [Parameter(Position = 0)]
    [ValidateSet("setup", "demo", "run", "run-private", "dagster", "dagster-private", "eval", "lint", "typecheck", "test", "dbt", "dbt-private", "check")]
    [string]$Target = "check"
)

$ErrorActionPreference = "Stop"

function Invoke-Step {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Invoke-Lint {
    Invoke-Step "uv" @("run", "ruff", "check", ".")
    Invoke-Step "uv" @("run", "ruff", "format", "--check", ".")
}

function Invoke-Typecheck { Invoke-Step "uv" @("run", "mypy") }
function Invoke-Test { Invoke-Step "uv" @("run", "pytest") }
function Invoke-Demo { Invoke-Step "uv" @("run", "python", "-m", "finance_copilot", "demo") }
function Invoke-DbtBuild {
    param([string]$DbtTarget)
    Invoke-Step "uv" @("run", "dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt", "--target", $DbtTarget)
}
function Invoke-Dbt {
    Invoke-Demo
    Invoke-DbtBuild "demo"
}

switch ($Target) {
    "setup" {
        Invoke-Step "uv" @("sync")
        Invoke-Step "uv" @("run", "pre-commit", "install")
    }
    "demo" { Invoke-Demo }
    "run" { Invoke-Step "uv" @("run", "python", "-m", "finance_copilot", "run") }
    "run-private" { Invoke-Step "uv" @("run", "python", "-m", "finance_copilot", "run", "--private") }
    "dagster" { Invoke-Step "uv" @("run", "python", "-m", "finance_copilot", "orchestrator") }
    "dagster-private" { Invoke-Step "uv" @("run", "python", "-m", "finance_copilot", "orchestrator", "--private") }
    "eval" { Invoke-Step "uv" @("run", "python", "-m", "finance_copilot", "eval-sql") }
    "lint" { Invoke-Lint }
    "typecheck" { Invoke-Typecheck }
    "test" { Invoke-Test }
    "dbt" { Invoke-Dbt }
    "dbt-private" { Invoke-DbtBuild "private" }
    "check" {
        Invoke-Lint
        Invoke-Typecheck
        Invoke-Test
        Invoke-Dbt
    }
}
