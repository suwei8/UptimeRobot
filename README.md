# UptimeRobot 监控同步

这个仓库用于把服务器公网 IP 同步到 UptimeRobot 监控，并在同步完成后通过 Telegram 发送 ARM64 服务器 IP 清单。

同时，它还会把采集到的 ARM64 服务器 `IPv4` / `IPv6` 更新到 Cloudflare 安全规则中，用于维护目标服务的允许访问 IP 白名单。

## 功能说明

- 从 `HOSTS_CONFIG_URL` 拉取服务器清单
- 按 `arm64` 和 `amd64` 区分服务器
- 读取两个 UptimeRobot 账号下的现有监控
- 删除配置中已不存在的监控
- 当服务器 `IPv4` 变化时创建或更新监控
- 自动绑定每个 UptimeRobot 账号的第一个告警联系人
- 采集 ARM64 服务器公网 `IPv4` 和 `IPv6`
- 发送 Telegram 消息 `ARM64 服务器 IP 清单`
- 仅将 ARM64 服务器 IP 更新到 Cloudflare 规则 `Allow Only Server IP List to batam2-ai`

## 仓库结构

- [`sync_monitors.py`](/home/sw/dev_root/UptimeRobot/sync_monitors.py)：主同步脚本
- [`.github/workflows/sync_monitors.yml`](/home/sw/dev_root/UptimeRobot/.github/workflows/sync_monitors.yml)：GitHub Actions 工作流
- [`bin/cloudflared-linux-amd64`](/home/sw/dev_root/UptimeRobot/bin/cloudflared-linux-amd64)：通过 Cloudflare Access 进行 SSH 代理时使用的二进制文件
- [`cloudflare_extra_allowlist.txt`](/home/sw/dev_root/UptimeRobot/cloudflare_extra_allowlist.txt)：需要长期保留在 Cloudflare 规则中的额外 IP / CIDR 白名单

## 运行流程

1. 从远端 JSON 配置加载服务器列表。
2. GitHub Actions 先生成服务器矩阵。
3. 通过 `matrix` job 逐台处理服务器，并设置 `max-parallel: 1`，保证同一时间只采集一台。
4. 每个采集 job 通过 Cloudflare Access SSH 登录对应 `ssh_host`，获取公网 `IPv4` 和 `IPv6`，并保存为单独结果文件。
5. 最后的汇总 job 读取全部采集结果。
6. 使用采集到的 `IPv4` 同步 UptimeRobot 监控目标。
7. 基于 ARM64 服务器采集结果构建 `IPv4` / `IPv6` 白名单。
8. 更新 Cloudflare 安全规则表达式。
9. 发送 ARM64 IP 汇总到 Telegram。

## 所需 Secrets

### UptimeRobot

- `CF_555606_XYZ_MAIN_API_KEY`
- `XINJIAPO_555606_XYZ_MAIN_API_KEY`
- `CF_555606_XYZ_STATUS_PAGE_ID` / `CF_555606_XYZ_STATUS_PAGE_URL_KEY`（可选）
- `XINJIAPO_555606_XYZ_STATUS_PAGE_ID` / `XINJIAPO_555606_XYZ_STATUS_PAGE_URL_KEY`（可选）

这两个是 UptimeRobot API Key，不是 Cloudflare Token。
如果某个账号下有多个状态页，可通过上面的可选变量指定脚本应同步哪一个状态页；若账号下只有一个状态页，脚本会自动使用它。

### 主机配置

- `HOSTS_CONFIG_URL`
- `EXTRA_HOSTS_CONFIG_URL`（可选）

`HOSTS_CONFIG_URL` 需要返回类似下面的 JSON：

```json
[
  {
    "name": "SG1-新加坡",
    "cpu_type": "arm64",
    "ssh_host": "singapore-1-ssh.555606.xyz"
  }
]
```

### SSH

- `SSH_USERNAME`
- `AMD64_SSH_USERNAME`
- `SSH_PASSWORD`

脚本通过 `cloudflared access ssh --hostname ...` 配合 `sshpass` 访问服务器。

### Telegram

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### Cloudflare

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ZONE_ID` 或 `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_RULESET_ID`
- `CLOUDFLARE_RULE_ID`（推荐）
- `CLOUDFLARE_RULE_DESCRIPTION`（可选，默认值为 `Allow Only Server IP List to batam2-ai`）
- `CLOUDFLARE_RULE_EXPRESSION_TEMPLATE`（可选，作为兜底模板）

说明：

- 只有 ARM64 服务器的 `IPv4` 和 `IPv6` 会写入 Cloudflare 安全规则。
- 如果需要长期保留额外的静态来源 IP 或网段，可写入 [`cloudflare_extra_allowlist.txt`](/home/sw/dev_root/UptimeRobot/cloudflare_extra_allowlist.txt)，脚本会在每次更新 Cloudflare 规则时一并合并。
- 如果没有设置 `CLOUDFLARE_RULE_ID`，脚本会按 `CLOUDFLARE_RULE_DESCRIPTION` 查找目标规则。
- 如果现有规则表达式里并不包含 `ip.src in { ... }` 这种内联 IP 集合，需要提供 `CLOUDFLARE_RULE_EXPRESSION_TEMPLATE`，并使用占位符 `__IP_SET__`。

模板示例：

```text
(http.host eq "batam2-ai.example.com" and ip.src in __IP_SET__)
```

## 本地运行

安装依赖：

```bash
python3 -m pip install requests
```

执行脚本：

```bash
python3 sync_monitors.py
```

如果仓库根目录存在本地 `.env`，脚本也会自动加载。

## GitHub Actions

工作流定义在 [`.github/workflows/sync_monitors.yml`](/home/sw/dev_root/UptimeRobot/.github/workflows/sync_monitors.yml) 中，当前配置为每 8 小时运行一次，也支持手动触发。

当前工作流分为 3 个阶段：

1. `prepare`
   从 `HOSTS_CONFIG_URL` 拉取服务器清单并生成 `matrix`
2. `collect`
   每个 `matrix` 任务只负责一台服务器的 SSH 登录与 IP 采集，并通过 `max-parallel: 1` 保证按顺序执行，不会同时批量开始
3. `aggregate`
   统一下载所有采集结果，再更新 UptimeRobot、Cloudflare 和 Telegram

这意味着：

- 不再由单个 Runner 在一个 job 里连续登录所有服务器
- 而是一个 Runner 只负责连接一台 `ssh_host`
- 但是否落到完全不同的 GitHub 出口 IP，仍取决于 GitHub Hosted Runner 的分配方式，仓库本身无法完全控制

## 当前行为

- UptimeRobot 监控仍然会同时同步 `arm64` 和 `amd64`
- Telegram 报告仅发送 `arm64`
- Cloudflare 白名单仅更新 `arm64`
- UptimeRobot 监控 URL 仍然只使用 `IPv4`
- GitHub Actions 会按顺序逐台采集服务器 IP，不会并发批量 SSH 登录

## 验证

基础语法检查：

```bash
python3 -m py_compile sync_monitors.py
```
