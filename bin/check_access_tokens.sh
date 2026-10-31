#!/usr/bin/env bash
#
# 验证 Cloudflare Access Service Token 是否能通过对应区域的 Access 策略。
#
# 对每个传入的 ssh_host 做 A/B 对比：
#   * 不带 Token        -> 预期被 Access 拦下（banner exchange 超时）
#   * 带对应区域的 Token -> 预期能握手到 SSH 服务（此时报 Permission denied 属正常）
#
# 用法：
#   bin/check_access_tokens.sh drms556i2a-ssh.555606.xyz yjto7jbw7e-ssh.hhwpxh.com
#
# 取值来源：环境变量 > 仓库根目录的 .env（与 sync_monitors.py 一致）。
# 依赖 bin/cloudflared-linux-amd64，以及可用的 ssh 客户端（不需要 sshpass）。
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT" || exit 1

CF="${REPO_ROOT}/bin/cloudflared-linux-amd64"

usage() {
  sed -n '3,14p' "$0" | sed 's/^# \{0,1\}//'
}

if [[ $# -eq 0 ]]; then
  usage
  exit 64
fi

if [[ ! -x "$CF" ]]; then
  echo "错误：找不到可执行的 ${CF}" >&2
  exit 2
fi

# 读取取值：优先环境变量，其次仓库根目录的 .env
read_value() {
  local name="$1" value
  value="$(printenv "$name" 2>/dev/null || true)"
  if [[ -n "$value" ]]; then
    printf '%s' "$value"
    return
  fi
  [[ -f .env ]] || return 0
  grep -m1 "^${name}=" .env | cut -d= -f2- | tr -d '\r' | sed "s/^['\"]//; s/['\"]$//"
}

# 走 cloudflared 代理执行一次 SSH 握手（只测隧道，不做密码认证）
ssh_probe() {
  local host="$1" id="$2" secret="$3" proxy
  proxy="${CF} access ssh --hostname ${host}"
  if [[ -n "$id" && -n "$secret" ]]; then
    proxy="${proxy} --service-token-id ${id} --service-token-secret ${secret}"
  fi
  timeout 60 ssh \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=25 \
    -o "ProxyCommand=${proxy}" \
    "probe@${host}" true 2>&1
}

FAILED=0

for host in "$@"; do
  zone=""
  case "${host,,}" in
    *.hhwpxh.com)
      zone="hhwpxh.com"
      token_id="$(read_value CF_ACCESS_ID_HHWPXH)"
      token_secret="$(read_value CF_ACCESS_SECRET_HHWPXH)"
      ;;
    *.555606.xyz)
      zone="555606.xyz"
      token_id="$(read_value CF_ACCESS_ID_555606)"
      token_secret="$(read_value CF_ACCESS_SECRET_555606)"
      ;;
    *)
      echo "⏭  跳过 ${host}：不在已配置的区域后缀内（hhwpxh.com / 555606.xyz）"
      continue
      ;;
  esac

  if [[ -z "$token_id" || -z "$token_secret" ]]; then
    echo "⏭  跳过 ${host}：缺少 ${zone} 区域的 Access Service Token（环境变量或 .env）"
    continue
  fi

  echo "=== ${host}（区域 ${zone}）==="

  no_token="$(ssh_probe "$host" "" "")"
  if grep -q 'Permission denied' <<<"$no_token"; then
    echo "  ⚠️  不带 Token 也握手成功：该 Access 应用可能没有启用访问策略"
  else
    echo "  ✅ 不带 Token 被拦下：$(tail -n 1 <<<"$no_token" | tr -d '\r')"
  fi

  with_token="$(ssh_probe "$host" "$token_id" "$token_secret")"
  if grep -q 'Permission denied' <<<"$with_token"; then
    echo "  ✅ 带 ${zone} Token 放行（已到达 SSH 服务）"
  else
    echo "  ❌ 带 ${zone} Token 仍被拦下：$(tail -n 1 <<<"$with_token" | tr -d '\r')"
    FAILED=1
  fi

  echo
done

if (( FAILED == 0 )); then
  echo "✅ 完成。所有被检查的主机都能用对应区域的 Token 通过 Cloudflare Access。"
else
  echo "⚠️  部分主机未通过，请检查 Access 应用策略是否允许该 Service Token（Policy → Action Service Auth / Allow）。" >&2
fi

exit "$FAILED"
