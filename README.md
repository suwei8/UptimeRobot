# UptimeRobot 监控同步

这个仓库用于把服务器公网 IP 同步到 UptimeRobot 监控，并把全部主机的 IP 清单写入私有仓库 `suwei8/blog` 的 `internal-notes.txt`。

> ⚠️ 该清单文件原名为 `HOSTS_IP.txt`，因为文件名已泄露，现已改名。工作流会自动从 `suwei8/blog` 默认分支删除残留的 `HOSTS_IP.txt`。

同时，它还会把采集到的 ARM64 服务器 `IPv4` / `IPv6` 更新到 Cloudflare 安全规则中，用于维护目标服务的允许访问 IP 白名单。

## 功能说明

- 从 `HOSTS_CONFIG_URL` 拉取服务器清单
- 按 `arm64` 和 `amd64` 区分服务器
- 读取两个 UptimeRobot 账号下的现有监控
- 删除配置中已不存在的监控
- 当服务器 `IPv4` 变化时创建或更新监控
- 自动绑定每个 UptimeRobot 账号的第一个告警联系人
- 采集 ARM64 服务器公网 `IPv4` 和 `IPv6`
- 采集 AMD64 服务器公网 `IPv4` 和 `IPv6`
- 仅将 ARM64 服务器 IP 更新到 Cloudflare 规则 `Allow Only Server IP List to batam2-ai`
- 将全部主机 IP 清单提交到私有仓库 `suwei8/blog` 的 `internal-notes.txt`

## 仓库结构

- [`sync_monitors.py`](/home/sw/dev_root/UptimeRobot/sync_monitors.py)：主同步脚本
- [`.github/workflows/sync_monitors.yml`](/home/sw/dev_root/UptimeRobot/.github/workflows/sync_monitors.yml)：GitHub Actions 工作流
- [`bin/cloudflared-linux-amd64`](/home/sw/dev_root/UptimeRobot/bin/cloudflared-linux-amd64)：通过 Cloudflare Access 进行 SSH 代理时使用的二进制文件
- [`cloudflare_extra_allowlist.txt`](/home/sw/dev_root/UptimeRobot/cloudflare_extra_allowlist.txt)：需要长期保留在 Cloudflare 规则中的额外 IP / CIDR 白名单
- [`bin/delete_deprecated_secrets.sh`](/home/sw/dev_root/UptimeRobot/bin/delete_deprecated_secrets.sh)：批量删除下面「可以删除的 Secrets」中列出的已废弃 Repository Secrets（默认 dry-run）
- [`bin/set_access_secrets.sh`](/home/sw/dev_root/UptimeRobot/bin/set_access_secrets.sh)：写入「SSH」小节所需的 4 个 Cloudflare Access Service Token Secret（默认 dry-run）
- [`bin/check_access_tokens.sh`](/home/sw/dev_root/UptimeRobot/bin/check_access_tokens.sh)：对指定 `ssh_host` 做 A/B 探测，验证 Access Service Token 是否能通过对应区域的策略

## 运行流程

1. 从远端 JSON 配置加载服务器列表。
2. GitHub Actions 先生成服务器矩阵。
3. 通过 `matrix` job 逐台处理服务器，并设置 `max-parallel: 1`，保证同一时间只采集一台。
4. 每个采集 job 通过 Cloudflare Access SSH 登录对应 `ssh_host`，获取公网 `IPv4` 和 `IPv6`，并将结果 JSON 推送到私有仓库 `suwei8/blog` 的 `ip-collect` 分支（不上传 GitHub artifacts，避免在公开仓库暴露 IP）。
5. 最后的汇总 job 从 `ip-collect` 分支取回全部采集结果。
6. 使用采集到的 `IPv4` 同步 UptimeRobot 监控目标。
7. 基于 ARM64 服务器采集结果构建 `IPv4` / `IPv6` 白名单。
8. 更新 Cloudflare 安全规则表达式。
9. 生成 `internal-notes.txt` 提交到 `suwei8/blog` 默认分支（同时清理历史泄露文件 `HOSTS_IP.txt`），并删除 `ip-collect` 临时分支。

