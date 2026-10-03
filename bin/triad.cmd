@echo off
setlocal
set "ENGINE="
if defined TRIAD_ROOT if exist "%TRIAD_ROOT%\triad\triad_engine.py" set "ENGINE=%TRIAD_ROOT%\triad\triad_engine.py"
if not defined ENGINE if exist "%~dp0..\triad\triad_engine.py" set "ENGINE=%~dp0..\triad\triad_engine.py"
if not defined ENGINE if exist "%USERPROFILE%\.agents\triad\triad_engine.py" set "ENGINE=%USERPROFILE%\.agents\triad\triad_engine.py"
if not defined ENGINE (
  echo triad_engine.py not found. Set TRIAD_ROOT or run scripts\install.ps1. 1>&2
  exit /b 1
)
python "%ENGINE%" %*
exit /b %ERRORLEVEL%
