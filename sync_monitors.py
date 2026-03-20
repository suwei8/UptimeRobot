import os
import requests
import json
import subprocess
import time
import platform
import sys
import ipaddress
import re
import glob
import argparse
from datetime import datetime, timezone, timedelta

def load_local_env_file(env_path=".env"):
    if not os.path.exists(env_path):
        return

    try:
        with open(env_path, "r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                os.environ.setdefault(key, value)
    except OSError as exc:
        print(f"Warning: failed to load {env_path}: {exc}")

load_local_env_file()

# Configuration
CONFIG_URL = os.getenv("HOSTS_CONFIG_URL")
EXTRA_CONFIG_URL = os.getenv("EXTRA_HOSTS_CONFIG_URL")

API_KEYS = {
    "arm64": os.getenv("CF_555606_XYZ_MAIN_API_KEY"),
    "amd64": os.getenv("XINJIAPO_555606_XYZ_MAIN_API_KEY")
}

SSH_USERS = {
    "arm64": os.getenv("SSH_USERNAME"),
    "amd64": os.getenv("AMD64_SSH_USERNAME")
}
SSH_PASS = os.getenv("SSH_PASSWORD")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID") or os.getenv("CF_ACCOUNT_ID")
CLOUDFLARE_ZONE_ID = os.getenv("CLOUDFLARE_ZONE_ID") or os.getenv("CF_ZONE_ID")
CLOUDFLARE_API_EMAIL = os.getenv("CF_API_EMAIL")
CLOUDFLARE_API_KEY = os.getenv("CF_API_KEY")
CLOUDFLARE_RULESET_ID = os.getenv("CLOUDFLARE_RULESET_ID")
CLOUDFLARE_RULE_ID = os.getenv("CLOUDFLARE_RULE_ID")
CLOUDFLARE_RULE_DESCRIPTION = os.getenv(
    "CLOUDFLARE_RULE_DESCRIPTION",
    "Allow Only Server IP List to batam2-ai"
)
CLOUDFLARE_RULE_EXPRESSION_TEMPLATE = os.getenv("CLOUDFLARE_RULE_EXPRESSION_TEMPLATE")

# API V3 configuration
API_BASE = "https://api.uptimerobot.com/v3"

# V2 API for alert contacts (V3 doesn't support this endpoint)
V2_BASE = "https://api.uptimerobot.com/v2"

def require_uptimerobot_api_keys():
    if not API_KEYS["arm64"] or not API_KEYS["amd64"]:
        raise RuntimeError("One or both UptimeRobot Main API keys are not set.")

def get_alert_contact_id(api_key):
    try:
        resp = requests.post(f"{V2_BASE}/getAlertContacts", data={"api_key": api_key, "format": "json"})
        contacts = resp.json().get('alert_contacts', [])
        if contacts:
            cid = str(contacts[0]['id'])
            print(f"Found alert contact: {contacts[0].get('value')} (ID: {cid})")
            return cid
    except Exception as e:
        print(f"Failed to get alert contacts: {e}")
    return None

# Country flag emoji mapping based on server name prefix
COUNTRY_FLAGS = {
    "SG": "🇸🇬", "US": "🇺🇸", "JP": "🇯🇵", "KR": "🇰🇷",
    "ID": "🇮🇩", "AU": "🇦🇺", "ES": "🇪🇸", "DU": "🇦🇪",
    "JBP": "🇲🇾", "AWS": "🇺🇸"
}

def get_country_flag(name):
    for prefix, flag in COUNTRY_FLAGS.items():
        if name.startswith(prefix):
            return flag
    return "🌐"

def format_telegram_ip(ip_value):
    return ip_value if ip_value else "N/A"

def send_telegram_ip_report(arm64_reports):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not set. Skipping IP report.")
        return

    cst = timezone(timedelta(hours=8))
    now_str = datetime.now(cst).strftime("%Y-%m-%d %H:%M CST")

    lines = ["📡 <b>ARM64 服务器 IP 清单</b>", "━━━━━━━━━━━━━━━━"]
    for report in arm64_reports:
        flag = get_country_flag(report["name"])
        lines.append(f"{flag} <code>{report['name']}</code>")
        lines.append(f"IPv4 → <code>{format_telegram_ip(report['ipv4'])}</code>")
        lines.append(f"IPv6 → <code>{format_telegram_ip(report['ipv6'])}</code>")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━")

    failed_reports = [report for report in arm64_reports if not report["ipv4"] and not report["ipv6"]]
    if failed_reports:
        lines.append("")
        lines.append("❌ <b>获取失败:</b>")
        for report in failed_reports:
            flag = get_country_flag(report["name"])
            lines.append(f"{flag} <code>{report['name']}</code> → IPv4 / IPv6 均获取失败")

    ipv4_count = sum(1 for report in arm64_reports if report["ipv4"])
    ipv6_count = sum(1 for report in arm64_reports if report["ipv6"])
    lines.append("")
    lines.append(
        f"✅ 共 {len(arm64_reports)} 台 | IPv4 {ipv4_count} 台 | IPv6 {ipv6_count} 台 | ❌ {len(failed_reports)} 台完全失败"
    )
    lines.append(f"⏰ {now_str}")

    message = "\n".join(line for line in lines if line is not None)

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            print("\n[TELEGRAM] IP report sent successfully.")
        else:
            print(f"\n[TELEGRAM FAIL] HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"\n[TELEGRAM ERROR] {e}")

def mask_ip(ip):
    if not ip:
        return str(ip)
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return "***"

    if parsed.version == 4:
        parts = ip.split('.')
        return f"{parts[0]}.{parts[1]}.***.***"

    parts = parsed.exploded.split(':')
    return f"{parts[0]}:{parts[1]}:****:****:****:{parts[-2]}:{parts[-1]}"

def mask_host(host):
    if not host: return str(host)
    parts = host.split('.')
    if len(parts) > 2:
        return f"***.{parts[-2]}.{parts[-1]}"
    elif len(parts) == 2:
        return f"***.{parts[-1]}"
    return "***"

def get_headers(api_key):
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

def get_server_list():
    try:
        print(f"Fetching config from {CONFIG_URL}...")
        resp = requests.get(CONFIG_URL, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Failed to fetch config: {e}")
        return []

def get_extra_monitors_list():
    if not EXTRA_CONFIG_URL:
        return []
    try:
        print(f"Fetching extra config from {EXTRA_CONFIG_URL}...")
        resp = requests.get(EXTRA_CONFIG_URL, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Failed to fetch extra config: {e}")
        return []

def get_cloudflared_binary():
    machine = platform.machine().lower()
    if "aarch64" in machine or "arm64" in machine:
        arch = "arm64"
    else:
        arch = "amd64"
    binary_path = os.path.join("bin", f"cloudflared-linux-{arch}")
    return binary_path

def parse_ip_value(value, version):
    if not value:
        return None
    try:
        parsed = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if parsed.version != version:
        return None
    return str(parsed)

def get_public_ips(ssh_host, cpu_type, server_name=None):
    # Special case: US-GCP俄勒冈 uses ARM64 SSH username despite being amd64
    if server_name == "US-GCP俄勒冈":
        ssh_user = SSH_USERS.get("arm64")
    else:
        ssh_user = SSH_USERS.get(cpu_type)
    if not ssh_user or not SSH_PASS:
        print("Skipping IP fetch: SSH credentials missing.")
        return {"ipv4": None, "ipv6": None}

    cloudflared_bin = get_cloudflared_binary()
    proxy_cmd = f"{cloudflared_bin} access ssh --hostname {ssh_host}"
    remote_cmd = (
        "sh -lc '"
        "ipv4=$(curl -fsS -4 --max-time 10 https://ifconfig.me/ip 2>/dev/null || true); "
        "ipv6=$(curl -fsS -6 --max-time 10 https://ifconfig.me/ip 2>/dev/null || true); "
        "printf \"ipv4=%s\\nipv6=%s\\n\" \"$ipv4\" \"$ipv6\""
        "'"
    )
    cmd = [
        "sshpass", "-p", SSH_PASS,
        "ssh",
        "-o", f"ProxyCommand={proxy_cmd}",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=20",
        f"{ssh_user}@{ssh_host}",
        remote_cmd
    ]

    try:
        print(f"Connecting to {mask_host(ssh_host)} using {cloudflared_bin}...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            ipv4 = None
            ipv6 = None
            for line in result.stdout.splitlines():
                if line.startswith("ipv4="):
                    ipv4 = parse_ip_value(line.split("=", 1)[1], 4)
                elif line.startswith("ipv6="):
                    ipv6 = parse_ip_value(line.split("=", 1)[1], 6)

            if not ipv4 and not ipv6:
                print(f"Invalid IP output from {mask_host(ssh_host)}: {result.stdout.strip()}")
            return {"ipv4": ipv4, "ipv6": ipv6}
        else:
            stderr_masked = result.stderr.replace(ssh_host, mask_host(ssh_host))
            print(f"SSH failed for {mask_host(ssh_host)}: {stderr_masked}")
    except subprocess.TimeoutExpired:
        print(f"SSH timed out for {mask_host(ssh_host)}")
    except Exception as e:
        print(f"Error checking {mask_host(ssh_host)}: {e}")

    return {"ipv4": None, "ipv6": None}

def collect_server_result(server):
    name = server.get("name")
    ssh_host = server.get("ssh_host")
    cpu_type = server.get("cpu_type", "amd64")

    if not name or not ssh_host:
        raise RuntimeError("Server definition must include both 'name' and 'ssh_host'.")

    public_ips = get_public_ips(ssh_host, cpu_type, server_name=name)
    ipv4 = public_ips["ipv4"]
    ipv6 = public_ips["ipv6"]

    if ipv4 and ipv6:
        status = "ok"
    elif ipv4 or ipv6:
        status = "partial"
    else:
        status = "failed"

    return {
        "name": name,
        "cpu_type": cpu_type,
        "ssh_host": ssh_host,
        "ipv4": ipv4,
        "ipv6": ipv6,
        "status": status
    }

def save_json(path, payload):
    output_dir = os.path.dirname(path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as output_file:
        json.dump(payload, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")

def load_collected_results(results_dir):
    result_map = {}
    for path in sorted(glob.glob(os.path.join(results_dir, "*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as result_file:
                payload = json.load(result_file)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Skipping invalid collected result {path}: {exc}")
            continue

        name = payload.get("name")
        if not name:
            print(f"Skipping collected result without server name: {path}")
            continue

        result_map[name] = payload

    return result_map

def get_current_monitors(api_key):
    url = f"{API_BASE}/monitors"
    try:
        resp = requests.get(url, headers=get_headers(api_key))
        data = resp.json()
        if 'data' in data:
            return {m['friendlyName']: m for m in data.get('data', [])}
        else:
            print(f"API Error (Get): {data}")
            return {}
    except Exception as e:
        print(f"Failed to fetch monitors: {e}")
        return {}

def create_monitor(api_key, name, url, interval, alert_contact_id=None):
    api_url = f"{API_BASE}/monitors"
    payload = {
        'friendlyName': name,
        'url': url,
        'type': 'PING', 
        'interval': interval,
        'timeout': 30
    }
    if alert_contact_id:
        payload['assignedAlertContacts'] = [{'alertContactId': alert_contact_id, 'threshold': 0, 'recurrence': 0}]
    try:
        resp = requests.post(api_url, json=payload, headers=get_headers(api_key))
        if resp.status_code in [200, 201]:
            print(f"[CREATED] {name} -> {mask_ip(url)} (interval {interval}s)")
        else:
            print(f"[CREATE FAIL] {name}: HTTP {resp.status_code} | {resp.text[:200]}")
    except Exception as e:
        print(f"[CREATE ERROR] {name}: {e}")

def create_monitor_typed(api_key, name, url, monitor_type, interval, alert_contact_id=None):
    api_url = f"{API_BASE}/monitors"
    payload = {
        'friendlyName': name,
        'url': url,
        'type': monitor_type,
        'interval': interval,
        'timeout': 30
    }
    if alert_contact_id:
        payload['assignedAlertContacts'] = [{'alertContactId': alert_contact_id, 'threshold': 0, 'recurrence': 0}]
    try:
        resp = requests.post(api_url, json=payload, headers=get_headers(api_key))
        if resp.status_code in [200, 201]:
            print(f"[CREATED] {name} -> {url} ({monitor_type}, interval {interval}s)")
        else:
            print(f"[CREATE FAIL] {name}: HTTP {resp.status_code} | {resp.text[:200]}")
    except Exception as e:
        print(f"[CREATE ERROR] {name}: {e}")

def update_monitor(api_key, monitor_id, name, new_url, monitor_type="PING"):
    api_url = f"{API_BASE}/monitors/{monitor_id}"
    payload = {
        'url': new_url,
        'type': monitor_type
    }
    try:
        resp = requests.patch(api_url, json=payload, headers=get_headers(api_key))
        if resp.status_code in [200, 201]:
            print(f"[UPDATED] {name} -> {mask_ip(new_url)}")
            return True
        else:
            print(f"[UPDATE FAIL] {name}: HTTP {resp.status_code} | {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"[UPDATE ERROR] {name}: {e}")
        return False

def delete_monitor(api_key, monitor_id, name):
    api_url = f"{API_BASE}/monitors/{monitor_id}"
    try:
        resp = requests.delete(api_url, headers=get_headers(api_key))
        if resp.status_code in [200, 204]:
            print(f"[DELETED] {name}")
        else:
            print(f"[DELETE FAIL] {name}: HTTP {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"[DELETE ERROR] {name}: {e}")

def bind_alert_contact(api_key, monitor_id, name, alert_contact_id):
    api_url = f"{API_BASE}/monitors/{monitor_id}"
    payload = {
        "assignedAlertContacts": [{"alertContactId": alert_contact_id, "threshold": 0, "recurrence": 0}]
    }
    try:
        resp = requests.patch(api_url, json=payload, headers=get_headers(api_key))
        if resp.status_code in [200, 201]:
            print(f"  [ALERT BOUND] {name}")
        else:
            print(f"  [ALERT FAIL] {name}: HTTP {resp.status_code}")
    except Exception as e:
        print(f"  [ALERT ERROR] {name}: {e}")

def get_cloudflare_scope():
    if CLOUDFLARE_ZONE_ID:
        return "zones", CLOUDFLARE_ZONE_ID
    if CLOUDFLARE_ACCOUNT_ID:
        return "accounts", CLOUDFLARE_ACCOUNT_ID
    return None, None

def cloudflare_is_configured():
    scope_type, scope_id = get_cloudflare_scope()
    has_auth = bool(CLOUDFLARE_API_TOKEN or (CLOUDFLARE_API_EMAIL and CLOUDFLARE_API_KEY))
    return bool(has_auth and scope_type and scope_id)

def cloudflare_auth_header_sets():
    header_sets = []
    headers = {"Content-Type": "application/json"}
    if CLOUDFLARE_API_TOKEN:
        token_headers = dict(headers)
        token_headers["Authorization"] = f"Bearer {CLOUDFLARE_API_TOKEN}"
        header_sets.append(("api_token", token_headers))
    if CLOUDFLARE_API_EMAIL and CLOUDFLARE_API_KEY:
        key_headers = dict(headers)
        key_headers["X-Auth-Email"] = CLOUDFLARE_API_EMAIL
        key_headers["X-Auth-Key"] = CLOUDFLARE_API_KEY
        header_sets.append(("global_key", key_headers))
    if not header_sets:
        raise RuntimeError("Cloudflare credentials are not configured.")
    return header_sets

def cloudflare_request(method, path, payload=None):
    url = f"https://api.cloudflare.com/client/v4{path}"
    auth_attempt_errors = []

    for auth_label, headers in cloudflare_auth_header_sets():
        response = requests.request(
            method,
            url,
            headers=headers,
            json=payload,
            timeout=30
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Cloudflare API returned non-JSON response: HTTP {response.status_code}") from exc

        if response.ok and data.get("success", False):
            if auth_label != "api_token":
                print(f"Cloudflare request {method} {path} succeeded using {auth_label} authentication.")
            return data.get("result")

        errors = data.get("errors", [])
        auth_attempt_errors.append((auth_label, response.status_code, errors))

        auth_error = response.status_code in (401, 403) and any(err.get("code") == 10000 for err in errors)
        if auth_error:
            print(f"Cloudflare {auth_label} authentication failed for {method} {path}. Trying next credential set.")
            continue

        raise RuntimeError(
            f"Cloudflare API error on {method} {path}: HTTP {response.status_code} | "
            f"errors={json.dumps(errors, ensure_ascii=False)}"
        )

    formatted_errors = "; ".join(
        f"{label}: HTTP {status} errors={json.dumps(errors, ensure_ascii=False)}"
        for label, status, errors in auth_attempt_errors
    )
    raise RuntimeError(
        f"Cloudflare API authentication failed for {method} {path} using all configured credential sets. "
        f"Attempts: {formatted_errors}"
    )

def find_cloudflare_target_rule(rules):
    if CLOUDFLARE_RULE_ID:
        for rule in rules:
            if rule.get("id") == CLOUDFLARE_RULE_ID:
                return rule
        raise RuntimeError(f"Cloudflare rule ID not found: {CLOUDFLARE_RULE_ID}")

    matches = [rule for rule in rules if rule.get("description") == CLOUDFLARE_RULE_DESCRIPTION]
    if not matches:
        raise RuntimeError(
            f"Cloudflare rule not found by description: {CLOUDFLARE_RULE_DESCRIPTION}. "
            "Set CLOUDFLARE_RULE_ID if the rule description does not match exactly."
        )
    if len(matches) > 1:
        raise RuntimeError(
            f"Multiple Cloudflare rules matched description: {CLOUDFLARE_RULE_DESCRIPTION}. "
            "Set CLOUDFLARE_RULE_ID to disambiguate."
        )
    return matches[0]

def get_cloudflare_ruleset(scope_type, scope_id, ruleset_id):
    return cloudflare_request("GET", f"/{scope_type}/{scope_id}/rulesets/{ruleset_id}")

def get_cloudflare_entrypoint_ruleset(scope_type, scope_id):
    if CLOUDFLARE_RULESET_ID:
        return get_cloudflare_ruleset(scope_type, scope_id, CLOUDFLARE_RULESET_ID)
    return cloudflare_request(
        "GET",
        f"/{scope_type}/{scope_id}/rulesets/phases/http_request_firewall_custom/entrypoint"
    )

def resolve_cloudflare_target_rule(scope_type, scope_id):
    candidate_rulesets = []
    seen_ruleset_ids = set()

    def add_candidate(ruleset):
        ruleset_id = ruleset.get("id")
        if ruleset_id and ruleset_id not in seen_ruleset_ids:
            seen_ruleset_ids.add(ruleset_id)
            candidate_rulesets.append(ruleset)

    entrypoint_ruleset = get_cloudflare_entrypoint_ruleset(scope_type, scope_id)
    add_candidate(entrypoint_ruleset)

    for rule in entrypoint_ruleset.get("rules", []):
        if rule.get("action") != "execute":
            continue
        child_ruleset_id = rule.get("action_parameters", {}).get("id")
        if not child_ruleset_id or child_ruleset_id in seen_ruleset_ids:
            continue
        try:
            add_candidate(get_cloudflare_ruleset(scope_type, scope_id, child_ruleset_id))
        except RuntimeError as exc:
            print(f"Warning: failed to inspect executed Cloudflare ruleset {child_ruleset_id}: {exc}")

    last_error = None
    for ruleset in candidate_rulesets:
        try:
            return ruleset, find_cloudflare_target_rule(ruleset.get("rules", []))
        except RuntimeError as exc:
            last_error = exc

    if last_error:
        raise last_error
    raise RuntimeError("Cloudflare target rule could not be resolved from any candidate ruleset.")

def sort_ip_key(ip_value):
    parsed = ipaddress.ip_address(ip_value)
    return (parsed.version, int(parsed))

def build_cloudflare_ip_set(ip_values):
    unique_ips = sorted(set(ip_values), key=sort_ip_key)
    if not unique_ips:
        raise RuntimeError("No server IPs were collected; refusing to clear the Cloudflare allowlist rule.")
    return "{ " + " ".join(unique_ips) + " }"

def replace_ip_src_set(expression, ip_set_literal):
    updated_expression, replacements = re.subn(
        r'ip\.src\s+in\s*\{[^{}]*\}',
        f"ip.src in {ip_set_literal}",
        expression,
        count=1,
        flags=re.IGNORECASE | re.DOTALL
    )
    if replacements == 1:
        return updated_expression

    if CLOUDFLARE_RULE_EXPRESSION_TEMPLATE:
        if "__IP_SET__" not in CLOUDFLARE_RULE_EXPRESSION_TEMPLATE:
            raise RuntimeError("CLOUDFLARE_RULE_EXPRESSION_TEMPLATE must contain the __IP_SET__ placeholder.")
        return CLOUDFLARE_RULE_EXPRESSION_TEMPLATE.replace("__IP_SET__", ip_set_literal)

    raise RuntimeError(
        "Could not find an inline 'ip.src in { ... }' set in the existing Cloudflare rule expression. "
        "Provide CLOUDFLARE_RULE_EXPRESSION_TEMPLATE with an __IP_SET__ placeholder if the rule needs full reconstruction."
    )

def build_cloudflare_rule_payload(rule, new_expression):
    payload = {
        "action": rule["action"],
        "expression": new_expression
    }

    for field in (
        "description",
        "enabled",
        "ref",
        "action_parameters",
        "logging",
        "ratelimit",
        "exposed_credential_check"
    ):
        if field in rule:
            payload[field] = rule[field]

    return payload

def update_cloudflare_server_ip_rule(collected_ips):
    if not cloudflare_is_configured():
        print("Cloudflare rule sync not configured. Skipping security rule update.")
        return

    scope_type, scope_id = get_cloudflare_scope()
    ip_set_literal = build_cloudflare_ip_set(collected_ips)
    ruleset, target_rule = resolve_cloudflare_target_rule(scope_type, scope_id)

    current_expression = target_rule.get("expression", "")
    new_expression = replace_ip_src_set(current_expression, ip_set_literal)

    if new_expression == current_expression:
        print("Cloudflare rule expression already matches collected IP set. No action.")
        return

    payload = build_cloudflare_rule_payload(target_rule, new_expression)
    ruleset_path = f"/{scope_type}/{scope_id}/rulesets/{ruleset['id']}"
    update_path = f"{ruleset_path}/rules/{target_rule['id']}"
    cloudflare_request("PATCH", update_path, payload)
    print(
        f"Updated Cloudflare rule '{target_rule.get('description') or target_rule.get('id')}' "
        f"with {len(set(collected_ips))} collected server IPs."
    )

def load_reports_file(path):
    with open(path, "r", encoding="utf-8") as input_file:
        payload = json.load(input_file)
    if not isinstance(payload, list):
        raise RuntimeError(f"Expected a JSON array in {path}.")
    return payload

def collect_arm64_ips_from_reports(reports):
    collected_ips = set()
    for report in reports:
        if report.get("cpu_type", "arm64") != "arm64":
            continue
        for field in ("ipv4", "ipv6"):
            value = report.get(field)
            if not value or str(value).upper() == "N/A":
                continue
            collected_ips.add(str(ipaddress.ip_address(value)))
    return collected_ips

def synchronize_with_results(servers, collected_results):
    require_uptimerobot_api_keys()
    # Auto-discover alert contact IDs
    print("\n=== Discovering Alert Contacts ===")
    alert_contacts = {
        "arm64": get_alert_contact_id(API_KEYS["arm64"]),
        "amd64": get_alert_contact_id(API_KEYS["amd64"])
    }

    config_names_arm64 = {s.get('name') for s in servers if s.get('name') and s.get('cpu_type', 'amd64') == 'arm64'}
    config_names_amd64 = {s.get('name') for s in servers if s.get('name') and s.get('cpu_type', 'amd64') == 'amd64'}

    # Fetch extra static monitors
    extra_monitors = get_extra_monitors_list()
    extra_names_amd64 = {e.get('name') for e in extra_monitors if e.get('name') and e.get('account') == 'amd64'}
    # Merge extra names into amd64 config so they won't be deleted
    config_names_amd64 = config_names_amd64 | extra_names_amd64

    # 1. Process arm64 monitors (cf_555606_xyz)
    print("\n=== Processing ARM64 monitors ===")
    arm64_api_key = API_KEYS["arm64"]
    arm64_monitors = get_current_monitors(arm64_api_key)
    print(f"Found {len(arm64_monitors)} existing arm64 monitors.")
    
    for name, monitor in arm64_monitors.items():
        if name not in config_names_arm64:
            print(f"Monitor {name} not in arm64 config. Deleting...")
            delete_monitor(arm64_api_key, monitor['id'], name)
        elif not monitor.get('assignedAlertContacts') and alert_contacts.get('arm64'):
            print(f"Monitor {name} has no alert contact. Binding...")
            bind_alert_contact(arm64_api_key, monitor['id'], name, alert_contacts['arm64'])
            time.sleep(2)

    # 2. Process amd64 monitors (Xinjiapo_555606_xyz)
    print("\n=== Processing AMD64 monitors ===")
    amd64_api_key = API_KEYS["amd64"]
    amd64_monitors = get_current_monitors(amd64_api_key)
    print(f"Found {len(amd64_monitors)} existing amd64 monitors.")
    
    for name, monitor in amd64_monitors.items():
        if name not in config_names_amd64:
            print(f"Monitor {name} not in amd64 config. Deleting...")
            delete_monitor(amd64_api_key, monitor['id'], name)
        elif not monitor.get('assignedAlertContacts') and alert_contacts.get('amd64'):
            print(f"Monitor {name} has no alert contact. Binding...")
            bind_alert_contact(amd64_api_key, monitor['id'], name, alert_contacts['amd64'])
            time.sleep(2)

    # 3. Synchronize actual servers
    update_failures = 0
    arm64_reports = []
    collected_server_ips = set()
    print("\n=== Synchronizing Server IPs From Collected Results ===")
    for server in servers:
        name = server.get('name')
        ssh_host = server.get('ssh_host')
        cpu_type = server.get('cpu_type', 'amd64')
        
        if not name or not ssh_host:
            continue

        api_key = API_KEYS.get(cpu_type)
        if not api_key:
            print(f"Skipping {name}: Unknown cpu_type {cpu_type}")
            continue
            
        interval = 300 if cpu_type == "arm64" else 600

        print(f"\n--- Applying {name} ({cpu_type}) ---")
        result = collected_results.get(name)
        if result is None:
            print(f"No collected result found for {name}. Treating IPv4/IPv6 as unavailable.")
            public_ipv4 = None
            public_ipv6 = None
        else:
            public_ipv4 = result.get("ipv4")
            public_ipv6 = result.get("ipv6")

        if public_ipv4:
            print(f"Resolved IPv4: {mask_ip(public_ipv4)}")
            if cpu_type == "arm64":
                collected_server_ips.add(public_ipv4)
        else:
            print(f"IPv4 unavailable for {name}.")

        if public_ipv6:
            print(f"Resolved IPv6: {mask_ip(public_ipv6)}")
            if cpu_type == "arm64":
                collected_server_ips.add(public_ipv6)
        else:
            print(f"IPv6 unavailable for {name}.")

        if cpu_type == "arm64":
            arm64_reports.append({
                "name": name,
                "ipv4": public_ipv4,
                "ipv6": public_ipv6
            })

        if not public_ipv4:
            print(f"Could not get IPv4 for {name}. Skipping monitor update.")
            continue

        current_monitors_for_type = arm64_monitors if cpu_type == "arm64" else amd64_monitors

        if name in current_monitors_for_type:
            monitor = current_monitors_for_type[name]
            old_ip = monitor.get('url')
            if old_ip != public_ipv4:
                print(f"IP changed for {name} ({mask_ip(old_ip)} -> {mask_ip(public_ipv4)}). Updating...")
                if not update_monitor(api_key, monitor['id'], name, public_ipv4):
                    update_failures += 1
                time.sleep(2)
            else:
                print(f"IP unchanged for {name}. No action.")
        else:
            print(f"Monitor {name} does not exist. Creating...")
            create_monitor(api_key, name, public_ipv4, interval, alert_contacts.get(cpu_type))
            time.sleep(2)

    # 4. Synchronize extra static monitors (no SSH needed)
    if extra_monitors:
        print("\n=== Synchronizing Extra Static Monitors ===")
        amd64_api_key = API_KEYS["amd64"]
        # Refresh amd64 monitors after dynamic sync
        amd64_monitors = get_current_monitors(amd64_api_key)
        for em in extra_monitors:
            name = em.get('name')
            url = em.get('url')
            monitor_type = em.get('type', 'PING')
            account = em.get('account', 'amd64')

            if not name or not url:
                continue

            api_key = API_KEYS.get(account)
            if not api_key:
                print(f"Skipping extra {name}: Unknown account {account}")
                continue

            print(f"\n--- Extra: {name} ({monitor_type}) ---")
            if name in amd64_monitors:
                monitor = amd64_monitors[name]
                old_url = monitor.get('url')
                if old_url != url:
                    print(f"URL changed for {name}. Updating...")
                    update_monitor(api_key, monitor['id'], name, url)
                    time.sleep(2)
                else:
                    print(f"URL unchanged for {name}. No action.")
            else:
                print(f"Extra monitor {name} does not exist. Creating...")
                create_monitor_typed(api_key, name, url, monitor_type, 600, alert_contacts.get(account))
                time.sleep(2)

    # 5. Update Cloudflare allowlist rule with collected ARM64 server IPs only
    print("\n=== Updating Cloudflare Security Rule ===")
    update_cloudflare_server_ip_rule(collected_server_ips)

    # 6. Send ARM64 IP report to Telegram
    print("\n=== Sending ARM64 IP Report to Telegram ===")
    send_telegram_ip_report(arm64_reports)

    if update_failures > 0:
        print(f"\n⚠ {update_failures} monitor(s) failed to update!")
        exit(1)

def run_full_sync():
    servers = get_server_list()
    if not servers:
        print("No servers found.")
        return

    collected_results = {}
    print("\n=== Collecting Server IPs Directly ===")
    for server in servers:
        name = server.get("name")
        ssh_host = server.get("ssh_host")
        if not name or not ssh_host:
            continue

        cpu_type = server.get("cpu_type", "amd64")
        print(f"\n--- Collecting {name} ({cpu_type}) ---")
        try:
            collected_results[name] = collect_server_result(server)
        except Exception as exc:
            print(f"Collection error for {name}: {exc}")
            collected_results[name] = {
                "name": name,
                "cpu_type": cpu_type,
                "ssh_host": ssh_host,
                "ipv4": None,
                "ipv6": None,
                "status": "failed"
            }

    synchronize_with_results(servers, collected_results)

def run_collect_mode(args):
    server = {
        "name": args.name,
        "cpu_type": args.cpu_type,
        "ssh_host": args.ssh_host
    }
    result = collect_server_result(server)
    save_json(args.output, result)
    print(
        f"Collected {result['name']} ({result['cpu_type']}): "
        f"IPv4={mask_ip(result['ipv4']) if result['ipv4'] else 'N/A'}, "
        f"IPv6={mask_ip(result['ipv6']) if result['ipv6'] else 'N/A'}"
    )

def run_aggregate_mode(args):
    servers = get_server_list()
    if not servers:
        print("No servers found.")
        return

    collected_results = load_collected_results(args.results_dir)
    print(f"Loaded {len(collected_results)} collected server result(s) from {args.results_dir}.")
    synchronize_with_results(servers, collected_results)

def run_manual_cloudflare_mode(args):
    reports = load_reports_file(args.input)
    collected_ips = collect_arm64_ips_from_reports(reports)
    print(f"Loaded {len(reports)} ARM64 report row(s) from {args.input}.")
    print(f"Collected {len(collected_ips)} unique ARM64 IP(s) for Cloudflare update.")
    update_cloudflare_server_ip_rule(collected_ips)

def build_arg_parser():
    parser = argparse.ArgumentParser(description="Sync UptimeRobot monitors and server IP allowlists.")
    subparsers = parser.add_subparsers(dest="command")

    collect_parser = subparsers.add_parser("collect", help="Collect IPv4/IPv6 for a single server.")
    collect_parser.add_argument("--name", required=True, help="Server display name.")
    collect_parser.add_argument("--cpu-type", default="amd64", help="Server CPU type.")
    collect_parser.add_argument("--ssh-host", required=True, help="SSH hostname.")
    collect_parser.add_argument("--output", required=True, help="Output JSON path.")

    aggregate_parser = subparsers.add_parser("aggregate", help="Aggregate collected results and update services.")
    aggregate_parser.add_argument("--results-dir", required=True, help="Directory containing collected JSON result files.")

    manual_cf_parser = subparsers.add_parser(
        "manual-cloudflare",
        help="Update the Cloudflare server-IP rule from a JSON report file."
    )
    manual_cf_parser.add_argument("--input", required=True, help="JSON file containing ARM64 report rows.")

    return parser

def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.command == "collect":
        run_collect_mode(args)
        return

    if args.command == "aggregate":
        run_aggregate_mode(args)
        return

    if args.command == "manual-cloudflare":
        run_manual_cloudflare_mode(args)
        return

    run_full_sync()

if __name__ == "__main__":
    main()
