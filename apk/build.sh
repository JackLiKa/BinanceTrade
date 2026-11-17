#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SDK="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
BUILD_TOOLS="${BUILD_TOOLS:-$SDK/build-tools/36.0.0}"
# Prefer android-34 (declared target); fall back to whatever newer platform exists.
if [ -n "${PLATFORM:-}" ]; then
  :
elif [ -f "$SDK/platforms/android-34/android.jar" ]; then
  PLATFORM="$SDK/platforms/android-34/android.jar"
else
  PLATFORM="$(find "$SDK/platforms" -maxdepth 2 -name android.jar | sort -V | tail -1)"
fi
# JDK: explicit $JDK wins; macOS java_home next; otherwise the javac on PATH.
if [ -z "${JDK:-}" ]; then
  JDK="$(/usr/libexec/java_home -v 21 2>/dev/null || /usr/libexec/java_home 2>/dev/null || true)"
fi
if [ -n "$JDK" ] && [ -x "$JDK/bin/javac" ]; then
  JAVAC="$JDK/bin/javac"
  KEYTOOL="$JDK/bin/keytool"
elif command -v javac >/dev/null 2>&1; then
  JAVAC="$(command -v javac)"
  KEYTOOL="$(command -v keytool || true)"
else
  echo "no javac found; set JDK or install a JDK 17+" >&2
  exit 1
fi
OUT="$HERE/build"
APK="$HERE/gridtrade.apk"
KEYSTORE="$HERE/gridtrade.jks"
VERSION_CODE="${VERSION_CODE:-2}"
VERSION_NAME="${VERSION_NAME:-0.2.0}"

for tool in aapt2 d8 zipalign apksigner; do
  found=""
  for cand in "$BUILD_TOOLS/$tool" "$BUILD_TOOLS/$tool.exe" "$BUILD_TOOLS/$tool.bat" "$BUILD_TOOLS/$tool.cmd"; do
    if [ -f "$cand" ]; then found="$cand"; break; fi
  done
  if [ -z "$found" ]; then
    echo "missing $BUILD_TOOLS/$tool (Windows: expect .exe/.bat)" >&2
    exit 1
  fi
  case "$tool" in
    aapt2) AAPT2="$found" ;;
    d8) D8="$found" ;;
    zipalign) ZIPALIGN="$found" ;;
    apksigner) APKSIGNER="$found" ;;
  esac
done
if [ ! -f "$PLATFORM" ]; then
  echo "missing $PLATFORM" >&2
  exit 1
fi

rm -rf "$OUT"
mkdir -p "$OUT/classes" "$OUT/dex" "$OUT/gen/com/gridtrade/panel"

# Build-time config: apk/.env (gitignored) -> BuildConfig.java
ENV_FILE="$HERE/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi
SERVER_URL="${SERVER_URL:-http://10.0.2.2:8000}"
TOKEN_VALUE="${TOKEN:-}"
SERVER_URL="${SERVER_URL%\"}"; SERVER_URL="${SERVER_URL#\"}"
TOKEN_VALUE="${TOKEN_VALUE%\"}"; TOKEN_VALUE="${TOKEN_VALUE#\"}"
cat > "$OUT/gen/com/gridtrade/panel/BuildConfig.java" <<JAVA
package com.gridtrade.panel;

final class BuildConfig {
    static final String DEFAULT_SERVER = "$SERVER_URL";
    static final String DEFAULT_TOKEN = "$TOKEN_VALUE";

    private BuildConfig() {}
}
JAVA

echo "== resources"
"$AAPT2" compile --dir "$HERE/res" -o "$OUT/res.zip"
"$AAPT2" link \
  -o "$OUT/unsigned.apk" \
  -I "$PLATFORM" \
  --manifest "$HERE/AndroidManifest.xml" \
  "$OUT/res.zip" \
  --min-sdk-version 26 \
  --target-sdk-version 34 \
  --version-code "$VERSION_CODE" \
  --version-name "$VERSION_NAME"

echo "== compile"
"$JAVAC" --release 17 -encoding UTF-8 -Xlint:-options -classpath "$PLATFORM" -d "$OUT/classes" \
  $(find "$HERE/src" "$OUT/gen" -name '*.java')

echo "== dex"
"$D8" --lib "$PLATFORM" --min-api 26 --output "$OUT/dex" \
  $(find "$OUT/classes" -name '*.class')

cp "$OUT/unsigned.apk" "$OUT/unaligned.apk"
if command -v zip >/dev/null 2>&1; then
  (cd "$OUT/dex" && zip -q "$OUT/unaligned.apk" classes.dex)
else
  # Git Bash on Windows has no zip: append with Python's zipfile instead.
  python - "$OUT/unaligned.apk" "$OUT/dex/classes.dex" <<'PY'
import sys, zipfile
apk, dex = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(apk, "a", zipfile.ZIP_DEFLATED) as zf:
    zf.write(dex, "classes.dex")
PY
fi

echo "== align"
"$ZIPALIGN" -f 4 "$OUT/unaligned.apk" "$OUT/aligned.apk"

if [ ! -f "$KEYSTORE" ]; then
  echo "== keystore"
  "$KEYTOOL" -genkeypair \
    -keystore "$KEYSTORE" \
    -alias gridtrade \
    -keyalg RSA \
    -keysize 2048 \
    -validity 10000 \
    -storepass gridtrade \
    -keypass gridtrade \
    -dname "CN=Gridtrade, OU=Research, O=Local, S=Local, C=US" >/dev/null 2>&1
fi

echo "== sign"
"$APKSIGNER" sign \
  --ks "$KEYSTORE" \
  --ks-key-alias gridtrade \
  --ks-pass pass:gridtrade \
  --key-pass pass:gridtrade \
  --out "$APK" \
  "$OUT/aligned.apk"

"$APKSIGNER" verify --print-certs "$APK" | head -5
echo "built $APK"
