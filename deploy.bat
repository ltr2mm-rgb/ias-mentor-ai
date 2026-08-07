@echo off
setlocal enableextensions
cd /d "%~dp0"

REM ============================================================
REM   One-click deploy for IAS Mentor AI
REM   First run: paste your GitHub token once. It is saved
REM   locally and reused automatically every time after that.
REM   Pushes to GitHub, then deploys to Cloud Run (aimentora.in).
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
echo Code pushed to GitHub. Now deploying to Cloud Run (aimentora.in)...
where gcloud >nul 2>nul
if errorlevel 1 goto nogcloud
call gcloud run deploy aivora --source . --region asia-south1 --project aivora-production --update-env-vars PILOT_DIGEST_KEY=HEt9AWMnzVKmBZplZhizGiXqCZz2LYzv --quiet
if errorlevel 1 goto deployfailed
echo.
echo ============================================
echo   DONE. aimentora.in is now LIVE with your changes.
echo ============================================
echo.
pause
goto end

:nogcloud
echo.
echo ============================================
echo   Your code IS on GitHub. It is NOT live yet.
echo.
echo   The Cloud Run deploy did not run because gcloud
echo   (Google Cloud SDK) is not installed on this PC.
echo.
echo   There is no second way to deploy. Cloud Run builds
echo   from the folder on THIS disk, so deploying from
echo   anywhere else would ship different code.
echo.
echo   To finish: install the Google Cloud SDK from
echo   cloud.google.com/sdk, run  gcloud auth login,
echo   then run deploy.bat again.
echo ============================================
echo.
pause
goto end

:deployfailed
echo.
echo ============================================
echo   Cloud Run deploy FAILED (see the error above).
echo   Your live site keeps running the previous version.
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
