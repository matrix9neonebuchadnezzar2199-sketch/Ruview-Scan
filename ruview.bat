@echo off
REM =============================================================================
REM RuView Scan - Windows起動スクリプト
REM =============================================================================

cd /d "%~dp0"

set HOST=127.0.0.1
set PORT=8080
set SIMULATE=
set LOG_LEVEL=INFO

:parse_args
if "%~1"=="" goto :start
if "%~1"=="--simulate" (set SIMULATE=--simulate & shift & goto :parse_args)
if "%~1"=="--host" (set HOST=%~2 & shift & shift & goto :parse_args)
if "%~1"=="--port" (set PORT=%~2 & shift & shift & goto :parse_args)
if "%~1"=="--debug" (set LOG_LEVEL=DEBUG & shift & goto :parse_args)
if "%~1"=="--help" (
    echo Usage: ruview.bat [options]
    echo   --simulate    シミュレーションモードで起動
    echo   --host HOST   リッスンアドレス ^(default: 127.0.0.1^)
    echo   --port PORT   リッスンポート ^(default: 8080^)
    echo   --debug       デバッグログを有効化
    exit /b 0
)
shift
goto :parse_args

:start
REM 仮想環境
if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat
if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat

set PYTHONPATH=%~dp0;%PYTHONPATH%

echo ==============================================
echo  RuView Scan v1.0
echo ==============================================
echo  Host: %HOST%:%PORT%
echo  Simulate: %SIMULATE%
echo  Log Level: %LOG_LEVEL%
echo ==============================================

python -m src.main --host %HOST% --port %PORT% --log-level %LOG_LEVEL% %SIMULATE%