## 所需 Secrets

> 全部 Secret 都在 **Settings → Secrets and variables → Actions → Repository secrets** 中配置，
> 名称必须与下表完全一致（区分大小写）。带「可选」的 Secret 不配置也能跑通。

| Secret 名称 | 必需 | 用途 |
| --- | --- | --- |
| `HOSTS_CONFIG_URL` | ✅ | 主服务器清单 JSON 地址 |
| `EXTRA_HOSTS_CONFIG_URL` | ✅（补充服务器时） | 额外服务器清单 JSON 地址 |
| `CF_555606_XYZ_MAIN_API_KEY` | ✅ | UptimeRobot 账号 1（arm64）Main API Key |
| `XINJIAPO_555606_XYZ_MAIN_API_KEY` | ✅ | UptimeRobot 账号 2（amd64）Main API Key |
| `SSH_USERNAME` | ✅ | arm64 服务器 SSH 用户名 |
| `AMD64_SSH_USERNAME` | ✅ | amd64 服务器 SSH 用户名 |
| `SSH_PASSWORD` | ✅ | 服务器 SSH 密码 |
| `CF_ACCESS_ID_HHWPXH` | ✅ | `hhwpxh.com` 区域的 Cloudflare Access Service Token ID |
| `CF_ACCESS_SECRET_HHWPXH` | ✅ | `hhwpxh.com` 区域的 Cloudflare Access Service Token Secret |
| `CF_ACCESS_ID_555606` | ✅ | `555606.xyz` 区域的 Cloudflare Access Service Token ID |
| `CF_ACCESS_SECRET_555606` | ✅ | `555606.xyz` 区域的 Cloudflare Access Service Token Secret |
| `BLOG_REPO_PAT` | ✅ | 推送 `suwei8/blog` 私有仓库的 PAT |
| `CLOUDFLARE_API_TOKEN` | ✅ | 更新 Cloudflare 规则（API Token，权限见「Cloudflare」小节） |
| `CLOUDFLARE_ZONE_ID` | ✅ | Cloudflare Zone ID |
| `CLOUDFLARE_RULESET_ID` | ✅ | 目标 Ruleset ID |
| `CLOUDFLARE_RULE_ID` | 推荐 | 目标规则 ID |
| `CLOUDFLARE_RULE_DESCRIPTION` | 可选 | 未提供 `CLOUDFLARE_RULE_ID` 时按描述查找规则 |
| `CLOUDFLARE_RULE_EXPRESSION_TEMPLATE` | 可选 | 规则表达式模板（含 `__IP_SET__`） |
| `CLOUDFLARE_ACCOUNT_ID` | 可选 | 仅当目标规则在账号级别（而非 Zone 级别）时才需要 |
| `CF_555606_XYZ_STATUS_PAGE_ID` / `_URL_KEY` | 可选 | 指定 arm64 状态页 |
| `XINJIAPO_555606_XYZ_STATUS_PAGE_ID` / `_URL_KEY` | 可选 | 指定 amd64 状态页 |

### 可以删除的 Secrets

> ✅ 已于 2026-10-31 全部清理完毕（用 `bin/delete_deprecated_secrets.sh --apply` 删除）。
> 下表保留作为记录；若日后再次出现同名 Secret，可重复运行脚本（幂等）。

下面这些名字已经不再被代码或工作流读取，可以直接删除：

| Secret 名称 | 删除原因 |
| --- | --- |
| `CF_API_EMAIL` | Cloudflare Global API Key 认证已废弃，改用 `CLOUDFLARE_API_TOKEN` |
| `CF_API_KEY` | 同上（Global API Key 本身也建议在 Cloudflare 后台吊销） |
| `CF_ACCOUNT_ID` | 旧别名，代码已只读取 `CLOUDFLARE_ACCOUNT_ID` |
| `CF_ZONE_ID` | 旧别名，代码已只读取 `CLOUDFLARE_ZONE_ID` |
| `TELEGRAM_BOT_TOKEN` | Telegram IP 推送已停用（`send_telegram_ip_report` 未被调用） |
| `TELEGRAM_CHAT_ID` | 同上 |
| `UPTIMEROBOT_MAIN_API_KEY` | 历史名称，已拆分为 `CF_555606_XYZ_MAIN_API_KEY` / `XINJIAPO_555606_XYZ_MAIN_API_KEY` |

