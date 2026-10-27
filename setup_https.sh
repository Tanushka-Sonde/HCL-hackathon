#!/bin/bash

set -e

DOMAIN="ragsearch.duckdns.org"
COMPOSE_FILE="docker-compose.prod.yml"
NGINX_CONF="docker/nginx/nginx.conf"

echo "========================================"
echo " Setting up HTTPS for $DOMAIN"
echo "========================================"

# ----------------------------------------
# 1. Check DNS
# ----------------------------------------
echo "[1/8] Checking DNS..."

RESOLVED_IP=$(getent hosts "$DOMAIN" | awk '{print $1}' | head -n1)

if [ -z "$RESOLVED_IP" ]; then
    echo "ERROR: $DOMAIN does not resolve."
    exit 1
fi

echo "DNS resolves to: $RESOLVED_IP"

# ----------------------------------------
# 2. Get current public IP
# ----------------------------------------
PUBLIC_IP=$(curl -4 -s https://checkip.amazonaws.com | tr -d '[:space:]')

echo "EC2 public IP:  $PUBLIC_IP"

if [ "$RESOLVED_IP" != "$PUBLIC_IP" ]; then
    echo "WARNING: DNS IP ($RESOLVED_IP) != EC2 IP ($PUBLIC_IP)"
    echo "Update DuckDNS first."
    exit 1
fi

echo "DNS check passed."

# ----------------------------------------
# 3. Backup Nginx configuration
# ----------------------------------------
echo "[2/8] Backing up Nginx configuration..."

cp "$NGINX_CONF" "${NGINX_CONF}.backup.$(date +%Y%m%d_%H%M%S)"

# ----------------------------------------
# 4. Stop Docker Nginx
# ----------------------------------------
echo "[3/8] Stopping Nginx..."

docker compose -f "$COMPOSE_FILE" stop nginx

# ----------------------------------------
# 5. Obtain Let's Encrypt certificate
# ----------------------------------------
echo "[4/8] Obtaining Let's Encrypt certificate..."

if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
    sudo certbot certonly \
        --standalone \
        --non-interactive \
        --agree-tos \
        --register-unsafely-without-email \
        -d "$DOMAIN"
else
    echo "Certificate already exists. Skipping Certbot."
fi

# ----------------------------------------
# 6. Create certificate directory
# ----------------------------------------
echo "[5/8] Preparing certificate mounts..."

sudo mkdir -p /etc/nginx/ssl

# ----------------------------------------
# 7. Update docker-compose.prod.yml
# ----------------------------------------
echo "[6/8] Updating Docker Compose..."

cp "$COMPOSE_FILE" "${COMPOSE_FILE}.backup.$(date +%Y%m%d_%H%M%S)"

python3 <<'PY'
from pathlib import Path

path = Path("docker-compose.prod.yml")
text = path.read_text()

cert_mount = """      - /etc/letsencrypt/live/ragsearch.duckdns.org/fullchain.pem:/etc/nginx/ssl/fullchain.pem:ro
      - /etc/letsencrypt/live/ragsearch.duckdns.org/privkey.pem:/etc/nginx/ssl/privkey.pem:ro
"""

# Only add the mounts if they don't already exist
if "/etc/nginx/ssl/fullchain.pem" not in text:
    marker = "      - ./docker/nginx/nginx.conf:/etc/nginx/nginx.conf:ro"

    if marker not in text:
        raise SystemExit("Could not find Nginx config volume in docker-compose.prod.yml")

    text = text.replace(
        marker,
        marker + "\n" + cert_mount.rstrip()
    )

path.write_text(text)
PY

# ----------------------------------------
# 8. Replace Nginx HTTP server with HTTPS
# ----------------------------------------
echo "[7/8] Updating Nginx configuration..."

python3 <<'PY'
from pathlib import Path

path = Path("docker/nginx/nginx.conf")
text = path.read_text()

old = """    server {
        listen 80;
        server_name localhost;

        location /metrics {
            deny all;
            return 404;
        }

        location /api/ {
            proxy_pass http://api;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            proxy_connect_timeout 60s;
            proxy_send_timeout 300s;
            proxy_read_timeout 300s;
        }

        location / {
            proxy_pass http://frontend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            proxy_connect_timeout 60s;
            proxy_send_timeout 300s;
            proxy_read_timeout 300s;
        }
    }
"""

new = """    # HTTP -> HTTPS
    server {
        listen 80;
        server_name ragsearch.duckdns.org;

        return 301 https://$host$request_uri;
    }

    # HTTPS
    server {
        listen 443 ssl;
        server_name ragsearch.duckdns.org;

        ssl_certificate /etc/nginx/ssl/fullchain.pem;
        ssl_certificate_key /etc/nginx/ssl/privkey.pem;

        ssl_protocols TLSv1.2 TLSv1.3;

        location /metrics {
            deny all;
            return 404;
        }

        location /api/ {
            proxy_pass http://api;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            proxy_connect_timeout 60s;
            proxy_send_timeout 300s;
            proxy_read_timeout 300s;
        }

        location / {
            proxy_pass http://frontend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            proxy_connect_timeout 60s;
            proxy_send_timeout 300s;
            proxy_read_timeout 300s;
        }
    }
"""

if old not in text:
    raise SystemExit(
        "Expected Nginx server configuration was not found. "
        "Nothing was changed in nginx.conf."
    )

path.write_text(text.replace(old, new))
PY

# ----------------------------------------
# Validate configuration
# ----------------------------------------
echo "[8/8] Validating and restarting..."

docker compose -f "$COMPOSE_FILE" up -d nginx

sleep 3

if ! docker exec ai_research_platform-nginx-1 nginx -t; then
    echo ""
    echo "Nginx configuration test FAILED."
    echo "Restoring previous configuration..."

    cp "$(ls -t ${NGINX_CONF}.backup.* | head -n1)" "$NGINX_CONF"

    docker compose -f "$COMPOSE_FILE" restart nginx

    exit 1
fi

echo ""
echo "========================================"
echo " HTTPS setup completed!"
echo "========================================"
echo ""
echo "Open:"
echo "https://$DOMAIN"
echo ""
echo "HTTP should redirect to HTTPS."
echo ""
echo "Checking HTTPS..."
curl -I "https://$DOMAIN" || true
