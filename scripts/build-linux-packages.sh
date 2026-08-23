#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$("$ROOT/.venv/bin/python" "$ROOT/scripts/version.py")
PROJECT_URL=$("$ROOT/.venv/bin/python" "$ROOT/scripts/external-links.py" project)
ARCH=${NFPM_ARCH:-amd64}
case "$ARCH" in
  amd64) RPM_ARCH=x86_64 ;;
  arm64) RPM_ARCH=aarch64 ;;
  *) RPM_ARCH=$ARCH ;;
esac
OUTPUT="$ROOT/dist/packages"

mkdir -p "$OUTPUT"
ELSEWISE_VERSION="$VERSION" PROJECT_URL="$PROJECT_URL" NFPM_ARCH="$ARCH" nfpm package \
  --config "$ROOT/packaging/linux/nfpm.yaml" \
  --packager deb \
  --target "$OUTPUT/elsewise_${VERSION}_${ARCH}.deb"
ELSEWISE_VERSION="$VERSION" PROJECT_URL="$PROJECT_URL" NFPM_ARCH="$ARCH" nfpm package \
  --config "$ROOT/packaging/linux/nfpm.yaml" \
  --packager rpm \
  --target "$OUTPUT/elsewise-${VERSION}-1.${RPM_ARCH}.rpm"

APPDIR="$ROOT/build/appimage/Elsewise.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/opt" "$APPDIR/usr/bin" "$APPDIR/usr/share/applications"
cp -a "$ROOT/dist/frozen/Elsewise" "$APPDIR/usr/opt/elsewise"
cp "$ROOT/packaging/linux/AppRun" "$APPDIR/AppRun"
cp "$ROOT/packaging/linux/elsewise.desktop" "$APPDIR/elsewise.desktop"
cp "$ROOT/packaging/generated/elsewise.png" "$APPDIR/elsewise.png"
cp "$ROOT/packaging/linux/elsewise.desktop" "$APPDIR/usr/share/applications/elsewise.desktop"
ln -s ../opt/elsewise/elsewise "$APPDIR/usr/bin/elsewise"
ln -s ../opt/elsewise/elsewise-gui "$APPDIR/usr/bin/elsewise-gui"
chmod +x "$APPDIR/AppRun"
ARCH=x86_64 appimagetool "$APPDIR" "$OUTPUT/Elsewise-${VERSION}-x86_64.AppImage"
