#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="/Users/apple/Documents/Claude/good-idea"
SOURCE_PLIST="$PROJECT_ROOT/scripts/com.songhai.goodidea.maintenance.plist"
SOURCE_RUNNER="$PROJECT_ROOT/scripts/run-maintenance.sh"
TARGET_PLIST="/Users/apple/Library/LaunchAgents/com.songhai.goodidea.maintenance.plist"
RUNTIME_DIR="/Users/apple/.local/share/goodidea-maintenance"
TARGET_RUNNER="$RUNTIME_DIR/run-maintenance.sh"
DOMAIN="gui/501"
LABEL="com.songhai.goodidea.maintenance"

[[ -f "$SOURCE_PLIST" ]] || { print -u2 "Missing $SOURCE_PLIST"; exit 2; }
[[ -f "$SOURCE_RUNNER" ]] || { print -u2 "Missing $SOURCE_RUNNER"; exit 2; }
[[ "$TARGET_PLIST" == "/Users/apple/Library/LaunchAgents/com.songhai.goodidea.maintenance.plist" ]] || exit 2
[[ "$TARGET_RUNNER" == "/Users/apple/.local/share/goodidea-maintenance/run-maintenance.sh" ]] || exit 2
/usr/bin/plutil -lint "$SOURCE_PLIST"
/bin/mkdir -p "$RUNTIME_DIR"
/bin/cp "$SOURCE_RUNNER" "$TARGET_RUNNER"
/bin/chmod 755 "$TARGET_RUNNER"
/bin/cp "$SOURCE_PLIST" "$TARGET_PLIST"
/bin/launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
/bin/launchctl bootstrap "$DOMAIN" "$TARGET_PLIST"
/bin/launchctl print "$DOMAIN/$LABEL"
