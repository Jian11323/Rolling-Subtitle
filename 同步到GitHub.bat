@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
if exist ".git\MERGE_HEAD" (
    echo Finishing unfinished merge...
    git commit -m "Merge remote main"
    if errorlevel 1 (
        echo Merge has conflicts. Resolve them then run: git add . ^&^& git commit -m "Merge"
        pause
        exit /b 1
    )
    for /f "delims=" %%i in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "BR=%%i"
    if "!BR!"=="HEAD" (
        echo Merge was in detached HEAD. Moving to main...
        for /f "delims=" %%j in ('git rev-parse HEAD 2^>nul') do set "MC=%%j"
        git stash -u
        git checkout main
        git merge !MC! -m "Integrate merge"
        git stash pop 2>nul
    )
)
for /f "delims=" %%i in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "BR=%%i"
if "!BR!"=="HEAD" (
    echo Detached HEAD detected. Merging into main...
    for /f "delims=" %%j in ('git rev-parse HEAD 2^>nul') do set "MC=%%j"
    git stash -u
    git checkout main
    git merge !MC! -m "Integrate merge"
    git pull origin main
    git push origin main
    git stash pop 2>nul
    goto :done
)
git checkout main 2>nul
echo Adding and committing local changes...
git add -A
git commit -m "Update"
if errorlevel 1 echo No changes to commit.
git pull origin main
git push origin main
:done
echo Done.
pause