删除方式（网页：**Settings → Secrets and variables → Actions → Repository secrets** 逐个删除）：

```bash
# 1. 先预演，确认待删除名单（默认就是 dry-run）
bin/delete_deprecated_secrets.sh

# 2. 确认无误后真正删除
export GH_TOKEN=<拥有 Secrets: Read and write 权限的 PAT>
bin/delete_deprecated_secrets.sh --apply
```

脚本只删除上表列出的名字（幂等，重复运行不会报错），且需要 Token 具备
**Fine-grained PAT → Repository permissions → Secrets: Read and write**（或 Classic PAT 的 `repo` scope）权限；
只有仓库 Admin 权限但没有 Secrets 权限的 Token 会返回 `HTTP 403`。

本次执行结果（2026-10-31）：删除了 `CF_API_EMAIL`、`CF_API_KEY`、`CF_ACCOUNT_ID`、`CF_ZONE_ID`、
`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`；`UPTIMEROBOT_MAIN_API_KEY` 此前已不存在。
随后又用 `bin/set_access_secrets.sh --apply` 补齐了 4 个 Access Service Token Secret（详见「SSH」小节），
仓库 Secret 总数由 9 个变为 13 个，全部为在用项：`HOSTS_CONFIG_URL`、`EXTRA_HOSTS_CONFIG_URL`、
`CF_555606_XYZ_MAIN_API_KEY`、`XINJIAPO_555606_XYZ_MAIN_API_KEY`、`SSH_USERNAME`、
`AMD64_SSH_USERNAME`、`SSH_PASSWORD`、`CF_ACCESS_ID_HHWPXH`、`CF_ACCESS_SECRET_HHWPXH`、
`CF_ACCESS_ID_555606`、`CF_ACCESS_SECRET_555606`、`BLOG_REPO_PAT`、`CLOUDFLARE_API_TOKEN`。

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

`EXTRA_HOSTS_CONFIG_URL` 用于补充额外的服务器，返回格式与 `HOSTS_CONFIG_URL` 相同，也是一个 JSON 数组：

```json
[
  {
    "name": "SG1-XXX",
    "cpu_type": "arm64",
    "ssh_host": "xxx-ssh.555606.xyz",
    "proxy_domains": "",
    "vless_host": "",
    "keepalive": false
  },
  {
    "name": "SG1-YYY",
    "cpu_type": "amd64",
    "ssh_host": "yyy-ssh.555606.xyz",
    "proxy_domains": "",
    "vless_host": ""
  }
]
```

说明：

- 两个地址返回的数组会被合并；`name` 重复的条目只保留第一个（`HOSTS_CONFIG_URL` 优先）。
- 只有同时包含 `name` 和 `ssh_host` 的条目才会被当作服务器；其余字段（`proxy_domains`、`vless_host`、`keepalive` 等）会被忽略。
- 因为 `EXTRA_HOSTS_CONFIG_URL` 现在是「服务器列表」，不再用于「额外的静态监控定义」，所以以前那种带 `url` 字段的静态监控条目会由 `get_extra_monitors_list()` 单独识别（带 `url` 的条目才当作静态监控）。
- ⚠️ 必须是**合法 JSON**：最后一个对象后面不能有多余逗号，否则 `response.json()` 会抛异常。建议用 `python3 -m json.tool <file>` 校验。

### SSH

