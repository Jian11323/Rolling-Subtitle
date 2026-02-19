@echo off
cd /d "%~dp0"

echo Abort failed merge...
git merge --abort 2>nul

echo Stash local changes...
git stash -u

echo Pull with rebase...
git pull --rebase origin main
if errorlevel 1 (
    echo.
    echo Rebase has conflicts. Fix conflicted files then run:
    echo   git add .
    echo   git rebase --continue
    echo   git push origin main
    echo   git stash pop
    pause
    exit /b 1
)

echo Push...
git push origin main
if errorlevel 1 (
    echo Push failed.
) else (
    echo Done.
)
echo Restore stashed changes...
git stash pop 2>nul
pause
