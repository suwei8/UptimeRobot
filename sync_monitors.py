import os
import requests
import json
import subprocess
import time
import platform
import sys

# Configuration
CONFIG_URL = os.getenv("HOSTS_CONFIG_URL")

API_KEYS = {
    "arm64": os.getenv("CF_555606_XYZ_MAIN_API_KEY"),
    "amd64": os.getenv("XINJIAPO_555606_XYZ_MAIN_API_KEY")
}

SSH_USER = os.getenv("SSH_USERNAME")
SSH_PASS = os.getenv("SSH_PASSWORD")

# API V3 configuration
API_BASE = "https://api.uptimerobot.com/v3"

if not API_KEYS["arm64"] or not API_KEYS["amd64"]:
    print("Error: One or both Main_API_keys not set.")
    exit(1)

def mask_ip(ip):
    if not ip: return str(ip)
    parts = ip.split('.')
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.***.***"
    return "***.***.***.***"

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

def get_cloudflared_binary():
    machine = platform.machine().lower()
    if "aarch64" in machine or "arm64" in machine:
        arch = "arm64"
    else:
        arch = "amd64"
    binary_path = os.path.join("bin", f"cloudflared-linux-{arch}")
    return binary_path

def get_public_ip(ssh_host, cpu_type_ignored):
    if not SSH_USER or not SSH_PASS:
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
        f"{SSH_USER}@{ssh_host}",
        "curl -s -4 ifconfig.me"
    ]

    try:
        print(f"Connecting to {ssh_host} using {cloudflared_bin}...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        if result.returncode == 0:
            ip = result.stdout.strip()
            if len(ip.split('.')) == 4:
                return ip
            else:
                print(f"Invalid IP from {ssh_host}: {ip}")
        else:
            print(f"SSH failed for {ssh_host}: {result.stderr}")
    except subprocess.TimeoutExpired:
        print(f"SSH timed out for {ssh_host}")
    except Exception as e:
        print(f"Error checking {ssh_host}: {e}")
    
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

def create_monitor(api_key, name, url, interval):
    api_url = f"{API_BASE}/monitors"
    payload = {
        'friendlyName': name,
        'url': url,
        'type': 'PING', 
        'interval': interval,
        'timeout': 30
    }
    try:
        resp = requests.post(api_url, json=payload, headers=get_headers(api_key))
        data = resp.json()
        if data.get('stat') == 'ok':
            print(f"[CREATED] {name} -> {mask_ip(url)} (interval {interval}s)")
        else:
            print(f"[CREATE FAIL] {name}: {data.get('error')} | Response: {resp.text}")
    except Exception as e:
        print(f"[CREATE ERROR] {name}: {e}")

def update_monitor(api_key, monitor_id, name, new_url):
    api_url = f"{API_BASE}/monitors/{monitor_id}"
    payload = {
        'url': new_url
    }
    try:
        resp = requests.patch(api_url, json=payload, headers=get_headers(api_key))
        data = resp.json()
        if data.get('stat') == 'ok':
            print(f"[UPDATED] {name} -> {mask_ip(new_url)}")
        else:
            print(f"[UPDATE FAIL] {name}: {data.get('error')}")
    except Exception as e:
        print(f"[UPDATE ERROR] {name}: {e}")

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

def main():
    servers = get_server_list()
    if not servers:
        print("No servers found.")
        return

    config_names_arm64 = {s.get('name') for s in servers if s.get('name') and s.get('cpu_type', 'amd64') == 'arm64'}
    config_names_amd64 = {s.get('name') for s in servers if s.get('name') and s.get('cpu_type', 'amd64') == 'amd64'}

    # 1. Process arm64 monitors (cf_555606_xyz)
    print("\n=== Processing ARM64 monitors ===")
    arm64_api_key = API_KEYS["arm64"]
    arm64_monitors = get_current_monitors(arm64_api_key)
    print(f"Found {len(arm64_monitors)} existing arm64 monitors.")
    
    for name, monitor in arm64_monitors.items():
        if name not in config_names_arm64:
            print(f"Monitor {name} not in arm64 config. Deleting...")
            delete_monitor(arm64_api_key, monitor['id'], name)

    # 2. Process amd64 monitors (Xinjiapo_555606_xyz)
    print("\n=== Processing AMD64 monitors ===")
    amd64_api_key = API_KEYS["amd64"]
    amd64_monitors = get_current_monitors(amd64_api_key)
    print(f"Found {len(amd64_monitors)} existing amd64 monitors.")
    
    for name, monitor in amd64_monitors.items():
        if name not in config_names_amd64:
            print(f"Monitor {name} not in amd64 config. Deleting...")
            delete_monitor(amd64_api_key, monitor['id'], name)

    # 3. Synchronize actual servers
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
        public_ip = get_public_ip(ssh_host, cpu_type)
        
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
                update_monitor(api_key, monitor['id'], name, public_ip)
            else:
                print(f"IP unchanged for {name}. No action.")
        else:
            print(f"Monitor {name} does not exist. Creating...")
            create_monitor(api_key, name, public_ip, interval)

if __name__ == "__main__":
    main()
