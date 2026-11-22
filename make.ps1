param(
    [Parameter(Position = 0)]
    [ValidateSet("setup", "demo", "run", "lint", "typecheck", "test", "dbt", "check")]
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
function Invoke-Dbt {
    Invoke-Step "uv" @("run", "dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt")
}

switch ($Target) {
    "setup" {
        Invoke-Step "uv" @("sync")
        Invoke-Step "uv" @("run", "pre-commit", "install")
    }
    "demo" { Invoke-Step "uv" @("run", "python", "-m", "finance_copilot", "demo") }
    "run" { Write-Host "make run is implemented in M3 (FR-10)." }
    "lint" { Invoke-Lint }
    "typecheck" { Invoke-Typecheck }
    "test" { Invoke-Test }
    "dbt" { Invoke-Dbt }
    "check" {
        Invoke-Lint
        Invoke-Typecheck
        Invoke-Test
        Invoke-Dbt
    }
}