- `SSH_USERNAME`
- `AMD64_SSH_USERNAME`
- `SSH_PASSWORD`
- `CF_ACCESS_ID_HHWPXH` / `CF_ACCESS_SECRET_HHWPXH`（`hhwpxh.com` 区域的 Access Service Token）
- `CF_ACCESS_ID_555606` / `CF_ACCESS_SECRET_555606`（`555606.xyz` 区域的 Access Service Token）

脚本通过 `cloudflared access ssh --hostname ...` 配合 `sshpass` 访问服务器。

服务器清单里的 `ssh_host` 分属两个受 Cloudflare Access 保护的区域（`hhwpxh.com` 和 `555606.xyz`），
未携带 Service Token 的请求会被重定向到 `https://sw8.cloudflareaccess.com/cdn-cgi/access/login/...`（HTTP 302）。
因此 `sync_monitors.py` 会按 `ssh_host` 的域名后缀选择对应的 Service Token，
并以 `cloudflared access ssh --service-token-id ... --service-token-secret ...` 的形式传给代理：

| `ssh_host` 后缀 | 使用的 Secret |
| --- | --- |
| `*.hhwpxh.com` | `CF_ACCESS_ID_HHWPXH` / `CF_ACCESS_SECRET_HHWPXH` |
| `*.555606.xyz` | `CF_ACCESS_ID_555606` / `CF_ACCESS_SECRET_555606` |

> ⚠️ Service Token 是**按区域隔离**的：用错区域会被 Access 拒绝（返回 302 登录页）。
> 所以不要只配置一个 Token，两个区域都要配。

Service Token 创建位置（Cloudflare Dashboard）：

1. **Zero Trust → Access → Service Auth → Service Tokens → Create Service Token**
2. 每个区域（`hhwpxh.com`、`555606.xyz`）各建一个，Duration 建议 `Non-expiring`
3. 把生成的 `Client ID`（形如 `xxxx.access`）和 `Client Secret`（形如 `cfast_xxxx`）分别填入上面 4 个 Secret
4. 确认两个区域的 Access 应用策略里允许该 Service Token（Policy → Action `Service Auth` / `Allow`）

本地运行时，这 4 个变量可直接写在仓库根目录的 `.env` 中（脚本会自动加载）。

#### 写入这 4 个 Secret

工作流读取的是 `secrets.CF_ACCESS_ID_HHWPXH` 等 4 个名字。**如果它们没有配置，`cloudflared` 会退化为交互式认证，
采集任务就会因为 Access 登录页（HTTP 302）而失败。** 用 `bin/set_access_secrets.sh` 可以幂等地写入：

```bash
# 取值来源：环境变量 > .env（默认仓库根目录）
bin/set_access_secrets.sh                       # 预演：只校验取值与权限
bin/set_access_secrets.sh --apply               # 真正写入
bin/set_access_secrets.sh --token <PAT>         # 覆盖 Token
bin/set_access_secrets.sh --env-file <path>     # 覆盖取值来源文件
bin/set_access_secrets.sh --secret SSH_PASSWORD # 追加写入其它 Secret（可重复）
```

脚本要求 Token 具备 **Fine-grained PAT → Repository permissions → Secrets: Read and write**（或 Classic PAT 的 `repo` scope），
并使用 python3 的 `pynacl` 生成 GitHub 要求的 libsodium sealed box 密文：

```bash
python3 -m pip install pynacl
```

> 该脚本默认只写这 4 个名字，重复运行不会报错（已存在则更新）；
> 凭据轮换后需要更新别的 Secret（如 `SSH_PASSWORD`）时，用 `--secret <NAME>` 追加，取值同样来自环境变量或 `.env`。

本次执行结果（2026-10-31）：4 个 Secret 全部写入成功，仓库 Secret 总数由 9 个变为 13 个。

验证方式：用 `ssh -o BatchMode=yes` 走 `cloudflared access ssh` 做 A/B 对比——不带 Token 会被 Access 拦下，
带**对应区域**的 Token 才能握手到 SSH 服务（此时报 `Permission denied` 属于预期，因为只测隧道不测密码）：

