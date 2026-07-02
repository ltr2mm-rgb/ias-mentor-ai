@echo off
setlocal enableextensions
cd /d "%~dp0"

REM ============================================================
REM   One-click deploy for IAS Mentor AI
REM   First run: paste your GitHub token once. It is saved
REM   locally and reused automatically every time after that.
REM   Render auto-redeploys aimentora.in a few minutes later.
REM ============================================================

set "TKFILE=%~dp0.gh_token"

if exist "%TKFILE%" goto haveToken

echo ============================================
echo   First-time setup
echo ============================================
echo.
echo Paste your GitHub token below and press Enter.
echo It is saved on THIS PC only and is never uploaded.
echo Tip: right-click in this window to paste.
echo.
set "TOKEN="
set /p TOKEN=GitHub token:
if not defined TOKEN goto noToken
> "%TKFILE%" echo %TOKEN%
echo.
echo Token saved. From now on, deploying is just a double-click.
goto push

:haveToken
set /p TOKEN=<"%TKFILE%"
echo Using your saved GitHub token.
goto push

:push
echo.
echo Pushing your latest code to GitHub...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0push_to_github.ps1" -Token "%TOKEN%"
if errorlevel 1 goto failed
echo.
echo ============================================
echo   Done. Render is auto-redeploying now.
echo   aimentora.in updates in about 3-5 minutes.
echo ============================================
echo.
pause
goto end

:noToken
echo.
echo No token entered. Just run deploy.bat again.
pause
goto end

:failed
echo.
echo Deploy failed. If your token expired, delete the file
echo  .gh_token  in this folder, then run deploy.bat again.
pause
goto end

:end
endlocal
