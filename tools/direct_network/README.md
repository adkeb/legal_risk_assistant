# Direct Network Rules

Use these rules before dependency or model downloads that must avoid VPN/proxy traffic.

```bash
source /root/sakura/learn/deep/tools/direct_network/direct_env.sh
env | grep -Ei 'proxy|PIP_CONFIG_FILE|NO_PROXY'
```

Expected behavior:

- `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` are unset.
- `NO_PROXY=*` and `no_proxy=*`.
- `PIP_CONFIG_FILE` points to this folder's `pip.conf`.
- pip uses `https://pypi.org/simple` directly.

