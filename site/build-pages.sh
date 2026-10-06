#!/usr/bin/env bash
# Build the static (GitHub Pages) version of the site and publish it to the
# repo root, replacing the legacy index.html + assets/. Then commit and push.
#
# Usage: ./site/build-pages.sh   (from anywhere; content edits in
# site/backend/content/*.json are baked in at build time — commit those first)
set -euo pipefail

SITE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SITE_DIR/.." && pwd)"

echo "==> Building static frontend (content baked in)..."
(cd "$SITE_DIR/frontend" && npm run build:pages)

echo "==> Publishing dist/ to repo root..."
rm -rf "$REPO_ROOT/assets"
cp -r "$SITE_DIR/frontend/dist/assets" "$REPO_ROOT/assets"
cp "$SITE_DIR/frontend/dist/index.html" "$REPO_ROOT/index.html"

cd "$REPO_ROOT"
git add index.html assets/
if git diff --cached --quiet; then
  echo "No changes to publish."
  exit 0
fi

git -c user.name="Carter P." -c user.email="pattoncarter@yahoo.com" commit -m "pages: rebuild static site from current content"
git push origin master
echo "Done. GitHub Pages will serve the new build shortly."
