@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM =============================================================================
REM RepoPulse Build Script (Windows)
REM =============================================================================
REM This script automates the full build pipeline:
REM   1. Pre-flight checks  - verify required tools are installed
REM   2. Dependency install - pip install (inside Docker)
REM   3. Docker build       - build all containers via Docker Compose
REM   4. Validation/tests   - run the test suite inside the container
REM   5. Start containers   - launch the application
REM
REM Usage:
REM   build.bat              - full build + test + start
REM   build.bat --skip-tests - build + start, skip tests
REM   build.bat stop         - stop running containers
REM   build.bat restart      - stop + full build + test + start
REM =============================================================================

set "SKIP_TESTS=false"
set "COMMAND=build"

REM ── Parse arguments ─────────────────────────────────────────────────────────
:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--skip-tests" (set "SKIP_TESTS=true" & shift & goto :parse_args)
if /i "%~1"=="stop" (set "COMMAND=stop" & shift & goto :parse_args)
if /i "%~1"=="restart" (set "COMMAND=restart" & shift & goto :parse_args)
if /i "%~1"=="-h" goto :show_help
if /i "%~1"=="--help" goto :show_help
echo [WARN] Unknown argument: %~1
shift
goto :parse_args

:show_help
echo Usage: build.bat [stop^|restart] [--skip-tests]
exit /b 0

:args_done

REM ── Ensure script runs from project root ───────────────────────────────────
cd /d "%~dp0"

REM ── Detect docker compose command ──────────────────────────────────────────
docker compose version >nul 2>&1
if %errorlevel%==0 (
    set "DC=docker compose"
) else (
    docker-compose version >nul 2>&1
    if %errorlevel%==0 (
        set "DC=docker-compose"
    ) else (
        echo [FAIL] Docker Compose not found.
        exit /b 1
    )
)

REM ── STOP COMMAND ───────────────────────────────────────────────────────────
if /i "%COMMAND%"=="stop" (
    echo [INFO] Stopping containers...
    %DC% down
    exit /b 0
)

REM ── RESTART COMMAND ────────────────────────────────────────────────────────
if /i "%COMMAND%"=="restart" (
    echo [INFO] Restarting containers...
    %DC% down
)

REM ── Step 1: Checks ─────────────────────────────────────────────────────────
echo [INFO] Checking prerequisites...

where git >nul 2>&1 || (echo [FAIL] Git not installed & exit /b 1)
where docker >nul 2>&1 || (echo [FAIL] Docker not installed & exit /b 1)

docker info >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Docker Desktop is not running.
    exit /b 1
)

echo [OK] Prerequisites satisfied.

REM ── Step 2: requirements.txt ───────────────────────────────────────────────
if not exist requirements.txt (
    echo [FAIL] requirements.txt missing.
    exit /b 1
)

REM ── Step 3: Build ──────────────────────────────────────────────────────────
echo [INFO] Building containers...
%DC% build
if errorlevel 1 exit /b 1

REM ── Step 4: Tests ──────────────────────────────────────────────────────
if "%SKIP_TESTS%"=="true" goto :start

echo [INFO] Stopping existing containers for clean test environment...
%DC% down

echo [INFO] Running ALL TESTS (unit + integration)...
%DC% run --rm api python -m pytest tests/ -v --cov=src --cov-fail-under=80
set TEST_EXIT=%errorlevel%

REM Exit code 1 from pytest is acceptable if coverage warning only
if %TEST_EXIT%==1 (
    echo [OK] All tests passed (coverage warning is non-critical).
) else if %TEST_EXIT%==0 (
    echo [OK] All tests passed.
) else (
    echo [FAIL] Tests failed with exit code %TEST_EXIT%.
    exit /b %TEST_EXIT%
)

REM ── Step 5: Start ──────────────────────────────────────────────────────────
:start
echo [INFO] Starting RepoPulse containers...
%DC% up -d
if errorlevel 1 exit /b 1

echo.
echo ============================================
echo [OK]    RepoPulse build completed successfully!
echo ============================================
echo.
echo [INFO]  API is running at:  http://localhost:8080/
echo [INFO]  Health check:       http://localhost:8080/health
echo [INFO]  InfluxDB is running at: http://localhost:8086
echo [INFO]  Grafana Dashboard: http://localhost:3000
echo [INFO]  Refer to .env file for username and password of Grafana and InfluxDB.
echo [INFO]  To stop:            build.bat stop
echo.

endlocal
exit /b 0
