# Home Server Control Bot (Aiogram v3)

A powerful, secure Telegram bot for managing a Debian-based home server (OpenMediaVault). Built with Python and Aiogram v3, this bot provides real-time monitoring, Docker management, and system control directly from your chat.

## ✨ Features

- **System Dashboard:** Real-time CPU, RAM, Disk usage, Uptime, and Temperatures (CPU & NVMe/SATA).
    
- **Power Monitoring:** Integrates with **Shelly Plug S** to show live power draw, voltage, total energy consumption, and estimated costs.
    
- **Docker Manager:** View running containers with clickable links to their Web UIs (auto-mapped ports).
    
- **qBittorrent Integration:** Live download/upload speeds, active torrent counts, Pause All / Resume All button and notifications about completed downloads.
    
- **System Controls:** Remote Reboot and Shutdown.
    
- **Tools & Utilities:**
    
    - **Network:** View Local/Public IPs and sent/received data.
        
    - **Speedtest:** Run Ookla Speedtest on the server remotely.
        
    - **Security:** View recent SSH logins.
        
    - **Maintenance:** One-click `apt autoremove` & `apt clean` and `apt update` & `apt upgrade`.
        
- **Security:** Middleware-based Admin ID locking. The bot ignores all interactions from unauthorized users.
    

## 🛠️ Prerequisites

- **OS:** Debian 12 (Bookworm) / Ubuntu 22.04+ (Tested on Dell OptiPlex 7060 w/ OMV 7)
    
- **Python:** 3.10+
    
- **Hardware:** (Optional) Shelly Plug S for power monitoring.
    

### 1. System Packages

```
sudo apt update
sudo apt install python3-venv lm-sensors smartmontools curl
```

### 2. Official Ookla Speedtest

To use the official speedtest required by this bot, you must install it from Ookla's repository, not the default Debian `speedtest-cli`:

```
curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | sudo bash
sudo apt install speedtest
```

## ⚙️ Installation

1. **Clone the repository & Choose Version:**
    
    This repository contains two versions of the bot depending on your Telegram subscription status.
    
    - **`default-emoji/`**: Uses standard Unicode emojis. Works for all users.
        
    - **`custom-emoji/`**: Uses custom emojis. You can get preferred emojis’ IDs with [@Get Emoji ID](https://t.me/GetEmojiIdBot "null") Bot. **Requires the bot owner to have an active Telegram Premium subscription.**
        
    
    ```
    git clone https://github.com/merrcul/homelab-telegram-bot.git
    cd homelab-telegram-bot
    
    # Choose your preferred version:
    cd default-emoji
    # OR
    cd custom-emoji
    ```
    
2. **Create a Virtual Environment:**
    
    ```
    python3 -m venv venv
    source venv/bin/activate
    ```
    
3. **Install Python Dependencies:**
    
    ```
    pip install aiogram docker psutil python-dotenv qbittorrent-api requests
    ```
    
4. **Configure Environment Variables:** Create a `.env` file in the project root:
    
    ```
    # Telegram
    BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
    ADMIN_ID=123456789
    
    # Integrations
    SHELLY_IP=192.168.1.50
    QBIT_URL=http://localhost:8080
    QBIT_USER=admin
    QBIT_PASS=adminadmin
    
    # Optional
    HDD_UUID=your-disk-uuid-here
    SPEEDTEST_ENABLED=true
    KWH_COST=0.40
    CACHE_DURATION=5
    REQUEST_TIMEOUT=3
    ```
    
    > **Note:** You can create your bot and get your token from [@BotFather](https://t.me/BotFather "null") and your ID from [@Get My ID](https://www.google.com/search?q=https://t.me/GetMyIDBot "null").
    

## ❕ Critical Configuration

### 1. Docker Permissions

Add your user to the `docker` group so the bot can read container stats without sudo:

```
sudo usermod -aG docker $USER
newgrp docker
```

### 2. Sudo Permissions

For the bot to restart the server or manage packages, configure `sudoers`:

1. Run `sudo visudo`.
    
2. Add the following lines at the bottom (replace `youruser` with your actual username):
    
    ```
    youruser ALL=(ALL) NOPASSWD: /usr/sbin/reboot
    youruser ALL=(ALL) NOPASSWD: /usr/sbin/shutdown
    youruser ALL=(ALL) NOPASSWD: /usr/bin/apt-get
    ```
    

### 3. qBittorrent Notifications

To receive "Download Complete" alerts:

1. Open qBittorrent WebUI → **Tools** → **Options** → **Downloads** → **Run external program**.
    
2. Check **"Run on torrent finished"**.
    
3. Enter this command (adjust path to match your setup):
    
    ```
    /config/qbit_notify.sh "%N" "✅ Download Complete: %N"
    ```
    

> **Note:** Since qBittorrent is installed as a container in this setup, create a separate `.env` file containing the `BOT_TOKEN` and `ADMIN_ID`, and place the notification script in a mapped configuration folder that is accessible by the qBittorrent container.

## 🟢 Running the Bot

### Run as Systemd Service (Recommended)

1. Edit `bot.service` in this repo to match your paths and user.
    
2. Copy to systemd:
    
    ```
    sudo cp bot.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now bot.service
    ```
    

### Manual Run

```
source venv/bin/activate
python bot.py
```

## 🔔 Alert Scripts (Push Notifications)

This repo includes Bash scripts for event-driven alerts.

1. **Universal Push Script (`scripts/tg_alert.sh`)**
    
    - Move to `/usr/local/bin/tg_alert.sh`.
        
    - **Edit the script** to point to your `.env` file absolute path.
        
    - Make executable: `sudo chmod +x /usr/local/bin/tg_alert.sh`.
        
2. **Temperature Monitor (`scripts/temp_alert.sh`)**
    
    - Move to `/usr/local/bin/temp_alert.sh` and make executable.
        
    - Add to cron (`crontab -e`) to run every 5 mins:
        
        ```
        */5 * * * * /usr/local/bin/temp_alert.sh
        ```
        
3. **Docker Monitor (`scripts/docker_monitor.sh`)**
    
    - Move to `/usr/local/bin/docker_monitor.sh` and make executable.
        
    - Use the provided `docker-monitor.service` to run it in the background.
