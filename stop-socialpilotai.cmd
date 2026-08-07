@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-socialpilotai.ps1" %*
set "exitCode=%ERRORLEVEL%"
if not "%exitCode%"=="0" (
  echo.
  echo SocialPilotAI failed to stop. Review the error above.
  echo No secret values should be shared when requesting help.
  pause
)
exit /b %exitCode%
