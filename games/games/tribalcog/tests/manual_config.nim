## Manual config smoke script for validation and help output.

import std/strformat
import config

echo "Loading configuration from environment."
let cfg = loadConfig()

echo ""
echo "=== Validation ==="
let errors = cfg.validate()
if errors.len == 0:
  echo "Configuration is valid."
else:
  echo "Validation errors:"
  for err in errors:
    echo fmt"  {err.field}: {err.message}"

echo ""
echo "=== JSON Serialization ==="
echo cfg.toJsonString()

echo ""
echo "=== Help Documentation ==="
echo cfg.help()
