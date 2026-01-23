#!/bin/bash
# Main deployment script - runs locally to deploy to VM

set -e

# Configuration
VM_NAME="iap-workshop-vm"
ZONE="us-east1-b"
PROJECT="sundai-iap-phess"
APP_DIR="/opt/iap-workshop"
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "🚀 Deploying FastAPI application to VM..."
echo "VM: $VM_NAME"
echo "Zone: $ZONE"
echo "Project: $PROJECT"
echo ""

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "❌ Error: gcloud CLI is not installed"
    echo "Please install Google Cloud SDK: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Step 1: Run setup script on VM
echo "📋 Step 1: Setting up VM (installing dependencies)..."
gcloud compute ssh $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT \
    --command="bash -s" < "$LOCAL_DIR/deploy/setup_vm.sh"

# Step 2: Copy project files to VM
echo ""
echo "📦 Step 2: Copying project files to VM..."
# Create a temporary directory structure
TEMP_DIR=$(mktemp -d)
cp -r "$LOCAL_DIR"/* "$TEMP_DIR/" 2>/dev/null || true

# Exclude unnecessary files
rm -rf "$TEMP_DIR/.git" 2>/dev/null || true
rm -rf "$TEMP_DIR/.venv" 2>/dev/null || true
rm -rf "$TEMP_DIR/__pycache__" 2>/dev/null || true
rm -rf "$TEMP_DIR/**/__pycache__" 2>/dev/null || true
rm -rf "$TEMP_DIR/.pytest_cache" 2>/dev/null || true
rm -rf "$TEMP_DIR/.ruff_cache" 2>/dev/null || true
rm -rf "$TEMP_DIR/.mypy_cache" 2>/dev/null || true
rm -f "$TEMP_DIR/.env" 2>/dev/null || true

# Copy to VM
gcloud compute scp \
    --recurse \
    --zone=$ZONE \
    --project=$PROJECT \
    "$TEMP_DIR"/* \
    $VM_NAME:$APP_DIR/

# Cleanup temp directory
rm -rf "$TEMP_DIR"

# Step 3: Install Python dependencies on VM
echo ""
echo "🐍 Step 3: Installing Python dependencies..."
gcloud compute ssh $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT \
    --command="cd $APP_DIR && if [ ! -f \$HOME/.local/bin/uv ] && [ ! -f \$HOME/.cargo/bin/uv ]; then curl -LsSf https://astral.sh/uv/install.sh | sh; fi && export PATH=\"\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH\" && uv sync"

# Step 4: Initialize database
echo ""
echo "💾 Step 4: Initializing database..."
gcloud compute ssh $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT \
    --command="cd $APP_DIR && export PATH=\"\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH\" && uv run python -c 'from api.database import init_db; init_db()'"

# Step 5: Set up systemd service
echo ""
echo "⚙️  Step 5: Setting up systemd service..."
# Copy service file
gcloud compute scp \
    --zone=$ZONE \
    --project=$PROJECT \
    "$LOCAL_DIR/deploy/fastapi.service" \
    $VM_NAME:/tmp/fastapi.service

# Get the username on the VM
VM_USER=$(gcloud compute ssh $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT \
    --command="whoami" 2>/dev/null | tr -d '\n\r')

# Replace USERNAME_PLACEHOLDER with actual username in service file
gcloud compute ssh $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT \
    --command="sudo sed -i 's/USERNAME_PLACEHOLDER/$VM_USER/g' /tmp/fastapi.service"

# Install service
gcloud compute ssh $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT \
    --command="sudo mv /tmp/fastapi.service /etc/systemd/system/fastapi.service && sudo systemctl daemon-reload"

# Step 6: Verify installation and create .env file if it doesn't exist
echo ""
echo "📝 Step 6: Verifying installation..."
gcloud compute ssh $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT \
    --command="cd $APP_DIR && if [ ! -f .venv/bin/uvicorn ]; then echo '❌ Error: uvicorn not found in .venv'; exit 1; fi && mkdir -p logs && chmod 755 logs && if [ ! -f $APP_DIR/.env ]; then echo '⚠️  Warning: .env file not found. Creating empty .env file...'; touch $APP_DIR/.env; fi && echo '✅ Installation verified'"

# Step 7: Start and enable service
echo ""
echo "🔄 Step 7: Starting FastAPI service..."
gcloud compute ssh $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT \
    --command="sudo systemctl daemon-reload && sudo systemctl enable fastapi.service && sudo systemctl restart fastapi.service"

# Step 8: Check service status
echo ""
echo "📊 Step 8: Checking service status..."
sleep 3
gcloud compute ssh $VM_NAME \
    --zone=$ZONE \
    --project=$PROJECT \
    --command="sudo systemctl status fastapi.service --no-pager -l || (echo '❌ Service failed. Checking logs...' && sudo journalctl -u fastapi.service -n 20 --no-pager)"

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📋 Next steps:"
echo "1. Ensure your .env file is configured at $APP_DIR/.env on the VM"
echo "2. Check service logs: sudo journalctl -u fastapi.service -f"
echo "3. Check application logs: tail -f $APP_DIR/logs/fastapi.log"
echo "4. Test the API: curl http://$(gcloud compute instances describe $VM_NAME --zone=$ZONE --project=$PROJECT --format='get(networkInterfaces[0].accessConfigs[0].natIP)'):8000/health"
echo ""
echo "🔧 Useful commands:"
echo "  - View logs: sudo journalctl -u fastapi.service -f"
echo "  - Restart service: sudo systemctl restart fastapi.service"
echo "  - Stop service: sudo systemctl stop fastapi.service"
echo "  - Check status: sudo systemctl status fastapi.service"
