@echo off
cd /d "%~dp0"

git add LICENSE
git commit -m "Add Chinese translation to LICENSE"
if errorlevel 1 (
    echo Commit failed. Maybe nothing to commit or not a git repo.
    pause
    exit /b 1
)

call git_push.bat
