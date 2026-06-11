#!/usr/bin/env bash
# Direct-download environment for dependency/model downloads.
#
# Source this file before running pip, curl, git, huggingface-cli, or model
# download commands when downloads must bypass local VPN/proxy settings.

unset HTTP_PROXY
unset HTTPS_PROXY
unset ALL_PROXY
unset http_proxy
unset https_proxy
unset all_proxy

export NO_PROXY="*"
export no_proxy="*"

export PIP_CONFIG_FILE="/root/sakura/learn/deep/tools/direct_network/pip.conf"
export PIP_NO_PROXY="*"

# Keep Hugging Face/model downloads off proxy-aware helpers as well.
export HF_HUB_DISABLE_TELEMETRY=1

