#!/usr/bin/env bash
#
# 删除已废弃的 GitHub Actions Repository Secrets。
#
# 这些名字已经不再被 sync_monitors.py 或 .github/workflows/*.yml 读取，
# 详见 README「可以删除的 Secrets」小节。
#
# 用法：
#   bin/delete_deprecated_secrets.sh                # 预演（默认，只列出将要删除的名字）
#   bin/delete_deprecated_secrets.sh --apply        # 真正执行删除
#   bin/delete_deprecated_secrets.sh --repo owner/name
#   bin/delete_deprecated_secrets.sh --token <PAT>
#
# Token 需要具备管理仓库 Secret 的权限（以下二选一）：
#   * Fine-grained PAT：Repository permissions → Secrets: Read and write
#   * Classic PAT：repo scope
# 未显式传入 --token 时，依次读取 $GH_TOKEN、$GITHUB_TOKEN，
# 若本机安装了 gh CLI 且已登录，则回退到 `gh auth token`。
# 自测/企业版可通过 $GITHUB_API_URL 覆盖 API 根地址（默认 https://api.github.com）。
#
set -euo pipefail

REPO="${REPO:-suwei8/UptimeRobot}"
MODE="dry-run"
TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"

# 已废弃的 Secret 名称（与 README「可以删除的 Secrets」表格保持一致）
DEPRECATED_SECRETS=(
  CF_API_EMAIL
  CF_API_KEY
  CF_ACCOUNT_ID
  CF_ZONE_ID
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
  UPTIMEROBOT_MAIN_API_KEY
)

RESPONSE_BODY=""
HTTP_CODE=""
LIST_ERROR_CODE=""

usage() {
  sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)   MODE="apply"; shift ;;
    --dry-run) MODE="dry-run"; shift ;;
    --repo)    REPO="${2:?--repo 需要 owner/name 参数}"; shift 2 ;;
    --token)   TOKEN="${2:?--token 需要一个参数}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数：$1" >&2; usage >&2; exit 64 ;;
  esac
done

API_BASE="${GITHUB_API_URL:-https://api.github.com}"
API="${API_BASE}/repos/${REPO}/actions/secrets"

if [[ -z "$TOKEN" ]] && command -v gh >/dev/null 2>&1; then
  TOKEN="$(gh auth token 2>/dev/null || true)"
fi

if [[ -z "$TOKEN" ]]; then
  cat >&2 <<'EOF'
错误：没有可用的 GitHub Token。

请通过下面任意一种方式提供：
  export GH_TOKEN=<拥有 Secrets: Read and write 权限的 PAT>
  bin/delete_deprecated_secrets.sh --token <PAT>
  gh auth login && bin/delete_deprecated_secrets.sh
EOF
  exit 2
fi

# 执行一次 API 调用，HTTP 状态码写入 HTTP_CODE，响应体写入 RESPONSE_BODY。
http_request() {
  local method="$1" url="$2" body_file
  body_file="$(mktemp)"
  HTTP_CODE="$(curl -sS -o "$body_file" -w '%{http_code}' -X "$method" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H 'Accept: application/vnd.github+json' \
    -H 'X-GitHub-Api-Version: 2022-11-28' \
    "$url" || echo "000")"
  RESPONSE_BODY="$(cat "$body_file")"
  rm -f "$body_file"
}

