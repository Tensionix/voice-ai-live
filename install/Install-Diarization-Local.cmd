@echo off
rem Speaker separation without a HuggingFace key: sherpa-onnx (CPU) + two ONNX models, about 65 MB.
rem It runs only with a speaker count given by the user; see system_core\providers\diarization_sherpa.py.
chcp 65001 >nul
setlocal
set "ROOT=%~dp0.."
set "PYEXE=%ROOT%\runtime\python.exe"
if not exist "%PYEXE%" (
  echo [ERROR] Portable Python was not found: %PYEXE%
  echo Run Build_Portable_Env.cmd first.
  set "RC=2"
  goto DONE
)
set "PYTHONUTF8=1"
"%PYEXE%" "%~dp0Install-Diarization-Local.py"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [Audion Voice AI] Speaker separation install did not complete. Exit code: %RC%
)

:DONE
call "%~dp0_pause_if_needed.cmd"
endlocal & exit /b %RC%
