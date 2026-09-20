#!/usr/bin/env sh
# Rebuild assets/css/tailwind.css (run after adding new Tailwind classes to the HTML/JS).
# Requires Node.js. No project dependencies are installed into the repo.
set -e
cd "$(dirname "$0")"
npx --yes tailwindcss@3.4.17 -c tailwind.config.js -i assets/css/tailwind.src.css -o assets/css/tailwind.css --minify
echo "assets/css/tailwind.css rebuilt"
