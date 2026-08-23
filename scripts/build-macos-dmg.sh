#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$("$ROOT/.venv/bin/python" "$ROOT/scripts/version.py")
ARCH=$(uname -m)
STAGE="$ROOT/build/dmg"
OUTPUT="$ROOT/dist/packages/Elsewise-${VERSION}-macOS-${ARCH}.dmg"

rm -rf "$STAGE"
mkdir -p "$STAGE" "$ROOT/dist/packages"
cp -a "$ROOT/dist/frozen/Elsewise.app" "$STAGE/Elsewise.app"
ln -s /Applications "$STAGE/Applications"
rm -f "$OUTPUT"
hdiutil create -volname Elsewise -srcfolder "$STAGE" -ov -format UDZO "$OUTPUT"
