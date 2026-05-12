#!/bin/bash
set -e

# One-time setup
uv python install 3.12
uv venv --python 3.12 .venv-cogames
uv pip install cogames anthropic openai --python .venv-cogames/bin/python
uv pip install -e . --python .venv-cogames/bin/python

# Auth & status
.venv-cogames/bin/cogames auth set-token $COGAMES_TOKEN
.venv-cogames/bin/cogames auth status
.venv-cogames/bin/cogames matches
