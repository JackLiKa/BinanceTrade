#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SDK="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
BUILD_TOOLS="${BUILD_TOOLS:-$SDK/build-tools/36.0.0}"
PLATFORM="${PLATFORM:-$SDK/platforms/android-34/android.jar}"
JDK="$(/usr/libexec/java_home -v 21 2>/dev/null || /usr/libexec/java_home)"
JAVAC="$JDK/bin/javac"
KEYTOOL="$JDK/bin/keytool"
OUT="$HERE/build"
APK="$HERE/gridtrade.apk"
KEYSTORE="$HERE/gridtrade.jks"

for tool in aapt2 d8 zipalign apksigner; do
  if [ ! -x "$BUILD_TOOLS/$tool" ]; then
    echo "missing $BUILD_TOOLS/$tool" >&2
    exit 1
  fi
done
if [ ! -f "$PLATFORM" ]; then
  echo "missing $PLATFORM" >&2
  exit 1
fi

rm -rf "$OUT"
mkdir -p "$OUT/classes" "$OUT/dex"

echo "== resources"
"$BUILD_TOOLS/aapt2" compile --dir "$HERE/res" -o "$OUT/res.zip"
"$BUILD_TOOLS/aapt2" link \
  -o "$OUT/unsigned.apk" \
  -I "$PLATFORM" \
  --manifest "$HERE/AndroidManifest.xml" \
  "$OUT/res.zip" \
  --min-sdk-version 26 \
  --target-sdk-version 34 \
  --version-code 1 \
  --version-name 0.1.0

echo "== compile"
"$JAVAC" --release 17 -Xlint:-options -classpath "$PLATFORM" -d "$OUT/classes" \
  $(find "$HERE/src" -name '*.java')

echo "== dex"
"$BUILD_TOOLS/d8" --lib "$PLATFORM" --min-api 26 --output "$OUT/dex" \
  $(find "$OUT/classes" -name '*.class')

cp "$OUT/unsigned.apk" "$OUT/unaligned.apk"
(cd "$OUT/dex" && zip -q "$OUT/unaligned.apk" classes.dex)

echo "== align"
"$BUILD_TOOLS/zipalign" -f 4 "$OUT/unaligned.apk" "$OUT/aligned.apk"

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
"$BUILD_TOOLS/apksigner" sign \
  --ks "$KEYSTORE" \
  --ks-key-alias gridtrade \
  --ks-pass pass:gridtrade \
  --key-pass pass:gridtrade \
  --out "$APK" \
  "$OUT/aligned.apk"

"$BUILD_TOOLS/apksigner" verify --print-certs "$APK" | head -5
echo "built $APK"
