import os
import requests
import json
import subprocess
import time
import platform
import sys

# Configuration
CONFIG_URL = os.getenv("HOSTS_CONFIG_URL")
UPTIMEROBOT_API_KEY = os.getenv("Main_API_key")
SSH_USER = os.getenv("SSH_USERNAME")
SSH_PASS = os.getenv("SSH_PASSWORD")

# API V3 configuration
API_BASE = "https://api.uptimerobot.com/v3"
HEADERS = {
    "Authorization": f"Bearer {UPTIMEROBOT_API_KEY}",
    "Content-Type": "application/json"
}

if not UPTIMEROBOT_API_KEY:
    print("Error: Main_API_key not set.")
    exit(1)

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
    """
    Determines which cloudflared binary to use based on the LOCAL system architecture.
    The ProxyCommand runs on the Runner (Client), not the Target Server.
    """
    machine = platform.machine().lower()
    
    # Map platform.machine() to our binary suffix
    if "aarch64" in machine or "arm64" in machine:
        arch = "arm64"
    else:
        # Default to amd64 for x86_64, amd64, etc.
        arch = "amd64"
    
    # Path relative to the script/repo root
    binary_path = os.path.join("bin", f"cloudflared-linux-{arch}")
    return binary_path

def get_public_ip(ssh_host, cpu_type_ignored):
    if not SSH_USER or not SSH_PASS:
        print("Skipping IP fetch: SSH credentials missing.")
        return None

    # We use local architecture for the proxy binary, unrelated to target cpu_type
    cloudflared_bin = get_cloudflared_binary()
    
    # Using ProxyCommand with specific binary
    # Note: We must ensure the binary is executable (chmod +x handled in workflow)
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

def get_current_monitors():
    url = f"{API_BASE}/monitors"
    try:
        resp = requests.get(url, headers=HEADERS)
        data = resp.json()
        if data.get('stat') == 'ok':
            return {m['friendly_name']: m for m in data.get('monitors', [])}
        else:
            print(f"API Error (Get): {data}")
            return {}
    except Exception as e:
        print(f"Failed to fetch monitors: {e}")
        return {}

def create_monitor(name, url):
    api_url = f"{API_BASE}/monitors"
    # V3 Payload: friendlyName (camelCase), type (string enum)
    payload = {
        'friendlyName': name,
        'url': url,
        'type': 'PING', 
        'interval': 300 
    }
    
    try:
        resp = requests.post(api_url, json=payload, headers=HEADERS)
        data = resp.json()
        if data.get('stat') == 'ok':
            print(f"[CREATED] {name} -> {url}")
        else:
            print(f"[CREATE FAIL] {name}: {data.get('error')}")
    except Exception as e:
        print(f"[CREATE ERROR] {name}: {e}")

def update_monitor(monitor_id, name, new_url):
    api_url = f"{API_BASE}/monitors/{monitor_id}"
    payload = {
        'url': new_url
    }
    
    try:
        resp = requests.patch(api_url, json=payload, headers=HEADERS)
        data = resp.json()
        if data.get('stat') == 'ok':
            print(f"[UPDATED] {name} -> {new_url}")
        else:
            print(f"[UPDATE FAIL] {name}: {data.get('error')}")
    except Exception as e:
        print(f"[UPDATE ERROR] {name}: {e}")

def main():
    servers = get_server_list()
    if not servers:
        print("No servers found.")
        return

    current_monitors = get_current_monitors()
    print(f"Found {len(current_monitors)} existing monitors.")

    for server in servers:
        name = server.get('name')
        ssh_host = server.get('ssh_host')
        cpu_type = server.get('cpu_type', 'amd64')
        
        if not name or not ssh_host:
            continue

        print(f"--- Processing {name} ({cpu_type}) ---")
        public_ip = get_public_ip(ssh_host, cpu_type)
        
        if not public_ip:
            print(f"Could not get public IP for {name}. Skipping update.")
            continue

        print(f"Resolved IP: {public_ip}")

        if name in current_monitors:
            monitor = current_monitors[name]
            old_ip = monitor.get('url')
            if old_ip != public_ip:
                print(f"IP changed for {name} ({old_ip} -> {public_ip}). Updating...")
                update_monitor(monitor['id'], name, public_ip)
            else:
                print(f"IP unchanged for {name}. No action.")
        else:
            print(f"Monitor {name} does not exist. Creating...")
            create_monitor(name, public_ip)

if __name__ == "__main__":
    main()
