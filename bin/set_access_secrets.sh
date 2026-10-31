#!/usr/bin/env bash
#
# 写入 Cloudflare Access Service Token 相关的 4 个 GitHub Actions Repository Secrets。
#
# 这 4 个 Secret 由 .github/workflows/sync_monitors.yml 注入 collect job，
# sync_monitors.py 再按 ssh_host 的域名后缀选择对应区域的 Token。
#
# 用法：
#   bin/set_access_secrets.sh                     # 预演（默认，只校验取值与权限）
#   bin/set_access_secrets.sh --apply             # 真正写入
#   bin/set_access_secrets.sh --repo owner/name
#   bin/set_access_secrets.sh --token <PAT>
#   bin/set_access_secrets.sh --env-file <path>
#
# Token 需要具备管理仓库 Secret 的权限（以下二选一）：
#   * Fine-grained PAT：Repository permissions → Secrets: Read and write
#   * Classic PAT：repo scope
# 未显式传入 --token 时，依次读取 $GH_TOKEN、$GITHUB_TOKEN，
# 若本机安装了 gh CLI 且已登录，则回退到 `gh auth token`。
# 自测/企业版可通过 $GITHUB_API_URL 覆盖 API 根地址（默认 https://api.github.com）。
#
# 取值优先级：环境变量 > --env-file（默认仓库根目录的 .env）。
# 加密使用 GitHub 要求的 libsodium sealed box，依赖 python3 的 pynacl：
#   python3 -m pip install pynacl
#
set -euo pipefail

REPO="${REPO:-suwei8/UptimeRobot}"
MODE="dry-run"
TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
ENV_FILE=".env"

# 需要写入的 Secret 名称（与 README「SSH」小节保持一致）
SECRET_NAMES=(
  CF_ACCESS_ID_HHWPXH
  CF_ACCESS_SECRET_HHWPXH
  CF_ACCESS_ID_555606
  CF_ACCESS_SECRET_555606
)

usage() {
  sed -n '3,23p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)    MODE="apply"; shift ;;
    --dry-run)  MODE="dry-run"; shift ;;
    --repo)     REPO="${2:?--repo 需要 owner/name 参数}"; shift 2 ;;
    --token)    TOKEN="${2:?--token 需要一个参数}"; shift 2 ;;
    --env-file) ENV_FILE="${2:?--env-file 需要一个参数}"; shift 2 ;;
    -h|--help)  usage; exit 0 ;;
    *) echo "未知参数：$1" >&2; usage >&2; exit 64 ;;
  esac
done

if [[ -z "$TOKEN" ]] && command -v gh >/dev/null 2>&1; then
  TOKEN="$(gh auth token 2>/dev/null || true)"
fi

if [[ -z "$TOKEN" ]]; then
  cat >&2 <<'EOF'
错误：没有可用的 GitHub Token。

请通过下面任意一种方式提供：
  export GH_TOKEN=<拥有 Secrets: Read and write 权限的 PAT>
  bin/set_access_secrets.sh --token <PAT>
  gh auth login && bin/set_access_secrets.sh
EOF
  exit 2
fi

if ! python3 -c 'import nacl.public' >/dev/null 2>&1; then
  cat >&2 <<'EOF'
错误：缺少 pynacl，无法生成 libsodium sealed box 密文。

请先安装：
  python3 -m pip install pynacl
EOF
  exit 2
fi

echo "仓库：${REPO}"
echo "模式：$([[ "$MODE" == "apply" ]] && echo 'apply（真正写入）' || echo 'dry-run（预演）')"
echo "取值来源：环境变量 > ${ENV_FILE}"
echo

MODE="$MODE" REPO="$REPO" TOKEN="$TOKEN" ENV_FILE="$ENV_FILE" \
  SECRET_NAMES="$(IFS=,; echo "${SECRET_NAMES[*]}")" \
  GITHUB_API_URL="${GITHUB_API_URL:-https://api.github.com}" \
  python3 - <<'PY'
