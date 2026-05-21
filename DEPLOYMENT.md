# NatCat Underwriting Engine — Deployment Guide

This document explains how to deploy the **NatCat Underwriting Engine**
(`underwriting_app/app.py`) on:

1. A local Windows / macOS / Linux machine
2. A self-hosted Linux server (systemd service)
3. Docker / Docker Compose (any host)
4. Streamlit Community Cloud (free)
5. Google Cloud Run (serverless)
6. AWS (EC2 or App Runner)
7. Azure App Service (Python)

The app is a **Streamlit** application backed by **Google Earth Engine
(EE)** and the **Google Places API**, with a local **SQLite** database
(`history.db`) for search history and PDF reports generated via
**ReportLab**.

---

## 1. Prerequisites (all targets)

You will need:

| Item | Purpose | How to get |
|---|---|---|
| **Python 3.10–3.12** | Runtime | python.org / pyenv |
| **Earth Engine account** | Cyclone / Flood / DEM data | https://earthengine.google.com/ |
| **GCP project + service account** *(production)* | Non-interactive EE auth | https://console.cloud.google.com/ |
| **Google Places API key** | Hazardous-POI scan + geocoding | Enable “Places API (New)” in GCP |

### 1.1 Earth Engine authentication modes

The app (in `init_earth_engine`) will work in either mode:

| Mode | When to use | How |
|---|---|---|
| **User OAuth** | Local laptop dev | `earthengine authenticate` once |
| **Service account** | Server / Docker / Cloud Run | Mount JSON key + set `GOOGLE_APPLICATION_CREDENTIALS` |

For a service account:

1. Create the SA in GCP and download its JSON key.
2. Register the SA email at <https://signup.earthengine.google.com/#!/service_accounts>.
3. Either:
   - place the JSON file at a known path and set
     `GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json`, or
   - paste the JSON inside `.streamlit/secrets.toml` (see
     `.streamlit/secrets.toml.example`).

---

## 2. Required files

After our latest changes the app folder must contain:

```
underwriting_app/
├── app.py                  # main Streamlit app
├── history_db.py           # SQLite persistence (new)
├── pdf_report.py           # ReportLab PDF generator (new)
├── risk_dashboard.py
├── update_stfi_excel.py
├── requirements.txt        # incl. reportlab, openpyxl
├── Dockerfile              # new
├── docker-compose.yml      # new
├── .dockerignore           # new
└── .streamlit/
    ├── config.toml         # optional UI settings
    ├── secrets.toml        # ← provided per environment, NOT in git
    └── secrets.toml.example
```

---

## 3. Local installation (Windows / macOS / Linux)

### 3.1 Windows (PowerShell)

```powershell
cd 'F:\Cyclone and Flood\underwriting_app'
python -m venv flood
.\flood\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt

# One-time: authenticate Earth Engine for this user
earthengine authenticate

# (Optional) put your Places API key in .streamlit\secrets.toml
streamlit run app.py
```

App opens at **http://localhost:8501**.

### 3.2 macOS / Linux

```bash
cd underwriting_app
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
earthengine authenticate
streamlit run app.py
```

### 3.3 Pinning the port / address

```bash
streamlit run app.py --server.port 8080 --server.address 0.0.0.0
```

---

## 4. Self-hosted Linux server (systemd)

Use this for a dedicated VM (DigitalOcean, Hetzner, on-prem).

```bash
sudo useradd -r -m -s /usr/sbin/nologin natcat
sudo mkdir -p /opt/natcat && sudo chown -R natcat:natcat /opt/natcat
sudo -u natcat git clone <your-repo-url> /opt/natcat/app
cd /opt/natcat/app/underwriting_app
sudo -u natcat python3 -m venv /opt/natcat/venv
sudo -u natcat /opt/natcat/venv/bin/pip install -r requirements.txt
```

Place the EE service-account key at
`/opt/natcat/secrets/ee-sa.json` (chmod 600, owned by `natcat`).

Create `/etc/systemd/system/natcat.service`:

```ini
[Unit]
Description=NatCat Underwriting Engine (Streamlit)
After=network.target

[Service]
Type=simple
User=natcat
Group=natcat
WorkingDirectory=/opt/natcat/app/underwriting_app
Environment="GOOGLE_APPLICATION_CREDENTIALS=/opt/natcat/secrets/ee-sa.json"
Environment="NATCAT_DB_PATH=/opt/natcat/data/history.db"
Environment="STREAMLIT_SERVER_HEADLESS=true"
Environment="STREAMLIT_BROWSER_GATHERUSAGESTATS=false"
ExecStart=/opt/natcat/venv/bin/streamlit run app.py \
          --server.port 8501 --server.address 127.0.0.1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo mkdir -p /opt/natcat/data && sudo chown natcat:natcat /opt/natcat/data
sudo systemctl daemon-reload
sudo systemctl enable --now natcat
sudo systemctl status natcat
```

### 4.1 Reverse proxy with HTTPS (nginx)

