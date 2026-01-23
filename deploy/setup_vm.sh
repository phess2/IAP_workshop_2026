#!/bin/bash
# VM setup script - runs on the VM to install system dependencies

set -e

echo "🚀 Setting up VM for FastAPI deployment..."

# Update package list
echo "📦 Updating package list..."
sudo apt-get update -y

# Install Python 3.11+ and pip if not already installed
echo "🐍 Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "Installing Python 3..."
    sudo apt-get install -y python3 python3-pip python3-venv
else
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
    echo "Python $PYTHON_VERSION found"
fi

# Install SQLite3 (usually pre-installed, but ensure it's there)
echo "💾 Checking SQLite installation..."
if ! command -v sqlite3 &> /dev/null; then
    echo "Installing SQLite3..."
    sudo apt-get install -y sqlite3
else
    echo "SQLite3 already installed"
fi

# Install curl and wget for downloading
echo "📥 Installing utilities..."
sudo apt-get install -y curl wget

# Install uv (Python package manager)
echo "📦 Installing uv package manager..."
if ! command -v uv &> /dev/null && [ ! -f "$HOME/.local/bin/uv" ] && [ ! -f "$HOME/.cargo/bin/uv" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    echo "✅ uv installed"
else
    echo "✅ uv already installed"
fi

# Create application directory
APP_DIR="/opt/iap-workshop"
echo "📁 Creating application directory: $APP_DIR"
sudo mkdir -p $APP_DIR
sudo chown $USER:$USER $APP_DIR

# Create data directory for SQLite
DATA_DIR="$APP_DIR/data"
echo "📁 Creating data directory: $DATA_DIR"
mkdir -p $DATA_DIR

# Create logs directory
LOGS_DIR="$APP_DIR/logs"
echo "📁 Creating logs directory: $LOGS_DIR"
mkdir -p $LOGS_DIR

echo "✅ VM setup complete!"
echo ""
echo "Next steps:"
echo "1. Copy your project files to $APP_DIR"
echo "2. Install Python dependencies with: cd $APP_DIR && uv sync"
echo "3. Set up systemd service"
echo "4. Start the service"
