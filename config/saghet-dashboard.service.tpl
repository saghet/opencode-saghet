[Unit]
Description=OpenCode-Saghet Control Center (Matrix Protocol)
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 __SAGHET_REPO__/dashboard/server.py --host 127.0.0.1 --port 4780
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