| 探测 | 结果 |
| --- | --- |
| `555606.xyz` 主机 + 不带 Token | `Connection timed out during banner exchange`（被 Access 拦下） |
| `555606.xyz` 主机 + `CF_ACCESS_ID_555606` | `Permission denied (publickey,password)`（已到达 SSH 服务） |
| `hhwpxh.com` 主机 + 不带 Token | `Connection timed out during banner exchange`（被 Access 拦下） |
| `hhwpxh.com` 主机 + `CF_ACCESS_ID_HHWPXH` | `Permission denied (publickey,password)`（已到达 SSH 服务） |
| `555606.xyz` 主机 + `CF_ACCESS_ID_HHWPXH`（跨区域） | `Connection timed out during banner exchange`（被拦，符合区域隔离） |

### Blog 仓库

- `BLOG_REPO_PAT`

用于向私有仓库 `suwei8/blog` 推送采集结果（`ip-collect` 分支）和 `internal-notes.txt`。
GitHub 内置的 `GITHUB_TOKEN` 只能写本仓库，跨仓库推送必须提供 PAT；
建议创建 Fine-grained PAT，仅授权 `suwei8/blog` 的 `Contents: Read and write` 权限。
注意 secret 不能以 `GITHUB_` 前缀命名（GitHub 保留），因此不能使用 `GITHUB_TOKEN` 这个名字。

### Telegram

