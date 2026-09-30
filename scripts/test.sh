#!/bin/sh
# Runs lint and tests in the python:3.13 image, as CI does.
set -eu
cd "$(dirname "$0")/.."
docker run --rm -v "$PWD":/work -w /work python:3.13 sh -c '
  pip install -q -r requirements_test.txt &&
  ruff check . &&
  ruff format --check . &&
  pytest -q
'