```nginx
server {
    listen 443 ssl http2;
    server_name natcat.example.com;
    ssl_certificate     /etc/letsencrypt/live/natcat.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/natcat.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;   # streamlit uses long-lived websockets
    }
}
```

Get a cert: `sudo certbot --nginx -d natcat.example.com`.

---

## 5. Docker

A `Dockerfile`, `docker-compose.yml` and `.dockerignore` are included.

### 5.1 Build and run with Docker

```bash
cd underwriting_app
docker build -t natcat-underwriting .

docker run --rm -p 8501:8501 \
  -v "$(pwd)/.streamlit:/app/.streamlit:ro" \
  -v natcat-data:/app/data \
  -e GOOGLE_APPLICATION_CREDENTIALS=/app/.streamlit/ee-service-account.json \
  natcat-underwriting
```

Open **http://localhost:8501**. The named volume `natcat-data` keeps
`history.db` between container restarts (`NATCAT_DB_PATH=/app/data/history.db`).

### 5.2 Docker Compose

```bash
cd underwriting_app
# Drop your EE JSON key as .streamlit/ee-service-account.json
# Drop your Places key as .streamlit/secrets.toml
docker compose up -d --build
docker compose logs -f
```

Stop: `docker compose down`. Wipe history: `docker volume rm underwriting_app_natcat-data`.

---

## 6. Streamlit Community Cloud (free, easiest)

1. Push your repo to GitHub.
2. Go to <https://share.streamlit.io>, click **New app**.
3. **Repository:** your repo • **Branch:** main • **Main file:**
   `underwriting_app/app.py`.
4. Under **Advanced settings → Python version** pick 3.11.
5. **Secrets** — paste the contents of your local `secrets.toml`,
   including the EE service-account JSON.
6. Click **Deploy**.

Notes & limits:

- Community Cloud uses an **ephemeral filesystem** — `history.db` is wiped
  on every redeploy. For persistent history use Cloud Run / VM / Docker.
- Earth Engine **must** use a service account on Streamlit Cloud
  (interactive `earthengine authenticate` is unavailable).
- Apps sleep after inactivity; cold start is 30–60 s.

---

## 7. Google Cloud Run (serverless)

Cloud Run is the smoothest production option because EE and Places live
in the same GCP project.

```bash
# 1. Build & push the image
gcloud auth configure-docker
docker build -t gcr.io/$PROJECT_ID/natcat-underwriting underwriting_app
docker push gcr.io/$PROJECT_ID/natcat-underwriting

# 2. Create a service account + grant EE access
gcloud iam service-accounts create natcat-runner
# (also register its email at https://signup.earthengine.google.com)

# 3. Deploy
gcloud run deploy natcat-underwriting \
  --image gcr.io/$PROJECT_ID/natcat-underwriting \
  --service-account natcat-runner@$PROJECT_ID.iam.gserviceaccount.com \
  --region asia-south1 \
  --platform managed \
  --allow-unauthenticated \
  --port 8501 \
  --cpu 1 --memory 1Gi \
  --min-instances 0 --max-instances 5 \
  --timeout 3600 \
  --session-affinity \
  --set-env-vars NATCAT_DB_PATH=/tmp/history.db \
  --set-secrets GOOGLE_PLACES_API_KEY=natcat-places-key:latest
```

Important Cloud Run notes:

- `--session-affinity` is **required** because Streamlit uses websockets.
- Cloud Run has a **read-only filesystem** except `/tmp`. The history DB
  is therefore ephemeral per instance. For durable history, switch
  `history_db.py` to **Cloud SQL (Postgres)** or **Firestore** (use
  `NATCAT_DB_PATH` only as a local cache).
- EE auth uses the bound service account automatically — no JSON file
  needs to be mounted.

### 7.1 Custom domain & HTTPS

```bash
gcloud run domain-mappings create \
  --service natcat-underwriting --domain natcat.example.com \
  --region asia-south1
```

---

## 8. AWS

### 8.1 EC2 (cheapest, full control)

1. Launch an Ubuntu 22.04 t3.small (or larger).
2. SSH in and follow **§4 (systemd)** verbatim.
3. Open port 443 in the security group; point Route 53 at the EC2 IP.

### 8.2 AWS App Runner (managed containers)

```bash
# Push the image to ECR
aws ecr create-repository --repository-name natcat-underwriting
aws ecr get-login-password | docker login --username AWS --password-stdin \
    <acct>.dkr.ecr.<region>.amazonaws.com
docker tag natcat-underwriting:latest \
    <acct>.dkr.ecr.<region>.amazonaws.com/natcat-underwriting:latest
docker push <acct>.dkr.ecr.<region>.amazonaws.com/natcat-underwriting:latest
```

Console → App Runner → Create service:

- Source: ECR image above
- **Port:** 8501
- **CPU/Memory:** 1 vCPU / 2 GB
- **Environment variables:**
  - `GOOGLE_APPLICATION_CREDENTIALS=/app/.streamlit/ee-sa.json`
  - `NATCAT_DB_PATH=/tmp/history.db`
- **Secrets:** mount `secrets.toml` via AWS Secrets Manager.

