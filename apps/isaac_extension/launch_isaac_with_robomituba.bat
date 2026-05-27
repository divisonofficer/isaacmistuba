@echo off
setlocal

if not defined ROBOMITUBA_WINDOWS_REPO_ROOT (
  if not defined ROBOMITUBA_ROOT (
    set "ROBOMITUBA_WINDOWS_REPO_ROOT=\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba"
  ) else (
    set "ROBOMITUBA_WINDOWS_REPO_ROOT=%ROBOMITUBA_ROOT%"
  )
)
set "ROBOMITUBA_ROOT=%ROBOMITUBA_WINDOWS_REPO_ROOT%"
set "ROBOMITUBA_APPS=%ROBOMITUBA_ROOT%\apps"
set "ROBOMITUBA_EXTENSION_SRC=%ROBOMITUBA_APPS%\isaac_extension"
set "ROBOMITUBA_STANDALONE_SRC=%ROBOMITUBA_APPS%\isaac_standalone"
set "ROBOMITUBA_BRIDGE_SRC=%ROBOMITUBA_ROOT%\modules\robomituba_bridge\src"
set "ROBOMITUBA_CONVERTER_SRC=%ROBOMITUBA_ROOT%\modules\mitsuba_converter\src"
set "ROBOMITUBA_ASSETS_SRC=%ROBOMITUBA_ROOT%\assets"

if not defined ISAAC_SIM_BAT (
  if defined ISAAC_SIM_ROOT (
    set "ISAAC_SIM_BAT=%ISAAC_SIM_ROOT%\isaac-sim.bat"
  ) else (
    set "ISAAC_SIM_BAT=C:\isaac_sim_win\isaac-sim.bat"
  )
)

if not exist "%ISAAC_SIM_BAT%" (
  echo [robomituba] Could not find Isaac launcher:
  echo   %ISAAC_SIM_BAT%
  echo.
  echo Set ISAAC_SIM_ROOT or ISAAC_SIM_BAT first, for example:
  echo   set ISAAC_SIM_ROOT=C:\isaac_sim_win
  echo or
  echo   set ISAAC_SIM_BAT=C:\isaac_sim_win\isaac-sim.bat
  exit /b 1
)

echo [robomituba] Windows repo root: %ROBOMITUBA_ROOT%
echo [robomituba] Extension source: %ROBOMITUBA_EXTENSION_SRC%

set "LOCAL_EXTENSION_PARENT=%~dp0..\..\..\..\isaac_sim_win\extsUser"
set "LOCAL_EXTENSION_ROOT=%LOCAL_EXTENSION_PARENT%\isaac_extension"
if exist "C:\isaac_sim_win\extsUser" (
  set "LOCAL_EXTENSION_PARENT=C:\isaac_sim_win\extsUser"
  set "LOCAL_EXTENSION_ROOT=%LOCAL_EXTENSION_PARENT%\isaac_extension"
)
if not exist "%LOCAL_EXTENSION_PARENT%" mkdir "%LOCAL_EXTENSION_PARENT%"
echo [robomituba] Local extension root: %LOCAL_EXTENSION_ROOT%
set "LOCAL_RUNTIME_ROOT=C:\isaac_sim_win\robomituba_runtime"
set "LOCAL_REPO_MIRROR=%LOCAL_RUNTIME_ROOT%\repo"
set "ROBOMITUBA_LOCAL_REPO_ROOT=%LOCAL_REPO_MIRROR%"
set "LOCAL_APPS_ROOT=%LOCAL_REPO_MIRROR%\apps"
set "LOCAL_MODULES_ROOT=%LOCAL_REPO_MIRROR%\modules"
set "LOCAL_ASSETS_ROOT=%LOCAL_REPO_MIRROR%\assets"
set "LOCAL_STANDALONE_ROOT=%LOCAL_APPS_ROOT%\isaac_standalone"
set "LOCAL_BRIDGE_SRC=%LOCAL_MODULES_ROOT%\robomituba_bridge\src"
set "LOCAL_CONVERTER_SRC=%LOCAL_MODULES_ROOT%\mitsuba_converter\src"
if not exist "%LOCAL_RUNTIME_ROOT%" mkdir "%LOCAL_RUNTIME_ROOT%"
if not exist "%LOCAL_APPS_ROOT%" mkdir "%LOCAL_APPS_ROOT%"
if not exist "%LOCAL_MODULES_ROOT%" mkdir "%LOCAL_MODULES_ROOT%"
if not exist "%LOCAL_ASSETS_ROOT%" mkdir "%LOCAL_ASSETS_ROOT%"
echo [robomituba] Local runtime root: %LOCAL_RUNTIME_ROOT%

