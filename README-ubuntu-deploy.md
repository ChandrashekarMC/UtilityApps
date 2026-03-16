# Deploying on Ubuntu 22.04 VM

This guide walks through deploying the PersMgr app on a fresh Ubuntu 22.04 VM using Docker and Docker Compose.

---

## 1. Update the system

```bash
sudo apt update && sudo apt upgrade -y
```

---

## 2. Install Docker Engine

```bash
# Install prerequisites
sudo apt install -y ca-certificates curl gnupg lsb-release

# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker and Compose plugin
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Allow current user to run Docker without sudo
sudo usermod -aG docker $USER
newgrp docker

# Verify Docker is running
docker --version
docker compose version
```

---

## 3. Copy the project to the VM

From your Windows machine, copy the project folder to the VM (replace `<vm-ip>` and `<user>` with your VM's IP and username):

```powershell
# On Windows (PowerShell)
scp -r "C:\Users\mcc\deployment\github\MCApps_docker" <user>@<vm-ip>:/home/<user>/MCApps_docker
```

Or on the VM, clone directly from GitHub if the repo is hosted there:

```bash
git clone <your-repo-url> ~/MCApps_docker
cd ~/MCApps_docker
```

---

## 4. Create the `.env` file

```bash
cd ~/MCApps_docker
cp .env.example .env
nano .env
```

Fill in the required values:

```ini
# Generate a strong random key: python3 -c "import secrets; print(secrets.token_hex(32))"
FLASK_SECRET_KEY=<your-long-random-secret>

# Local username/password login (used when Google OAuth is not configured)
PERSONAL_SERVER_USER=mcc
PERSONAL_SERVER_PASSWORD=<your-strong-password>

# Google OAuth (optional — leave blank to use only username/password login)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
PERSONAL_GOOGLE_ALLOWED_EMAILS=

# Optional app portal links
PERSONAL_FINANCE_URL=
PERSONAL_NOTES_URL=
```

> **Security note:** The `mcc` username uses a daily rotating dynamic password (`rak<Mon/Tue/...>esh`).
> Use a different username for standard password login, or leave `mcc` as the only user and rely on the dynamic system.

---

## 5. Build and start the container

```bash
cd ~/MCApps_docker
docker compose up -d --build
```

This will:
- Build the Python 3.11 image
- Install all dependencies (`Flask`, `gunicorn`, `Authlib`)
- Start the app via gunicorn on port `8000`
- Create a persistent Docker volume `persmgr_data` for SQLite DB and uploads

---

## 6. Verify the app is running

```bash
# Check container status
docker compose ps

# View live logs
docker compose logs -f

# Quick HTTP test
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000
# Expected: 302 (redirect to /login)
```

Open in browser: `http://<vm-ip>:8000`

---

## 7. Open the firewall port (if UFW is active)

```bash
sudo ufw allow 8000/tcp
sudo ufw status
```

---

## 8. (Optional) Configure Nginx as a reverse proxy with HTTPS

Install Nginx and Certbot:

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

Create an Nginx site config (replace `yourdomain.com` with your actual domain):

```bash
sudo nano /etc/nginx/sites-available/persmgr
```

Paste:

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

Enable and test:

```bash
sudo ln -s /etc/nginx/sites-available/persmgr /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Get a free TLS certificate:

```bash
sudo certbot --nginx -d yourdomain.com
```

Once issued, Certbot auto-configures HTTPS and sets up auto-renewal.

Update the Google OAuth callback URL in Google Cloud Console to:
`https://yourdomain.com/auth/google/callback`

---

## 9. Auto-start on VM reboot

The `restart: unless-stopped` policy in `docker-compose.yml` ensures the container restarts automatically after the VM reboots. Confirm Docker service is enabled:

```bash
sudo systemctl enable docker
```

---

## 10. Useful management commands

| Task | Command |
|------|---------|
| Stop the app | `docker compose down` |
| Restart the app | `docker compose restart` |
| View logs | `docker compose logs -f` |
| Rebuild after code change | `docker compose up -d --build` |
| View persistent data volume | `docker volume inspect persmgr_data` |
| Backup the SQLite DB | Use the in-app Backup/Restore page at `/backup-restore` |
| Update the app | `git pull && docker compose up -d --build` |

---

## Summary of ports

| Port | Purpose |
|------|---------|
| 8000 | Flask app via gunicorn (direct access) |
| 80   | Nginx HTTP (if reverse proxy is set up) |
| 443  | Nginx HTTPS (after Certbot) |

To fix https issue and to force redirections
1. Ensure DNS is correct first (both names must point to your server IP)
`dig +short chikku.tech A`
`dig +short www.chikku.tech A`

2. Install Nginx + Certbot, open firewall
`sudo apt update`
`sudo apt install -y nginx certbot python3-certbot-nginx`
`sudo ufw allow 80/tcp`
`sudo ufw allow 443/tcp`

3. Create Nginx site (HTTP reverse proxy first)
`sudo tee /etc/nginx/sites-available/taskmgrdock >/dev/null <<'EOF'`
--------------------------------------------------------------
server {
    listen 80;
    listen [::]:80;
    server_name chikku.tech www.chikku.tech;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
EOF
--------------------------------------------------------------
4. Enable site, disable default, reload Nginx
`sudo ln -sf /etc/nginx/sites-available/taskmgrdock /etc/nginx/sites-enabled/taskmgrdock`
`sudo rm -f /etc/nginx/sites-enabled/default`
`sudo nginx -t`
`sudo systemctl reload nginx`

5. Issue TLS cert for both domain names
`sudo certbot --nginx -d chikku.tech -d www.chikku.tech`

6. Replace config with canonical redirect (www -> apex) and HTTPS proxy
`sudo tee /etc/nginx/sites-available/taskmgrdock >/dev/null <<'EOF'`
server {
    listen 80;
    listen [::]:80;
    server_name www.chikku.tech;
    return 301 https://chikku.tech$request_uri;
}

server {
    listen 80;
    listen [::]:80;
    server_name chikku.tech;
    return 301 https://chikku.tech$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name www.chikku.tech;

    ssl_certificate /etc/letsencrypt/live/chikku.tech/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/chikku.tech/privkey.pem;
    include /etc/letsencrypt/ssl-dhparams.pem;

    return 301 https://chikku.tech$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name chikku.tech;

    ssl_certificate /etc/letsencrypt/live/chikku.tech/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt

sudo nginx -t
sudo systemctl reload nginx

7. Verify
`curl -I http://chikku.tech`
`curl -I https://chikku.tech`
`curl -I https://www.chikku.tech`

http://... redirects to https://chikku.tech/...
https://www... redirects to https://chikku.tech/...
https://chikku.tech returns 200 or 302

8. Set Google OAuth redirect URI to exactly this:
https://chikku.tech/auth/google/callback

