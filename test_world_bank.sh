#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

command -v uv >/dev/null || { echo 'Install uv before running this script.' >&2; exit 1; }
test -f tests/world_bank_data_annual_2024.pdf || { echo 'World Bank PDF fixture is missing.' >&2; exit 1; }

# Large CUDA wheels can need longer download timeouts.
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-600}"
export UV_HTTP_CONNECT_TIMEOUT="${UV_HTTP_CONNECT_TIMEOUT:-60}"
export UV_CONCURRENT_DOWNLOADS="${UV_CONCURRENT_DOWNLOADS:-2}"

echo 'Installing locked Python 3.12 and GPU dependencies...'
uv sync --locked

echo 'Running API, OCR-adapter, and workbook checks...'
uv run --no-sync pytest -q

echo 'Running real extraction on all 49 World Bank PDF pages...'
RUN_GPU_INTEGRATION=1 uv run --no-sync pytest tests/test_world_bank_integration.py -s -q

echo 'Results:'
echo "$PWD/tests/artifacts/world_bank_2024.md"
echo "$PWD/tests/artifacts/world_bank_2024.json"
