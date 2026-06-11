#!/usr/bin/env bash
set -euo pipefail

cd /root/sakura/learn/deep
PYTHONPATH=industry_information_assistant/backend/app \
industry_information_assistant/backend/.venv/bin/python \
ivfpq_adc_benchmark/benchmark_ivfpq_adc.py --rebuild "$@"

