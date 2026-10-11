#!/usr/bin/python3
"""DuckDNS updater and Certbot DNS-01 hook; credentials never enter argv or logs."""
import os
import re
import stat
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG = Path("/etc/rizan-bridge/duckdns.env")


def load_config():
    info = CONFIG.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError("CREDENTIAL_FILE_PERMISSION_INVALID")
    values = {}
    for line in CONFIG.read_text().splitlines():
        name, separator, value = line.partition("=")
        if separator and name.strip() in {"DUCKDNS_HOSTNAME", "DUCKDNS_TOKEN"}:
            values[name.strip()] = value.strip().strip("'\"")
    host = values.get("DUCKDNS_HOSTNAME", "").lower()
    token = values.get("DUCKDNS_TOKEN", "")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.duckdns\.org", host):
        raise ValueError("DUCKDNS_HOSTNAME_MISSING_OR_INVALID")
    if not re.fullmatch(r"[a-fA-F0-9-]{32,64}", token):
        raise ValueError("DUCKDNS_TOKEN_MISSING_OR_INVALID")
    return host, token


def update(host, token, **fields):
    query = urllib.parse.urlencode({"domains": host.removesuffix(".duckdns.org"),
                                   "token": token, **fields})
    # HTTPS validation stays enabled; request URL and exceptions are never printed.
    with urllib.request.urlopen("https://www.duckdns.org/update?" + query, timeout=30) as response:
        if response.read(100).strip() != b"OK":
            raise ValueError("DUCKDNS_UPDATE_REJECTED")


def main():
    host, token = load_config()
    operation = sys.argv[1]
    if operation == "update":
        update(host, token, ip="")  # DuckDNS sees the VPS's outbound public IPv4.
    elif operation in {"auth", "cleanup"}:
        if os.environ.get("CERTBOT_DOMAIN") != host:
            raise ValueError("CERTBOT_DOMAIN_MISMATCH")
        validation = os.environ.get("CERTBOT_VALIDATION", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,200}", validation):
            raise ValueError("CERTBOT_VALIDATION_INVALID")
        if operation == "cleanup":
            update(host, token, txt="", clear="true")
        else:
            update(host, token, txt=validation)
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                ready = True
                for resolver in ("1.1.1.1", "8.8.8.8"):
                    result = subprocess.run(
                        ["dig", "+short", "+time=3", "+tries=1", "TXT", "_acme-challenge." + host,
                         "@" + resolver], capture_output=True, text=True, timeout=5)
                    ready = ready and validation in {line.strip('"') for line in result.stdout.splitlines()}
                if ready:
                    break
                time.sleep(5)
            else:
                raise ValueError("DNS_PROPAGATION_TIMEOUT")
    elif operation != "check":
        raise ValueError("OPERATION_INVALID")
    print("DUCKDNS_" + operation.upper() + "_OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("DUCKDNS_OPERATION_FAILED", file=sys.stderr)
        sys.exit(1)
