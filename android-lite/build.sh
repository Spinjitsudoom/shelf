#!/usr/bin/env bash
# Build (and with --install, install) Shelf Lite, the lightweight Android app (Shelf's web app
# in a small shell), without Gradle: aapt2, javac, d8, zipalign and apksigner from the Android
# SDK. Set ANDROID_HOME and JAVA_HOME, or the defaults under ~/.local/share/android-build are used.
#   bash android-lite/build.sh [--install [device-serial]]
# It installs as app.shelf.lite, beside Shelf (the native app, app.shelf). The Java code keeps
# its app.shelf package; only the installed package name changes.
set -euo pipefail
cd "$(dirname "$0")"
TOOLS="${ANDROID_BUILD:-$HOME/.local/share/android-build}"
export JAVA_HOME="${JAVA_HOME:-$TOOLS/jdk}"
export PATH="$JAVA_HOME/bin:$PATH"
SDK="${ANDROID_HOME:-$TOOLS/sdk}"
BT="$SDK/build-tools/${BUILD_TOOLS:-34.0.0}"
JAR="$SDK/platforms/android-34/android.jar"
APP=app/src/main
OUT=build
VERSION_CODE="${VERSION_CODE:-5}"   # releases set these from the version tag
VERSION_NAME="${VERSION_NAME:-0.5}"

rm -rf "$OUT" && mkdir -p "$OUT/classes" "$OUT/dex" "$OUT/gen"
"$BT/aapt2" compile --dir "$APP/res" -o "$OUT/res.zip"
"$BT/aapt2" link -o "$OUT/unsigned.apk" -I "$JAR" --manifest "$APP/AndroidManifest.xml" -A "$APP/assets" \
  --min-sdk-version 21 --target-sdk-version 34 --version-code $VERSION_CODE --version-name $VERSION_NAME \
  --rename-manifest-package app.shelf.lite --java "$OUT/gen" "$OUT/res.zip"
"$JAVA_HOME/bin/javac" -nowarn -Xlint:-options -source 8 -target 8 -encoding UTF-8 -classpath "$JAR" \
  -d "$OUT/classes" $(find "$APP/java" "$OUT/gen" -name '*.java')
"$BT/d8" --release --min-api 21 --lib "$JAR" --output "$OUT/dex" $(find "$OUT/classes" -name '*.class')
(cd "$OUT/dex" && zip -q -j ../unsigned.apk classes.dex)
"$BT/zipalign" -f -p 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"

KEY="$TOOLS/debug.keystore" # a personal signing key, kept outside the project
if [ ! -f "$KEY" ]; then
  "$JAVA_HOME/bin/keytool" -genkeypair -keystore "$KEY" -storepass android -keypass android -alias shelf \
    -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Shelf" >/dev/null 2>&1
fi
"$BT/apksigner" sign --ks "$KEY" --ks-pass pass:android --key-pass pass:android --out "$OUT/shelf.apk" "$OUT/aligned.apk"
echo "Built $(pwd)/$OUT/shelf.apk"

if [ "${1:-}" = "--install" ]; then
  adb ${2:+-s "$2"} install -r "$OUT/shelf.apk"
  adb ${2:+-s "$2"} shell am start -n app.shelf/.MainActivity
fi
