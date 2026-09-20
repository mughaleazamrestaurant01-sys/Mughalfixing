@echo off
REM Rebuild assets\css\tailwind.css (run after adding new Tailwind classes to the HTML/JS).
REM Requires Node.js (https://nodejs.org). Nothing is installed into the repo.
cd /d "%~dp0"
call npx --yes tailwindcss@3.4.17 -c tailwind.config.js -i assets\css\tailwind.src.css -o assets\css\tailwind.css --minify
if errorlevel 1 (
  echo Build failed. Make sure Node.js is installed.
  exit /b 1
)
echo assets\css\tailwind.css rebuilt