App Runner gives you HTTPS + a custom domain out of the box. Like Cloud
Run, the filesystem is ephemeral — use **RDS Postgres** for durable
history if needed (see §10).

---

## 9. Azure App Service (Python)

```bash
az login
az group create -n natcat-rg -l centralindia
az appservice plan create -g natcat-rg -n natcat-plan --sku B1 --is-linux
az webapp create -g natcat-rg -p natcat-plan -n natcat-uw \
    --runtime "PYTHON:3.11" \
    --deployment-local-git

# Configure startup command
az webapp config set -g natcat-rg -n natcat-uw \
    --startup-file "streamlit run app.py --server.port 8000 --server.address 0.0.0.0"

# Configure env vars / secrets
az webapp config appsettings set -g natcat-rg -n natcat-uw --settings \
    GOOGLE_PLACES_API_KEY=$KEY \
    NATCAT_DB_PATH=/home/data/history.db \
    WEBSITES_PORT=8000

# Deploy
git remote add azure <local-git-url-from-create>
git push azure main
```

Azure App Service serves `/home/` as a persistent mount, so
`NATCAT_DB_PATH=/home/data/history.db` survives restarts.

---

## 10. Production hardening checklist

| Concern | Recommendation |
|---|---|
| **HTTPS** | Always terminate TLS (Cloud Run/App Runner do this for you; otherwise nginx + certbot). |
| **Auth** | Streamlit has no built-in auth. Put it behind **IAP** (GCP), **Cognito** (AWS), **Azure AD**, or **oauth2-proxy**. |
| **Secrets** | Never bake API keys into the image. Use Secret Manager / AWS Secrets / Azure Key Vault, mounted as env vars or files. |
| **Quotas** | Set Places API + EE quotas per project; enable budget alerts. |
| **Persistent history** | For multi-instance / serverless, swap SQLite for Postgres. The only file to change is `history_db.py` (replace `sqlite3.connect` with `psycopg2.connect`); the schema is identical. |
| **Backups** | If you keep SQLite, snapshot the volume (`/app/data` or `/opt/natcat/data`) nightly. |
| **Logs** | Streamlit logs to stdout — wired automatically into Cloud Run / App Runner / Azure / `journalctl`. |
| **Resource sizing** | Start with 1 vCPU / 1–2 GB RAM. EE queries are network-bound, not CPU-bound. |
| **Cold starts** | On Cloud Run set `--min-instances 1` for snappy response (costs ~₹1–2k/mo). |
| **CSP / X-Frame** | If embedding in an iframe, set `server.enableCORS = false` and `server.enableXsrfProtection = false` in `.streamlit/config.toml` (only behind your own auth). |

---

## 11. Environment variables reference

| Variable | Default | Purpose |
|---|---|---|
| `NATCAT_DB_PATH` | `<app>/history.db` | Path of the SQLite history DB |
| `GOOGLE_APPLICATION_CREDENTIALS` | – | Path to EE service-account JSON |
| `GOOGLE_PLACES_API_KEY` | – | Read by `get_places_api_key()`; can also be set via `secrets.toml` |
| `STREAMLIT_SERVER_PORT` | `8501` | Listening port |
| `STREAMLIT_SERVER_ADDRESS` | `localhost` | Bind address; set to `0.0.0.0` in containers |
| `STREAMLIT_SERVER_HEADLESS` | `false` | `true` in production (no browser auto-open) |
| `STREAMLIT_BROWSER_GATHERUSAGESTATS` | `true` | `false` to disable telemetry |

---

## 12. Smoke test after deployment

1. Open the app URL.
2. Sidebar → search **Mumbai** → click **🔍 Run Risk Assessment**.
3. Confirm the dashboard shows non-zero Cyclone / Flood / DEM scores.
4. Open **📜 History** → the run should appear; click **📕 Download PDF
   for this Record** → PDF downloads.
5. Open **📄 Report** → click **📕 Download Report (PDF)** → PDF
   downloads.
6. *(optional)* In **🏭 Hazard Proximity (POI)**, paste your Places key
   and run **Scan Nearby Hazards**.

If all four steps work, the deployment is healthy.

---

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `EEException: Please authorize access` | EE not authenticated | Run `earthengine authenticate` (local) or set `GOOGLE_APPLICATION_CREDENTIALS` (server). |
| `EEException: User does not have permission` | SA not registered with EE | Register the SA email at <https://signup.earthengine.google.com/#!/service_accounts>. |
| `403 PERMISSION_DENIED` from Places | API not enabled or wrong key | Enable **Places API (New)** in GCP, restrict the key to that API. |
| Streamlit shows blank page on Cloud Run | Missing session affinity | Redeploy with `--session-affinity`. |
| `history.db` empty after restart | Ephemeral filesystem | Mount a persistent volume or migrate to Postgres (§10). |
| `ModuleNotFoundError: reportlab` | Old image | Rebuild after pulling the latest `requirements.txt`. |
| 502 from nginx | WebSocket timeout | Add `proxy_read_timeout 86400;` (§4.1). |
