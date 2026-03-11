import os
import requests
import json
import subprocess
import time
import platform
import sys

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

# API V3 configuration
API_BASE = "https://api.uptimerobot.com/v3"

if not API_KEYS["arm64"] or not API_KEYS["amd64"]:
    print("Error: One or both Main_API_keys not set.")
    exit(1)

# V2 API for alert contacts (V3 doesn't support this endpoint)
V2_BASE = "https://api.uptimerobot.com/v2"

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

def mask_ip(ip):
    if not ip: return str(ip)
    parts = ip.split('.')
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.***.***"
    return "***.***.***.***"

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

def get_public_ip(ssh_host, cpu_type, server_name=None):
    # Special case: US-GCP俄勒冈 uses ARM64 SSH username despite being amd64
    if server_name == "US-GCP俄勒冈":
        ssh_user = SSH_USERS.get("arm64")
    else:
        ssh_user = SSH_USERS.get(cpu_type)
    if not ssh_user or not SSH_PASS:
        print("Skipping IP fetch: SSH credentials missing.")
        return None

    cloudflared_bin = get_cloudflared_binary()
    proxy_cmd = f"{cloudflared_bin} access ssh --hostname {ssh_host}"
    cmd = [
        "sshpass", "-p", SSH_PASS,
        "ssh", 
        "-o", f"ProxyCommand={proxy_cmd}",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=20",
        f"{ssh_user}@{ssh_host}",
        "curl -s -4 ifconfig.me"
    ]

    try:
        print(f"Connecting to {mask_host(ssh_host)} using {cloudflared_bin}...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        if result.returncode == 0:
            ip = result.stdout.strip()
            if len(ip.split('.')) == 4:
                return ip
            else:
                print(f"Invalid IP from {mask_host(ssh_host)}: {ip}")
        else:
            stderr_masked = result.stderr.replace(ssh_host, mask_host(ssh_host))
            print(f"SSH failed for {mask_host(ssh_host)}: {stderr_masked}")
    except subprocess.TimeoutExpired:
        print(f"SSH timed out for {mask_host(ssh_host)}")
    except Exception as e:
        print(f"Error checking {mask_host(ssh_host)}: {e}")
    
    return None

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

def main():
    servers = get_server_list()
    if not servers:
        print("No servers found.")
        return

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
    print("\n=== Synchronizing Server IPs ===")
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

        print(f"\n--- Checking {name} ({cpu_type}) ---")
        public_ip = get_public_ip(ssh_host, cpu_type, server_name=name)
        
        if not public_ip:
            print(f"Could not get public IP for {name}. Skipping update.")
            continue

        print(f"Resolved IP: {mask_ip(public_ip)}")

        current_monitors_for_type = arm64_monitors if cpu_type == "arm64" else amd64_monitors

        if name in current_monitors_for_type:
            monitor = current_monitors_for_type[name]
            old_ip = monitor.get('url')
            if old_ip != public_ip:
                print(f"IP changed for {name} ({mask_ip(old_ip)} -> {mask_ip(public_ip)}). Updating...")
                if not update_monitor(api_key, monitor['id'], name, public_ip):
                    update_failures += 1
                time.sleep(2)
            else:
                print(f"IP unchanged for {name}. No action.")
        else:
            print(f"Monitor {name} does not exist. Creating...")
            create_monitor(api_key, name, public_ip, interval, alert_contacts.get(cpu_type))
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

    if update_failures > 0:
        print(f"\n⚠ {update_failures} monitor(s) failed to update!")
        exit(1)

if __name__ == "__main__":
    main()
