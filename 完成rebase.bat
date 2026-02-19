@echo off
cd /d "%~dp0"
git checkout --theirs "SA、KMA-EEW-Fe Fix\korea_region_data.json"
git checkout --theirs "SA、KMA-EEW-Fe Fix\sa_region_data.json"
git add LICENSE README.md "SA、KMA-EEW-Fe Fix\korea_region_data.json" "SA、KMA-EEW-Fe Fix\sa_region_data.json"
git rebase --continue
git push origin main
git stash pop 2>nul
echo Done.
pause
