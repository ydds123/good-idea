#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="/Users/apple/Documents/Claude/good-idea"
SOURCE_PLIST="$PROJECT_ROOT/scripts/com.songhai.goodidea.maintenance.plist"
TARGET_PLIST="/Users/apple/Library/LaunchAgents/com.songhai.goodidea.maintenance.plist"
DOMAIN="gui/501"
LABEL="com.songhai.goodidea.maintenance"

[[ -f "$SOURCE_PLIST" ]] || { print -u2 "Missing $SOURCE_PLIST"; exit 2; }
[[ "$TARGET_PLIST" == "/Users/apple/Library/LaunchAgents/com.songhai.goodidea.maintenance.plist" ]] || exit 2
/usr/bin/plutil -lint "$SOURCE_PLIST"
/bin/cp "$SOURCE_PLIST" "$TARGET_PLIST"
/bin/launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
/bin/launchctl bootstrap "$DOMAIN" "$TARGET_PLIST"
/bin/launchctl print "$DOMAIN/$LABEL"
