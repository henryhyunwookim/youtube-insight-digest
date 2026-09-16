@echo off
REM ===========================================================================
REM YouTube Insight Digest - One-Click Execution Batch Script
REM Runs daily at 12:00 PM JST or manually via CLI
REM ===========================================================================

chcp 65001 > nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo ===========================================================================
echo Starting YouTube Insight Digest (Japan Time 12:00 PM Trigger)...
echo ===========================================================================

py -3.11 -m src.main %*

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Script encountered an error during execution.
    exit /b %ERRORLEVEL%
)

echo [SUCCESS] Run completed successfully.
