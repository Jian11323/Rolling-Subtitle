@echo off
cd /d "%~dp0"
set REPO=https://github.com/crazy786781/Rolling-Subtitle.git

echo [1] Git config...
git config --global user.name "crazy786781"
git config --global user.email "mazhiyuan401@163.com"

if not exist ".git" (
    echo [2] Init repo...
    git init
)

echo [3] Clean non-core from repo...
git rm --cached build.bat build_debug.bat build_debug_run.bat 2>nul
git rm --cached build_lite.spec build_lite_debug.spec 2>nul
git rm --cached "GITHUB_上传说明.md" 2>nul
where bash >nul 2>&1 && if exist "%~dp0cleanup_only.sh" bash "%~dp0cleanup_only.sh" 2>nul

echo [4] Add files...
git add -A
git status --short
echo.
pause

echo [5] Commit...
git commit -m "Update core files"
if errorlevel 1 echo No changes to commit.

echo [6] Push...
git remote get-url origin >nul 2>&1
if errorlevel 1 git remote add origin %REPO%
if not errorlevel 1 git remote set-url origin %REPO%
git branch -M main
git push -u origin main
if errorlevel 1 (
    echo Push failed. Try VPN or run again later.
) else (
    echo Done: https://github.com/crazy786781/Rolling-Subtitle
)
pause
