#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Define variables
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="pi-led-api"
PORT=8080

echo "🍓 Starting deployment of Pi LED API..."

# 1. Check Python installation
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed." >&2
    exit 1
fi

# 2. Check Raspberry Pi environment (warning only, since we support mock mode)
IS_RPI=false
if [ -f /proc/device-tree/model ] && grep -q -i "raspberry pi" /proc/device-tree/model; then
    IS_RPI=true
    echo "ℹ️  Raspberry Pi detected: $(cat /proc/device-tree/model)"
else
    echo "⚠️  Warning: Raspberry Pi model not detected. Running in Mock/Simulation mode."
fi

# 3. Create virtual environment
echo "📦 Setting up Python virtual environment..."
if [ "$IS_RPI" = true ]; then
    # We must include system site packages to use system-wide pre-installed gpiozero/lgpio
    python3 -m venv "$PROJECT_DIR/venv" --system-site-packages
else
    python3 -m venv "$PROJECT_DIR/venv"
fi

# 4. Install requirements
echo "📥 Installing python packages..."
"$PROJECT_DIR/venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

# 5. Service registration
echo "⚙️ Registering service..."

if command -v pm2 &> /dev/null; then
    echo "✅ PM2 detected. Deploying via PM2..."
    # Stop existing instance if running
    pm2 delete "$SERVICE_NAME" &> /dev/null || true
    # Start using config
    pm2 start "$PROJECT_DIR/ecosystem.config.js"
    pm2 save
    echo "🎉 Service successfully deployed and started under PM2!"
    pm2 status
else
    echo "⚠️ PM2 not found. Generating systemd service file..."
    SYSTEMD_FILE="/etc/systemd/system/$SERVICE_NAME.service"
    
    # Generate systemd file contents
    cat <<EOF > "$PROJECT_DIR/$SERVICE_NAME.service"
[Unit]
Description=Raspberry Pi LED Control API
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port $PORT
Restart=always

[Install]
WantedBy=multi-user.target
EOF

    echo "=========================================================="
    echo "To run this API as a systemd service, run the following commands:"
    echo "  sudo cp $PROJECT_DIR/$SERVICE_NAME.service $SYSTEMD_FILE"
    echo "  sudo systemctl daemon-reload"
    echo "  sudo systemctl enable $SERVICE_NAME"
    echo "  sudo systemctl start $SERVICE_NAME"
    echo "=========================================================="
fi

echo "🎉 Pi LED API deployment complete!"
