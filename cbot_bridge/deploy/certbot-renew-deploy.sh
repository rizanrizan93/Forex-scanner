#!/bin/sh
# Certbot deploy hook: reload only after nginx configuration validation.
# No certificate, private key or environment content is printed.
set -eu
/usr/sbin/nginx -t -q
/bin/systemctl reload nginx