# 列出仓库现有的全部 Secret 名称（逐页读取）。失败时设置 LIST_ERROR_CODE 并返回 1。
list_secret_names() {
  local page=1 per_page=100 names=() total=0 body
  while :; do
    http_request GET "${API}?per_page=${per_page}&page=${page}"
    if [[ "$HTTP_CODE" != "200" ]]; then
      LIST_ERROR_CODE="$HTTP_CODE"
      return 1
    fi
    body="$RESPONSE_BODY"
    while IFS= read -r name; do
      [[ -n "$name" ]] && names+=("$name")
    done < <(printf '%s' "$body" | python3 -c \
      'import json,sys;print("\n".join(s["name"] for s in json.load(sys.stdin).get("secrets",[])))')
    total="$(printf '%s' "$body" | python3 -c \
      'import json,sys;print(json.load(sys.stdin).get("total_count",0))')"
    if (( ${#names[@]} >= total )) || (( ${#names[@]} < per_page )); then
      break
    fi
    page=$((page + 1))
  done
  if (( ${#names[@]} > 0 )); then
    printf '%s\n' "${names[@]}"
  fi
}

is_deprecated() {
  local candidate="$1" name
  for name in "${DEPRECATED_SECRETS[@]}"; do
    [[ "$name" == "$candidate" ]] && return 0
  done
  return 1
}

permission_hint() {
  cat >&2 <<EOF
错误：当前 Token 无权读取仓库 Secret（HTTP ${LIST_ERROR_CODE}）。

GitHub 要求管理 Repository Secrets 时必须具备：
  * Fine-grained PAT：Repository permissions → Secrets: Read and write
  * Classic PAT：repo scope

也可以改用网页删除：Settings → Secrets and variables → Actions → Repository secrets。
EOF
}

echo "仓库：${REPO}"
echo "模式：$([[ "$MODE" == "apply" ]] && echo 'apply（真正删除）' || echo 'dry-run（预演）')"
echo

EXISTING_FILE="$(mktemp)"
trap 'rm -f "$EXISTING_FILE"' EXIT

LIST_OK=1
if ! list_secret_names > "$EXISTING_FILE"; then
  LIST_OK=0
fi
mapfile -t EXISTING_SECRETS < "$EXISTING_FILE"

if (( LIST_OK == 1 )); then
  echo "仓库现有 Secret：${#EXISTING_SECRETS[@]} 个"
else
  echo "⚠️  无法读取现有 Secret 列表（HTTP ${LIST_ERROR_CODE}），仅按已废弃名单处理。"
fi

# 需要删除的名字：优先取「已废弃名单 ∩ 现有列表」，读不到列表时退化为整份已废弃名单。
TO_DELETE=()
if (( LIST_OK == 1 )); then
  for name in "${EXISTING_SECRETS[@]}"; do
    is_deprecated "$name" && TO_DELETE+=("$name")
  done
else
  TO_DELETE=("${DEPRECATED_SECRETS[@]}")
fi

echo
if (( ${#TO_DELETE[@]} == 0 )); then
  echo "✅ 没有需要删除的已废弃 Secret（可能已经清理过了）。"
  exit 0
fi

echo "待删除的已废弃 Secret（${#TO_DELETE[@]} 个）："
for name in "${TO_DELETE[@]}"; do
  echo "  - ${name}"
done
echo

if [[ "$MODE" != "apply" ]]; then
  if (( LIST_OK == 0 )); then
    permission_hint
    echo "提示：dry-run 仅做预演；修好权限后重新运行本脚本即可执行删除。" >&2
    exit 3
  fi
  echo "这是预演。确认无误后执行：bin/delete_deprecated_secrets.sh --apply"
  exit 0
fi

if (( LIST_OK == 0 )); then
  permission_hint
  exit 3
fi

FAILED=0
for name in "${TO_DELETE[@]}"; do
  http_request DELETE "${API}/${name}"
  case "$HTTP_CODE" in
    204) echo "🗑  已删除 ${name}" ;;
    404) echo "➖ 不存在，跳过 ${name}" ;;
    *)   echo "❌ 删除 ${name} 失败：HTTP ${HTTP_CODE} ${RESPONSE_BODY}" >&2; FAILED=1 ;;
  esac
done

echo
if (( FAILED == 0 )); then
  echo "✅ 完成。已废弃的 Secret 清理完毕。"
else
  echo "⚠️  部分 Secret 删除失败，请查看上面的错误信息。" >&2
  exit 1
fi