- 已停用：`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 不再需要（`send_telegram_ip_report` 目前未被调用）

### Cloudflare

Cloudflare 只使用 **API Token** 认证；旧版 Global API Key（`CF_API_EMAIL` + `CF_API_KEY`）以及 `CF_ACCOUNT_ID` / `CF_ZONE_ID` 别名已不再支持。

需要配置的 Secret：

- `CLOUDFLARE_API_TOKEN`（必需）
- `CLOUDFLARE_ZONE_ID`（必需，本仓库规则为 Zone 级别）
- `CLOUDFLARE_RULESET_ID`
- `CLOUDFLARE_RULE_ID`（推荐）
- `CLOUDFLARE_RULE_DESCRIPTION`（可选，默认值为 `Allow Only Server IP List to batam2-ai`）
- `CLOUDFLARE_RULE_EXPRESSION_TEMPLATE`（可选，作为兜底模板）
- `CLOUDFLARE_ACCOUNT_ID`（可选，仅当规则在账号级别时才需要）

#### 创建 `CLOUDFLARE_API_TOKEN` 所需的权限

在 Cloudflare 后台 **My Profile → API Tokens → Create Token → Create Custom Token** 中创建，
脚本实际调用的接口只有以下三个（全部为 Zone 级别）：

| 脚本调用的接口 | 用途 |
| --- | --- |
| `GET /zones/{zone_id}/rulesets/phases/http_request_firewall_custom/entrypoint` | 读取 Zone 级 WAF 自定义规则入口 Ruleset |
| `GET /zones/{zone_id}/rulesets/{ruleset_id}` | 读取指定 Ruleset 及其规则 |
| `PATCH /zones/{zone_id}/rulesets/{ruleset_id}/rules/{rule_id}` | 更新规则表达式中的 IP 白名单 |

因此 Token 权限按下面这样勾选即可（不要多给）：

| 项目 | 取值 |
| --- | --- |
| Permissions | **Zone → WAF → Edit**（API 权限名称为 `Zone WAF: Write`，同时包含读取能力） |
| Zone Resources | **Include → Specific zone → 目标 Zone**（例如 `555606.xyz`） |
| Client IP Address Filtering | 不填 |
| TTL | 不填（长期有效） |

说明：

- 只需要 **Zone WAF: Edit** 这一条权限；不需要 `Account Rulesets`、`Zone: Read`、`DNS: Edit` 等任何其他权限。
- 如果只做读取验证、不打算写入，可以只给 `Zone WAF: Read`，但工作流最后一步 `PATCH` 更新规则时会失败。
- 使用 Global API Key 的时代已经结束：代码里不再有任何 Global Key 兜底路径，Token 缺失或权限不足时会直接报错并给出权限提示。
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

工作流定义在 [`.github/workflows/sync_monitors.yml`](/home/sw/dev_root/UptimeRobot/.github/workflows/sync_monitors.yml) 中，当前配置为每天 02:00 UTC（北京时间 10:00）运行一次，也支持手动触发。

运行环境说明：

- 使用 `ubuntu-latest`（2026-10-19 起为 Ubuntu 26.04）
- 使用 `actions/checkout@v5` 与 `actions/setup-python@v5`
- Python 版本固定为 `3.12`（Ubuntu 26.04 上不再提供 3.9）

当前工作流分为 3 个阶段：

1. `prepare`
   从 `HOSTS_CONFIG_URL` 拉取服务器清单并生成 `matrix`
2. `collect`
   每个 `matrix` 任务只负责一台服务器的 SSH 登录与 IP 采集，并通过 `max-parallel: 1` 保证按顺序执行，不会同时批量开始；结果 JSON 逐个推送到 `suwei8/blog` 的 `ip-collect` 分支
3. `aggregate`
   从 `ip-collect` 分支取回全部采集结果，更新 UptimeRobot 和 Cloudflare，并把 `internal-notes.txt` 提交到 `suwei8/blog` 默认分支

这意味着：

- 不再由单个 Runner 在一个 job 里连续登录所有服务器
- 而是一个 Runner 只负责连接一台 `ssh_host`
- 但是否落到完全不同的 GitHub 出口 IP，仍取决于 GitHub Hosted Runner 的分配方式，仓库本身无法完全控制

## 当前行为

- UptimeRobot 监控仍然会同时同步 `arm64` 和 `amd64`
- Cloudflare 白名单仅更新 `arm64`
- 主机 IP 清单写入私有仓库 `suwei8/blog` 的 `internal-notes.txt`（原名 `HOSTS_IP.txt` 已因泄露改名），不再通过 artifacts 或 Telegram 传播
- `transport` 为 `direct` 的主机会被跳过：不参与 IP 采集和监控更新，已有监控保留不动
- UptimeRobot 监控 URL 仍然只使用 `IPv4`
- GitHub Actions 会按顺序逐台采集服务器 IP，不会并发批量 SSH 登录

## 验证

基础语法检查：

```bash
python3 -m py_compile sync_monitors.py
```

校验工作流 YAML：

```bash
python3 -c "import yaml; [yaml.safe_load(open(f)) for f in ['.github/workflows/sync_monitors.yml', '.github/workflows/manual_cloudflare_update.yml']]; print('YAML OK')"
```

校验远端服务器配置 JSON 是否合法（把 URL 换成实际地址）：

```bash
curl -fsSL "$EXTRA_HOSTS_CONFIG_URL" | python3 -m json.tool > /dev/null && echo "JSON OK"
```

验证两个区域的 Access Service Token 能否通过 Cloudflare Access（A/B 探测，不需要 `sshpass`）：

```bash
# 参数为服务器清单里的 ssh_host，两个区域各给一个
bin/check_access_tokens.sh drms556i2a-ssh.555606.xyz yjto7jbw7e-ssh.hhwpxh.com
```

预期输出：不带 Token 时被拦下，带对应区域的 Token 时报 `Permission denied (publickey,password)`（说明隧道已通）。

## 常见故障排查

### `prepare` 秒失败：`The version '3.9' ... was not found for Ubuntu 26.04`

原因：`ubuntu-latest` 已迁移到 Ubuntu 26.04，而该镜像不再提供 Python 3.9。

处理：工作流中所有 `python-version` 必须为 `3.12`，并且 `actions/setup-python` 至少为 `v5`。仓库当前已按此配置。

### 采集列表里缺少 `EXTRA_HOSTS_CONFIG_URL` 的服务器

原因：`prepare` job 里构建 matrix 的步骤没有把 `EXTRA_HOSTS_CONFIG_URL` 注入环境变量，Python 里读到的是空值。

处理：确认 `Build server matrix` 步骤的 `env:` 中同时包含 `HOSTS_CONFIG_URL` 和 `EXTRA_HOSTS_CONFIG_URL`。

### `Failed to fetch extra config: Expecting property name enclosed in double quotes`

原因：远端 JSON 不合法（常见于数组最后一个对象后多了逗号）。

处理：用 `python3 -m json.tool` 校验并修正远端文件。

### Secret 更新后仍失败

- GitHub 不会回显 Secret 的值，只有 `***`；如果怀疑值有误，直接覆盖重新保存即可。
- Secret 名称区分大小写，必须与工作流中的 `${{ secrets.XXX }}` 完全一致。
- Secret 值不要包含首尾空格或换行（复制粘贴时容易带入）。
- 修改 Secret 后需要重新触发工作流（`workflow_dispatch` 或等待下一次 schedule），不会自动重跑。

### `collect` 阶段 SSH 失败：被重定向到 Access 登录页（HTTP 302）

原因：`secrets.CF_ACCESS_ID_HHWPXH`、`secrets.CF_ACCESS_SECRET_HHWPXH`、
`secrets.CF_ACCESS_ID_555606`、`secrets.CF_ACCESS_SECRET_555606` 这 4 个 Secret 没有配置，
工作流把它们注入成空字符串，`cloudflared access ssh` 拿不到 Service Token，就会退化为交互式认证并被 Access 拦下。

处理：

```bash
# 1. 写入 4 个 Access Service Token Secret
bin/set_access_secrets.sh --apply

