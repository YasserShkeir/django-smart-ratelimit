#!/bin/bash
# Script to run commands with virtual environment activated
# Usage: ./run_with_venv.sh <command>

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtual environment
source venv/bin/activate

# Run the command with all arguments
exec "$@"