if exist "%LOCAL_EXTENSION_PARENT%\isaac_standalone" (
  if not exist "%LOCAL_EXTENSION_PARENT%\isaac_standalone\config\extension.toml" (
    echo [robomituba] Removing stale extsUser\isaac_standalone folder to avoid extension-loader warnings...
    rmdir /S /Q "%LOCAL_EXTENSION_PARENT%\isaac_standalone"
  )
)

robocopy "%ROBOMITUBA_EXTENSION_SRC%" "%LOCAL_EXTENSION_ROOT%" /MIR /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo [robomituba] Failed to sync extension from:
  echo   %ROBOMITUBA_EXTENSION_SRC%
  echo to
  echo   %LOCAL_EXTENSION_ROOT%
  exit /b 1
)
call :copy_extension_file "__init__.py"
call :copy_extension_file "README.md"
call :copy_extension_file "daemon_client.py"
call :copy_extension_file "extension.py"
call :copy_extension_file "ranger_mini_stage.py"
call :copy_extension_file "stage_capture.py"
call :copy_extension_file "ui_panel.py"
if exist "%ROBOMITUBA_EXTENSION_SRC%\config" (
  robocopy "%ROBOMITUBA_EXTENSION_SRC%\config" "%LOCAL_EXTENSION_ROOT%\config" /MIR /NFL /NDL /NJH /NJS /NP >nul
  if errorlevel 8 (
    echo [robomituba] Failed to sync config folder:
    echo   %ROBOMITUBA_EXTENSION_SRC%\config
    echo to
    echo   %LOCAL_EXTENSION_ROOT%\config
    exit /b 1
  )
)
if exist "%LOCAL_EXTENSION_ROOT%\ui_panel.py" (
  echo [robomituba] Synced ui_panel.py:
  dir /T:W "%LOCAL_EXTENSION_ROOT%\ui_panel.py"
)
robocopy "%ROBOMITUBA_STANDALONE_SRC%" "%LOCAL_STANDALONE_ROOT%" /MIR /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo [robomituba] Failed to sync isaac_standalone package from:
  echo   %ROBOMITUBA_STANDALONE_SRC%
  echo to
  echo   %LOCAL_STANDALONE_ROOT%
  exit /b 1
)
robocopy "%ROBOMITUBA_BRIDGE_SRC%" "%LOCAL_BRIDGE_SRC%" /MIR /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo [robomituba] Failed to sync robomituba_bridge sources from:
  echo   %ROBOMITUBA_BRIDGE_SRC%
  echo to
  echo   %LOCAL_BRIDGE_SRC%
  exit /b 1
)
robocopy "%ROBOMITUBA_CONVERTER_SRC%" "%LOCAL_CONVERTER_SRC%" /MIR /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo [robomituba] Failed to sync mitsuba_converter sources from:
  echo   %ROBOMITUBA_CONVERTER_SRC%
  echo to
  echo   %LOCAL_CONVERTER_SRC%
  exit /b 1
)
robocopy "%ROBOMITUBA_ASSETS_SRC%\robots\ranger_mini_v3" "%LOCAL_ASSETS_ROOT%\robots\ranger_mini_v3" /MIR /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo [robomituba] Failed to sync RangerMini assets from:
  echo   %ROBOMITUBA_ASSETS_SRC%\robots\ranger_mini_v3
  echo to
  echo   %LOCAL_ASSETS_ROOT%\robots\ranger_mini_v3
  exit /b 1
)
if exist "%LOCAL_STANDALONE_ROOT%\ranger_mini\robot.py" (
  echo [robomituba] Synced local RangerMini runtime:
  dir /T:W "%LOCAL_STANDALONE_ROOT%\ranger_mini\robot.py"
)

set "PYTHONPATH=%LOCAL_APPS_ROOT%;%LOCAL_BRIDGE_SRC%;%LOCAL_CONVERTER_SRC%;%PYTHONPATH%"

call "%ISAAC_SIM_BAT%" ^
  --ext-folder "%LOCAL_EXTENSION_PARENT%" ^
  --enable isaac_extension ^
  --/app/python/extraPaths/0="%LOCAL_APPS_ROOT%" ^
  --/app/python/extraPaths/1="%LOCAL_BRIDGE_SRC%" ^
  --/app/python/extraPaths/2="%LOCAL_CONVERTER_SRC%" ^
  %*
exit /b %ERRORLEVEL%

:copy_extension_file
set "SRC_FILE=%ROBOMITUBA_EXTENSION_SRC%\%~1"
set "DST_FILE=%LOCAL_EXTENSION_ROOT%\%~1"
if not exist "%SRC_FILE%" (
  echo [robomituba] Missing extension file:
  echo   %SRC_FILE%
  exit /b 1
)
copy /Y "%SRC_FILE%" "%DST_FILE%" >nul
if errorlevel 1 (
  echo [robomituba] Failed to copy extension file:
  echo   %SRC_FILE%
  echo to
  echo   %DST_FILE%
  exit /b 1
)
exit /b 0
