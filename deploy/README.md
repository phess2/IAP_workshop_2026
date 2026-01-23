# Deployment Guide

This directory contains scripts to deploy the FastAPI application with SQLite to the GCP VM.

## Prerequisites

1. Google Cloud SDK (`gcloud`) installed and configured
2. Access to the GCP project `sundai-iap-phess`
3. SSH access to the VM `walker` in zone `us-east1-b`

## Quick Start

Run the deployment script from the project root:

```bash
./deploy/deploy.sh
```

This will:
1. Install system dependencies on the VM (Python, SQLite, uv)
2. Copy project files to `/opt/iap-workshop` on the VM
3. Install Python dependencies using `uv`
4. Initialize the SQLite database
5. Set up and start the systemd service

## Manual Steps

### 1. Configure Environment Variables

After deployment, create a `.env` file on the VM:

```bash
gcloud compute ssh walker --zone=us-east1-b --project=sundai-iap-phess
cd /opt/iap-workshop
nano .env
```

Copy the contents from `env.example` and fill in your actual values.

### 2. Restart the Service

After updating `.env`:

```bash
sudo systemctl restart fastapi.service
```

## Service Management

### Check Service Status
```bash
sudo systemctl status fastapi.service
```

### View Logs
```bash
# Systemd logs
sudo journalctl -u fastapi.service -f

# Application logs
tail -f /opt/iap-workshop/logs/fastapi.log
tail -f /opt/iap-workshop/logs/fastapi.error.log
```

### Restart Service
```bash
sudo systemctl restart fastapi.service
```

### Stop Service
```bash
sudo systemctl stop fastapi.service
```

## API Endpoints

Once deployed, the API will be available at:
- Health check: `http://<VM_IP>:8000/health`
- API docs: `http://<VM_IP>:8000/docs`
- Root: `http://<VM_IP>:8000/`

## Firewall Configuration

Ensure port 8000 is open in the GCP firewall:

```bash
gcloud compute firewall-rules create allow-fastapi \
    --allow tcp:8000 \
    --source-ranges 0.0.0.0/0 \
    --description "Allow FastAPI traffic" \
    --project=sundai-iap-phess
```

## Troubleshooting

### Service won't start
1. Check logs: `sudo journalctl -u fastapi.service -n 50`
2. Verify `.env` file exists and has correct values
3. Check file permissions: `ls -la /opt/iap-workshop`
4. Verify Python environment: `/opt/iap-workshop/.venv/bin/python --version`

### Database issues
1. Check database directory exists: `ls -la /opt/iap-workshop/data`
2. Verify permissions: `ls -la /opt/iap-workshop/data/workshop.db`
3. Test database connection: `sqlite3 /opt/iap-workshop/data/workshop.db ".tables"`

### Connection refused
1. Verify service is running: `sudo systemctl status fastapi.service`
2. Check firewall rules
3. Verify VM has external IP: `gcloud compute instances describe walker --zone=us-east1-b --project=sundai-iap-phess --format='get(networkInterfaces[0].accessConfigs[0].natIP)'`
