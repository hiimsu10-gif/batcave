#!/bin/bash
# One-step setup of the Rekordbox connector for Claude Desktop (macOS).
#
#   curl -fsSL https://raw.githubusercontent.com/hiimsu10-gif/batcave/main/rekordbox-mcp/install.sh | bash
#
# Safe to run again: it updates the code and re-checks the settings.
set -euo pipefail

REPO="hiimsu10-gif/batcave"
BRANCHES="${RBMCP_BRANCH:-main claude/festive-pascal-yrjn69}"
INSTALL_DIR="${RBMCP_INSTALL_DIR:-$HOME/rekordbox-mcp}"
CLAUDE_CONFIG="${RBMCP_CLAUDE_CONFIG:-$HOME/Library/Application Support/Claude/claude_desktop_config.json}"

bold() { printf '\n\033[1m%s\033[0m\n' "$1"; }
ok() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() {
  printf '\n  \033[31m✗ %s\033[0m\n' "$1"
  printf '\n  Nothing in Claude Desktop was changed. Copy everything above and paste it to Claude.\n\n'
  exit 1
}

if [[ "$(uname)" != "Darwin" && -z "${RBMCP_ALLOW_ANY_OS:-}" ]]; then
  fail "This installer is for macOS."
fi

bold "1/5  Finding uv"
UV="$(command -v uv || true)"
for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
  if [[ -z "$UV" && -x "$candidate" ]]; then
    UV="$candidate"
  fi
done
if [[ -z "$UV" ]]; then
  echo "  uv isn't installed yet. Installing it..."
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
  UV="$HOME/.local/bin/uv"
  [[ -x "$UV" ]] || fail "Couldn't install uv."
fi
ok "uv found at $UV"

bold "2/5  Downloading the connector"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
SRC=""
for branch in $BRANCHES; do
  if curl -fsSL "https://github.com/$REPO/archive/refs/heads/$branch.tar.gz" -o "$TMP/src.tar.gz" 2>/dev/null; then
    tar -xzf "$TMP/src.tar.gz" -C "$TMP"
    found="$(find "$TMP" -maxdepth 2 -type d -name rekordbox-mcp | head -n 1)"
    if [[ -n "$found" && -f "$found/pyproject.toml" ]]; then
      SRC="$found"
      break
    fi
    rm -rf "$TMP"/batcave-* "$TMP/src.tar.gz"
  fi
done
[[ -n "$SRC" ]] || fail "Couldn't download the connector from GitHub. Check your internet connection."
if [[ -d "$INSTALL_DIR" ]] && [[ -n "$(ls -A "$INSTALL_DIR")" ]] \
  && ! grep -qs 'name = "rekordbox-mcp"' "$INSTALL_DIR/pyproject.toml"; then
  fail "$INSTALL_DIR already exists and isn't the connector. Rename that folder and run this again."
fi
mkdir -p "$INSTALL_DIR"
# Replace the code but keep the installed Python environment, so re-runs are quick.
find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 ! -name .venv -exec rm -rf {} +
cp -R "$SRC"/. "$INSTALL_DIR"/
ok "Installed to $INSTALL_DIR"

bold "3/5  Checking your Rekordbox library (the first time takes a minute)"
if ! "$UV" --directory "$INSTALL_DIR" run --quiet rekordbox-mcp --check; then
  fail "The connector couldn't open your Rekordbox library."
fi

bold "4/5  Looking for your Dropbox 'New Downloads' folder"
DOWNLOADS=""
for candidate in "$HOME"/Library/CloudStorage/Dropbox*/"New Downloads" "$HOME"/Dropbox*/"New Downloads"; do
  if [[ -z "$DOWNLOADS" && -d "$candidate" ]]; then
    DOWNLOADS="$candidate"
  fi
done
if [[ -n "$DOWNLOADS" ]]; then
  ok "Found $DOWNLOADS"
else
  echo "  Not found. That's fine: you can tell Claude the folder when you scan downloads."
fi

bold "5/5  Adding the connector to Claude Desktop"
PYTHON="$INSTALL_DIR/.venv/bin/python"
[[ -x "$PYTHON" ]] || fail "The connector's Python environment is missing."
if [[ -f "$CLAUDE_CONFIG" ]]; then
  BACKUP="$CLAUDE_CONFIG.backup-$(date +%Y%m%d-%H%M%S)"
  cp "$CLAUDE_CONFIG" "$BACKUP"
  ok "Backed up your current Claude settings to: $BACKUP"
fi
"$PYTHON" - "$CLAUDE_CONFIG" "$UV" "$INSTALL_DIR" "$DOWNLOADS" <<'PY' || fail "Couldn't update the Claude Desktop settings."
import json, sys
from pathlib import Path

config_path, uv, install_dir, downloads = sys.argv[1:5]
path = Path(config_path)
text = path.read_text() if path.exists() else ""
try:
    config = json.loads(text) if text.strip() else {}
except json.JSONDecodeError as exc:
    sys.exit(f"  Your Claude settings file isn't valid JSON ({exc}), so it was left alone.")
if not isinstance(config, dict):
    sys.exit("  Your Claude settings file has an unexpected format, so it was left alone.")

server = {"command": uv, "args": ["--directory", install_dir, "run", "--quiet", "rekordbox-mcp"]}
if downloads:
    server["env"] = {"REKORDBOX_MCP_DOWNLOADS_DIR": downloads}
servers = config.setdefault("mcpServers", {})
action = "Updated" if "rekordbox" in servers else "Added"
servers["rekordbox"] = server

path.parent.mkdir(parents=True, exist_ok=True)
tmp = path.with_suffix(".tmp")
tmp.write_text(json.dumps(config, indent=2) + "\n")
tmp.replace(path)
print(f"  \033[32m✓\033[0m {action} 'rekordbox' in {path}")
PY

bold "All set!"
cat <<EOF
  Last step: fully quit Claude Desktop (click it, then press ⌘Q) and open it again.
  Then ask Claude:  "Check my Rekordbox connection."

EOF
