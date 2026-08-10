#!/bin/sh
# Prints the API key for one vendor. Claude Code's apiKeyHelper runs this and
# uses whatever it prints, so the tracked settings file only ever holds a path.
#
# Install:
#   cp vendor-key.example.sh ~/.claude/qwen-key.sh   (or kimi-key.sh)
#   chmod 700 ~/.claude/qwen-key.sh
#   then replace the placeholder below with your real key.
#
# Keep this file OUTSIDE any git repository.

echo "sk-REPLACE-WITH-YOUR-VENDOR-KEY"