# 2. 复验（不带 Token 会被拦，带对应区域的 Token 能握手到 SSH）
bin/check_access_tokens.sh <555606.xyz 的 ssh_host> <hhwpxh.com 的 ssh_host>
```

补充说明：

- Service Token 是**按区域隔离**的，用错区域同样会被拦下（返回 302 登录页）。
- 除了 Token 本身，还要确认两个区域的 Access 应用策略里允许该 Service Token（Policy → Action `Service Auth` / `Allow`）。
- 排查时优先看 job 日志里的 `Using Cloudflare Access service token 0163****cess for ***-ssh.555606.xyz` 之类的输出，
  它说明脚本选中了哪个区域的 Token（Token ID 在日志中始终是打码的）。

### Access 已通过、但 SSH 认证失败：`Permission denied, please try again.`

`collect` job 日志里先出现 `Using Cloudflare Access service token ...`（说明隧道已打通、Access 已放行），
紧接着是 `Permission denied, please try again.`——这说明 **Access 这一层没问题，是 SSH 用户名/密码被服务器拒绝**。

排查与处理：

1. 先用 `bin/check_access_tokens.sh <ssh_host>` 复验隧道：只要能看到 `Permission denied (publickey,password)`，就说明 Access 正常。
2. 在服务器上确认当前的 SSH 用户名/密码，然后更新对应 Secret：

```bash
# 先把新值写进仓库根目录的 .env（该文件已被 .gitignore 忽略，不会被提交）
# SSH_USERNAME=<arm64 用户名>
# AMD64_SSH_USERNAME=<amd64 用户名>
# SSH_PASSWORD=<新密码>
bin/set_access_secrets.sh --apply --secret SSH_USERNAME --secret AMD64_SSH_USERNAME --secret SSH_PASSWORD
```

3. 改完后重新触发工作流（`workflow_dispatch` 或等下一次 schedule）。

> ⚠️ `SSH_USERNAME` / `AMD64_SSH_USERNAME` / `SSH_PASSWORD` 这三个 Secret 最后更新于 2026-01-12。
> 如果服务器侧改过密码（例如密钥泄露后的凭据轮换），CI 会一直认证失败，
> 但 collect job 状态**仍然显示 success**（脚本把失败写进结果 JSON 的 `status` 字段，不会让 job 失败）。
> 判断采集是否真的成功，要看 `Collected <主机名> (cpu): IPv4=...` 里是不是真实 IP，而不是 `N/A`。


