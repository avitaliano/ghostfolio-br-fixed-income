#!/bin/sh
# Run the test suite in the pinned Python image (host Python may be older).
exec docker run --rm -v "$(cd "$(dirname "$0")" && pwd)":/src:ro -w /src -e PYTHONDONTWRITEBYTECODE=1 python:3.13.18-alpine python -m unittest "$@"