import base64
import os
import sys

import requests
from nacl import encoding, public

REPO = os.environ["REPO"]
TOKEN = os.environ["TOKEN"]
ENV_FILE = os.environ["ENV_FILE"]
MODE = os.environ["MODE"]
API = os.environ["GITHUB_API_URL"].rstrip("/") + f"/repos/{REPO}/actions/secrets"
NAMES = [name for name in os.environ["SECRET_NAMES"].split(",") if name]

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

def parse_env_file(path):
    values = {}
    if not path or not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("'").strip('"')
    return values

def mask(value):
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}…{value[-4:]} ({len(value)} chars)"

def permission_hint(status):
    if status in (401, 403, 404):
        print(
            f"错误：当前 Token 无权管理仓库 Secret（HTTP {status}）。\n\n"
            "GitHub 要求管理 Repository Secrets 时必须具备：\n"
            "  * Fine-grained PAT：Repository permissions → Secrets: Read and write\n"
            "  * Classic PAT：repo scope\n",
            file=sys.stderr,
        )
        return True
    return False

file_values = parse_env_file(ENV_FILE)
values = {}
missing = []
for name in NAMES:
    value = os.environ.get(name) or file_values.get(name)
    if value:
        values[name] = value
    else:
        missing.append(name)

print("取值检查：")
for name in NAMES:
    if name in values:
        source = "环境变量" if os.environ.get(name) else ENV_FILE
        print(f"  ✅ {name} = {mask(values[name])}  （来源：{source}）")
    else:
        print(f"  ❌ {name} 未提供")

if missing:
    print(
        f"\n错误：缺少 {len(missing)} 个取值，未做任何写入：{', '.join(missing)}",
        file=sys.stderr,
    )
    sys.exit(2)

list_response = requests.get(API, headers=HEADERS, params={"per_page": 100}, timeout=30)
if list_response.status_code != 200:
    if not permission_hint(list_response.status_code):
        print(
            f"错误：读取仓库 Secret 列表失败：HTTP {list_response.status_code} {list_response.text}",
            file=sys.stderr,
        )
    sys.exit(3)

existing = {secret["name"] for secret in list_response.json().get("secrets", [])}
print(f"\n仓库现有 Secret：{len(existing)} 个")
for name in NAMES:
    print(f"  {'~' if name in existing else '+'} {name}（将{'更新' if name in existing else '新建'}）")

if MODE != "apply":
    print("\n这是预演。确认无误后执行：bin/set_access_secrets.sh --apply")
    sys.exit(0)

key_response = requests.get(f"{API}/public-key", headers=HEADERS, timeout=30)
if key_response.status_code != 200:
    print(
        f"错误：获取仓库公钥失败：HTTP {key_response.status_code} {key_response.text}",
        file=sys.stderr,
    )
    sys.exit(3)

key_payload = key_response.json()
sealed_box = public.SealedBox(
    public.PublicKey(base64.b64decode(key_payload["key"]), encoding.RawEncoder)
)

failed = 0
print()
for name in NAMES:
    encrypted = base64.b64encode(
        sealed_box.encrypt(values[name].encode("utf-8"))
    ).decode("ascii")
    response = requests.put(
        f"{API}/{name}",
        headers=HEADERS,
        json={"encrypted_value": encrypted, "key_id": key_payload["key_id"]},
        timeout=30,
    )
    if response.status_code in (201, 204):
        print(f"🔐 已写入 {name} = {mask(values[name])}")
    else:
        failed += 1
        print(f"❌ 写入 {name} 失败：HTTP {response.status_code} {response.text}", file=sys.stderr)

print()
if failed == 0:
    print(f"✅ 完成。{len(NAMES)} 个 Secret 已写入 {REPO}。")
else:
    print(f"⚠️  有 {failed} 个 Secret 写入失败，请查看上面的错误信息。", file=sys.stderr)
    sys.exit(1)
PY
