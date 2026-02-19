@echo off
cd /d "%~dp0"

git add LICENSE README.md git_commit_license_and_push.bat
git status --short
git commit -m "Add Chinese translation to LICENSE, update README, add helper script"
if errorlevel 1 (
    echo Commit failed. Check above. If "nothing to commit", all changes may already be committed.
    pause
    exit /b 1
)

call git_push.bat
