@echo off
setlocal EnableExtensions

set "SCRIPT_ROOT=%~dp0"
set "SKILL_SOURCE=%SCRIPT_ROOT%document-reader-skill"
if defined DOCUMENT_READER_HOME (set "RUNTIME_ROOT=%DOCUMENT_READER_HOME%") else (set "RUNTIME_ROOT=%USERPROFILE%\.document-reader")
set "VENV_PYTHON=%RUNTIME_ROOT%\venv\Scripts\python.exe"

if "%~1"=="" (set "PROJECT_ROOT=%CD%") else (set "PROJECT_ROOT=%~1")
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"
if "%~2"=="" (set "REQUIREMENTS_INPUT=requirements") else (set "REQUIREMENTS_INPUT=%~2")
if "%REQUIREMENTS_INPUT:~1,1%"==":" (for %%I in ("%REQUIREMENTS_INPUT%") do set "REQUIREMENTS_ROOT=%%~fI") else (for %%I in ("%PROJECT_ROOT%\%REQUIREMENTS_INPUT%") do set "REQUIREMENTS_ROOT=%%~fI")

set "AGENT=%~3"
set "INSTALL_DEPS=%~4"
if "%AGENT%"=="" set "AGENT=all"
if /I "%AGENT%"=="--agent" (set "AGENT=%~4"& set "INSTALL_DEPS=%~5")
if /I "%AGENT%"=="/install-deps" (set "INSTALL_DEPS=/install-deps"& set "AGENT=all")
if /I "%AGENT%"=="--install-deps" (set "INSTALL_DEPS=--install-deps"& set "AGENT=all")
if /I "%AGENT:~0,8%"=="--agent=" set "AGENT=%AGENT:~8%"
if /I not "%AGENT%"=="codex" if /I not "%AGENT%"=="claude" if /I not "%AGENT%"=="gemini" if /I not "%AGENT%"=="all" (
  echo ERROR: agent must be codex, claude, gemini, or all
  exit /b 2
)

if not exist "%SKILL_SOURCE%\SKILL.md" (echo ERROR: Skill source not found.& exit /b 2)
if not exist "%PROJECT_ROOT%\" (echo ERROR: Project folder not found.& exit /b 2)

echo [1/6] Installing agent skills...
if /I "%AGENT%"=="codex" call :install_skill "%USERPROFILE%\.agents\skills\document-reader"
if /I "%AGENT%"=="claude" call :install_skill "%USERPROFILE%\.claude\skills\document-reader"
if /I "%AGENT%"=="gemini" call :install_skill "%USERPROFILE%\.gemini\skills\document-reader"
if /I "%AGENT%"=="all" (
  call :install_skill "%USERPROFILE%\.agents\skills\document-reader"
  call :install_skill "%USERPROFILE%\.claude\skills\document-reader"
  call :install_skill "%USERPROFILE%\.gemini\skills\document-reader"
)

echo [2/6] Creating project state...
if not exist "%REQUIREMENTS_ROOT%" mkdir "%REQUIREMENTS_ROOT%"
if not exist "%PROJECT_ROOT%\.document-reader" mkdir "%PROJECT_ROOT%\.document-reader"
if not exist "%PROJECT_ROOT%\.document-reader\knowledge.md" (
  copy /Y "%SKILL_SOURCE%\references\project-memory-template.md" "%PROJECT_ROOT%\.document-reader\knowledge.md" >nul
) else (echo Preserved existing .document-reader\knowledge.md)

echo [3/6] Configuring agent instructions...
if /I "%AGENT%"=="codex" call :append_instructions "%PROJECT_ROOT%\AGENTS.md" "%SKILL_SOURCE%\templates\AGENTS.document-reader.md"
if /I "%AGENT%"=="claude" call :append_instructions "%PROJECT_ROOT%\CLAUDE.md" "%SKILL_SOURCE%\templates\CLAUDE.document-reader.md"
if /I "%AGENT%"=="gemini" call :append_instructions "%PROJECT_ROOT%\GEMINI.md" "%SKILL_SOURCE%\templates\GEMINI.document-reader.md"
if /I "%AGENT%"=="all" (
  call :append_instructions "%PROJECT_ROOT%\AGENTS.md" "%SKILL_SOURCE%\templates\AGENTS.document-reader.md"
  call :append_instructions "%PROJECT_ROOT%\CLAUDE.md" "%SKILL_SOURCE%\templates\CLAUDE.document-reader.md"
  call :append_instructions "%PROJECT_ROOT%\GEMINI.md" "%SKILL_SOURCE%\templates\GEMINI.document-reader.md"
)

echo [4/6] Checking Python...
if exist "%VENV_PYTHON%" (set "PYTHON=%VENV_PYTHON%") else (set "PYTHON=python")
"%PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] in tuple((3, i) for i in range(10, 100)) else 1)" >nul 2>&1
if errorlevel 1 (
  echo WARNING: Python 3.10+ was not found; indexing was skipped.
  echo Run: powershell -ExecutionPolicy Bypass -File "%SCRIPT_ROOT%setup-python-env.ps1" then run this installer again.
  exit /b 0
)

echo [5/6] Checking optional dependencies...
if /I "%INSTALL_DEPS%"=="/install-deps" "%PYTHON%" -m pip install openpyxl
if /I "%INSTALL_DEPS%"=="--install-deps" "%PYTHON%" -m pip install openpyxl

echo [6/6] Indexing requirements...
"%PYTHON%" "%SKILL_SOURCE%\scripts\index_documents.py" "%REQUIREMENTS_ROOT%" --output "%PROJECT_ROOT%\.document-reader\manifest.json"
if errorlevel 1 (echo ERROR: Indexing failed. Use /install-deps when Excel files are present.& exit /b 4)
echo Document Reader deployment completed for agent: %AGENT%
exit /b 0

:install_skill
if not exist "%~1" mkdir "%~1"
robocopy "%SKILL_SOURCE%" "%~1" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (echo ERROR: Could not copy skill to %~1& exit /b 8)
exit /b 0

:append_instructions
if not exist "%~1" type nul > "%~1"
findstr /L /C:"## Local requirements (document-reader)" "%~1" >nul
if errorlevel 1 (
  >> "%~1" echo.
  type "%~2" >> "%~1"
) else (echo Preserved document-reader instructions in %~nx1)
exit /b 0
