"""
Telegram Bot for Home Server Management (Aiogram v3 Version)
Monitors system stats, Docker containers, qBittorrent, and provides remote control
"""

import os
import logging
import asyncio
import socket
import json
import subprocess
import functools
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple, Any, Union, Callable
from datetime import datetime, timedelta
from contextlib import suppress

import requests
import psutil
import docker
import qbittorrentapi
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware
from aiogram.types import (
    Message, 
    CallbackQuery, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    TelegramObject
)
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.client.default import DefaultBotProperties

# --- CONFIGURATION ---
load_dotenv()

@dataclass
class Config:
    """Bot configuration from environment variables"""
    TOKEN: str = os.getenv('BOT_TOKEN')
    ADMIN_ID: int = int(os.getenv('ADMIN_ID', '0'))
    SHELLY_IP: Optional[str] = os.getenv('SHELLY_IP')
    HDD_UUID: Optional[str] = os.getenv('HDD_UUID')
    QBIT_URL: str = os.getenv('QBIT_URL', 'http://localhost:8080')
    QBIT_USER: str = os.getenv('QBIT_USER', 'admin')
    QBIT_PASS: str = os.getenv('QBIT_PASS', 'adminadmin')
    KWH_COST: float = float(os.getenv('KWH_COST', '0.40'))  # €/kWh for power cost estimation
    
    # Optional advanced settings
    SPEEDTEST_ENABLED: bool = os.getenv('SPEEDTEST_ENABLED', 'true').lower() == 'true'
    CACHE_DURATION: int = int(os.getenv('CACHE_DURATION', '5'))  # seconds
    REQUEST_TIMEOUT: int = int(os.getenv('REQUEST_TIMEOUT', '3'))  # seconds

    def validate(self):
        if not self.TOKEN:
            raise ValueError("BOT_TOKEN is missing in .env")
        if self.ADMIN_ID == 0:
            raise ValueError("ADMIN_ID is required for security")

conf = Config()
conf.validate()

# --- LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- UTILITIES ---
async def run_blocking(func: Callable, *args, **kwargs) -> Any:
    """Run blocking code in executor to keep bot responsive"""
    func_call = functools.partial(func, *args, **kwargs)
    return await asyncio.to_thread(func_call)

def format_bytes(bytes_val: float) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} PB"

def format_uptime(seconds: float) -> str:
    uptime = timedelta(seconds=int(seconds))
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"

def get_main_keyboard() -> InlineKeyboardMarkup:
    """Helper to generate the main menu keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Refresh", callback_data='menu_main', icon_custom_emoji_id='5877410604225924969'),
            InlineKeyboardButton(text="Tools", callback_data='menu_tools', icon_custom_emoji_id='5967389567781703494')
        ],
        [
            InlineKeyboardButton(text="Docker", callback_data='menu_docker', icon_custom_emoji_id='5924720918826848520'),
            InlineKeyboardButton(text="qBitT", callback_data='menu_qbit', icon_custom_emoji_id='5879883461711367869')
        ],
        [
            InlineKeyboardButton(text="Processes", callback_data='menu_processes', icon_custom_emoji_id='5936111781981197900'),
            InlineKeyboardButton(text="System", callback_data='menu_system', icon_custom_emoji_id='5877260593903177342')
        ]
    ])

# --- CACHE ---
class SimpleCache:
    def __init__(self):
        self._cache: Dict[str, Tuple[any, datetime]] = {}
    
    def get(self, key: str, max_age_seconds: int = 5) -> Optional[any]:
        if key in self._cache:
            value, timestamp = self._cache[key]
            if datetime.now() - timestamp < timedelta(seconds=max_age_seconds):
                return value
        return None
    
    def set(self, key: str, value: any):
        self._cache[key] = (value, datetime.now())

cache = SimpleCache()

# --- SYSTEM MONITORS ---
class SystemMonitor:
    
    @staticmethod
    def get_all_temperatures() -> Tuple[str, List[str]]:
        cpu_temp = "N/A"
        disk_temps = []
        
        try:
            temps = psutil.sensors_temperatures()
            for name in ['k10temp', 'coretemp', 'cpu_thermal', 'zenpower', 'acpitz']:
                if name in temps and temps[name]:
                    cpu_temp = f"{temps[name][0].current:.1f}°C"
                    break
            
            for name, entries in temps.items():
                if 'nvme' in name.lower() or 'drivetemp' in name.lower():
                    for entry in entries:
                        disk_temps.append(f"{entry.current:.0f}°C")
        except Exception as e:
            logger.debug(f"Temperature read error: {e}")
        
        return cpu_temp, disk_temps
    
    @staticmethod
    def get_updates_info() -> str:
        try:
            subprocess.run(["sudo", "apt-get", "update"], check=True, capture_output=True)
            
            result = subprocess.run(["apt", "list", "--upgradable"], capture_output=True, text=True)
            lines = result.stdout.splitlines()
            
            packages = [line for line in lines if '/' in line and 'Listing...' not in line]
            count = len(packages)
            
            if count == 0:
                return "<tg-emoji emoji-id=\"5427009714745517609\">✅</tg-emoji> <b>System is up to date.</b>"
            
            msg = f"<tg-emoji emoji-id=\"5361979468887893611\">📦</tg-emoji> <b>Updates Available:</b> {count}\n━━━━━━━━━━━━━━━━━━━━━━━━━\n"

            for pkg in packages[:10]:
                name = pkg.split('/')[0]
                msg += f"• {name}\n"
            
            if count > 10:
                msg += f"<i>...and {count - 10} more</i>"
                
            return msg
        except Exception as e:
            return f"<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> Error checking updates: {str(e)[:50]}"
    
    @staticmethod
    def get_uptime() -> str:
        try:
            boot_time = psutil.boot_time()
            uptime_seconds = datetime.now().timestamp() - boot_time
            return format_uptime(uptime_seconds)
        except Exception:
            return "N/A"
    
    @staticmethod
    def get_stats() -> str:
        cached = cache.get('system_stats', conf.CACHE_DURATION)
        if cached:
            return cached
        
        try:
            cpu = psutil.cpu_percent(interval=0.5)
            cpu_temp, disk_temps = SystemMonitor.get_all_temperatures()
            ram = psutil.virtual_memory()
            
            disk_info = []
            with suppress(Exception):
                d1 = psutil.disk_usage('/')
                disk_info.append(('Root', d1))
            
            if conf.HDD_UUID:
                path = f"/srv/dev-disk-by-uuid-{conf.HDD_UUID}"
                if os.path.exists(path):
                    with suppress(Exception):
                        d2 = psutil.disk_usage(path)
                        disk_info.append(('Data', d2))
            
            power_msg = SystemMonitor._get_power_status()
            disk_temp_display = f" ({', '.join(reversed(disk_temps))})" if disk_temps else ""
            uptime = SystemMonitor.get_uptime()
            
            msg = (
                f"<tg-emoji emoji-id=\"5190806721286657692\">📊</tg-emoji> "
                f"<b>System Dashboard</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>Uptime:</b> {uptime}\n"
                f"<b>CPU:</b> {cpu:.1f}%  |  <b>Temp:</b> {cpu_temp}\n"
                f"<b>RAM:</b> {ram.used / (1024**3):.1f} / {ram.total / (1024**3):.1f} GB ({ram.percent:.1f}%)\n"
                f"{power_msg}"
                f"<b>Disks</b>{disk_temp_display}:\n"
            )
            
            for name, d in disk_info:
                msg += f"  • {name}: {d.used / (1024**3):.1f} / {d.total / (1024**3):.1f} GB\n"
            
            cache.set('system_stats', msg)
            return msg
            
        except Exception as e:
            logger.error(f"Error getting system stats: {e}")
            return "<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> Error retrieving system stats"
    
    @staticmethod
    def _get_power_status() -> str:
        if not conf.SHELLY_IP:
            return ""
        try:
            resp = requests.get(
                f"http://{conf.SHELLY_IP}/rpc/Switch.GetStatus?id=0",
                timeout=conf.REQUEST_TIMEOUT
            )
            if resp.status_code == 200:
                watts = resp.json().get('apower', 0)
                return f"<b>Power:</b> {watts:.1f} W\n"
        except Exception:
            pass
        return "<b>Power:</b> N/A\n"

    @staticmethod
    def get_docker_stats() -> str:
        try:
            client = docker.from_env()
            containers = client.containers.list(all=True)
            if not containers:
                return "<tg-emoji emoji-id=\"5431815452437257407\">🐳</tg-emoji> <b>Docker:</b> No containers found."
        except Exception as e:
            return f"<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> Docker API Error: {str(e)[:50]}"
        
        msg = (
            f"<tg-emoji emoji-id=\"5431815452437257407\">🐳</tg-emoji> <b>Docker Containers</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        local_ip = SystemMonitor.get_local_ip()
        
        known_ports = {
            'qbittorrent': 8080, 'jackett': 9117, 'portainer': 9000,
            'plex': 32400, 'sonarr': 8989, 'radarr': 7878,
            'prowlarr': 9696, 'overseerr': 5055, 'tautulli': 8181,
            'jellyfin': 8096, 'transmission': 9091, 'heimdall': 80,
            'grafana': 3000, 'prometheus': 9090
        }
        ignore_links = ['gluetun', 'cloudflared', 'watchtower', 'autoheal']
        
        containers.sort(key=lambda c: (c.status != 'running', c.name.lower()))
        
        for c in containers:
            status_icon = "<tg-emoji emoji-id=\"5465647158935963624\">🟢</tg-emoji>" if c.status == 'running' else "<tg-emoji emoji-id=\"4926956800005112527\">🔴</tg-emoji>"
            name = c.name[:25] + "..." if len(c.name) > 25 else c.name
            
            link = None
            if c.status == 'running' and not any(ignore in name.lower() for ignore in ignore_links):
                for service, port in known_ports.items():
                    if service in name.lower():
                        link = f"http://{local_ip}:{port}"
                        break
                if not link:
                    with suppress(Exception):
                        ports = c.attrs.get('NetworkSettings', {}).get('Ports', {})
                        for _, bindings in ports.items():
                            if bindings and bindings[0].get('HostPort'):
                                link = f"http://{local_ip}:{bindings[0]['HostPort']}"
                                break
            
            if link:
                msg += f"{status_icon} <a href='{link}'><b>{name}</b></a>\n"
            else:
                status_text = f" ({c.status})" if c.status != 'running' else ""
                msg += f"{status_icon} <b>{name}</b>{status_text}\n"
        
        return msg

    @staticmethod
    def get_qbit_client() -> Optional[qbittorrentapi.Client]:
        try:
            qbt = qbittorrentapi.Client(
                host=conf.QBIT_URL,
                username=conf.QBIT_USER,
                password=conf.QBIT_PASS
            )
            qbt.auth_log_in()
            return qbt
        except qbittorrentapi.LoginFailed:
            logger.error("qBittorrent login failed - check credentials")
            return None
        except qbittorrentapi.APIConnectionError as e:
            logger.error(f"qBittorrent connection error: {e}")
            return None
        except Exception as e:
            logger.error(f"qBittorrent client error: {e}")
            return None

    @staticmethod
    def get_qbit_stats() -> Tuple[str, bool, bool]:
        client = SystemMonitor.get_qbit_client()
        if not client:
            return "<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> qBit Connection Error", False, False
            
        try:
            torrents = client.torrents_info()
            transfer = client.transfer_info()
            
            downloading = sum(1 for t in torrents if t.state in ['downloading', 'stalledDL', 'metaDL', 'forcedDL'])
            seeding = sum(1 for t in torrents if t.state in ['uploading', 'stalledUP', 'queuedUP', 'forcedUP'])
            paused = sum(1 for t in torrents if 'paused' in t.state.lower())
            error = sum(1 for t in torrents if 'error' in t.state.lower())
            completed = sum(1 for t in torrents if t.progress >= 1.0)
            
            has_active = (downloading + seeding) > 0
            has_torrents = len(torrents) > 0
            
            dl_speed = format_bytes(transfer.dl_info_speed) + "/s"
            up_speed = format_bytes(transfer.up_info_speed) + "/s"
            
            msg = (
                f"<tg-emoji emoji-id=\"5377535110289576661\">🧲</tg-emoji> <b>qBitTorrent</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"                
                f"<tg-emoji emoji-id=\"5875008416132370818\">⬇️</tg-emoji> {dl_speed} <tg-emoji emoji-id=\"5875078273775439450\">⬆️</tg-emoji> {up_speed}\n"                
                f"<b>Downloading:</b> {downloading}\n"
                f"<b>Seeding:</b> {seeding}\n"
                f"<b>Paused:</b> {paused}\n"
            )
            
            if error > 0:
                msg += f"<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> <b>Errors:</b> {error}\n"
            msg += f"<b>Completed:</b> {completed}/{len(torrents)}"
            return msg, has_active, has_torrents
        except Exception as e:
            return f"<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> qBit Connection Error: {str(e)[:50]}", False, False

    @staticmethod
    def get_local_ip() -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    @staticmethod
    def get_network_info() -> str:
        local = SystemMonitor.get_local_ip()
        try:
            public = requests.get('https://api.ipify.org', timeout=conf.REQUEST_TIMEOUT).text
        except Exception:
            public = "<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> Timeout"
        
        try:
            net = psutil.net_io_counters()
            sent = format_bytes(net.bytes_sent)
            recv = format_bytes(net.bytes_recv)
            usage = f"<b>Sent:</b> {sent}  |  <b>Recv:</b> {recv}\n"
        except Exception:
            usage = ""
        
        return (
            f"<tg-emoji emoji-id=\"5447410659077661506\">📍</tg-emoji> "
            f"<b> IP Info</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Local IP:</b> {local}\n"
            f"<b>External IP:</b> {public}\n"
            f"{usage}"
        )

    @staticmethod
    def run_speedtest() -> str:
        if not conf.SPEEDTEST_ENABLED:
            return "<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> Speedtest is disabled in config"
        
        try:
            cmd = ["speedtest", "--accept-license", "--accept-gdpr", "-f", "json"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode != 0:
                return f"<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> Speedtest Error: {result.stderr[:100]}"
            
            data = json.loads(result.stdout)
            dl_mbps = data['download']['bandwidth'] * 8 / 1_000_000
            ul_mbps = data['upload']['bandwidth'] * 8 / 1_000_000
            ping = data['ping']['latency']
            server = data.get('server', {})
            
            msg = (
                f"<tg-emoji emoji-id=\"5445284980978621387\">🚀</tg-emoji> "
                f"<b> Speedtest Results</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<tg-emoji emoji-id=\"5875008416132370818\">⬇️</tg-emoji>"
                f"<b> Download:</b> {dl_mbps:.1f} Mbps\n"
                f"<tg-emoji emoji-id=\"5875078273775439450\">⬆️</tg-emoji>"
                f"<b> Upload:</b> {ul_mbps:.1f} Mbps\n"
                f"<tg-emoji emoji-id=\"5924681813149618024\">📶</tg-emoji>"
                f"<b> Ping:</b> {ping:.0f} ms\n"
                f"<tg-emoji emoji-id=\"6008135256798927387\">🌐</tg-emoji>"
                f"<b> Server:</b> {server.get('name', 'Unknown')}"
            )
            
            result_url = data.get('result', {}).get('url')
            if result_url:
                msg += f"\n\n<tg-emoji emoji-id=\"5931472654660800739\">📊</tg-emoji> <a href='{result_url}'> View Detailed Results</a>"
            return msg
            
        except subprocess.TimeoutExpired:
            return "<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> Speedtest timed out (>60s)"
        except Exception as e:
            return f"<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> Speedtest Error: {str(e)[:50]}"

    @staticmethod
    def get_power_detail() -> str:
        if not conf.SHELLY_IP:
            return "<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> Shelly IP not configured"
        try:
            resp = requests.get(
                f"http://{conf.SHELLY_IP}/rpc/Switch.GetStatus?id=0",
                timeout=conf.REQUEST_TIMEOUT
            )
            if resp.status_code != 200:
                return f"<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> HTTP Error: {resp.status_code}"
            
            data = resp.json()
            power = data.get('apower', 0)
            voltage = data.get('voltage', 0)
            total_kwh = data.get('aenergy', {}).get('total', 0) / 1000
            temp = data.get('temperature', {}).get('tC', 'N/A')
            
            return (
                f"<tg-emoji emoji-id=\"5199646154823838084\">⚡</tg-emoji> "
                f"<b> Power Monitor</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>Power:</b> {power:.1f} W\n"
                f"<b>Voltage:</b> {voltage:.1f} V\n"
                f"<b>Total Energy:</b> {total_kwh:.2f} kWh\n"
                f"<b>Estimated Costs:</b> {total_kwh * conf.KWH_COST:.2f}€\n"
                f"<b>Plug Temperature:</b> {temp}°C"
            )
        except Exception as e:
            return f"<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> Error: {str(e)[:50]}"
    
    @staticmethod
    def get_process_info() -> str:
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                with suppress(Exception):
                    pinfo = proc.info
                    if pinfo['cpu_percent'] > 0 or pinfo['memory_percent'] > 0:
                        processes.append(pinfo)
            
            top_cpu = sorted(processes, key=lambda x: x['cpu_percent'], reverse=True)[:5]
            top_mem = sorted(processes, key=lambda x: x['memory_percent'], reverse=True)[:5]
            
            msg = (
                f"<tg-emoji emoji-id=\"5190741648237161191\">🔝</tg-emoji> <b>Top Processes</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>By CPU:</b>\n"
            )
            for p in top_cpu:
                msg += f"  • {p['name'][:15]}: {p['cpu_percent']:.1f}%\n"
            
            msg += "\n<b>By Memory:</b>\n"
            for p in top_mem:
                msg += f"  • {p['name'][:15]}: {p['memory_percent']:.1f}%\n"
            
            return msg
        except Exception:
            return "<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> Error retrieving process info"                

# --- MIDDLEWARE ---
class AdminMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Any],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if not user or user.id != conf.ADMIN_ID:
            if user:
                logger.warning(f"⚠️ Unauthorized access attempt: {user.first_name} ({user.id})")
            return
        return await handler(event, data)

# --- ROUTER SETUP ---
router = Router()
router.message.middleware(AdminMiddleware())
router.callback_query.middleware(AdminMiddleware())

# --- MESSAGE HANDLERS ---
@router.message(CommandStart())
async def start_command(message: Message):
    await show_main_menu(message)

async def show_main_menu(message: Union[Message, CallbackQuery]):
    stats = await run_blocking(SystemMonitor.get_stats)
    keyboard = get_main_keyboard()
    
    if isinstance(message, CallbackQuery):
        await safe_edit_message(message, stats, keyboard)
    else:
        await message.answer(stats, reply_markup=keyboard)

async def safe_edit_message(query: CallbackQuery, text: str, reply_markup: Optional[InlineKeyboardMarkup]):
    with suppress(TelegramBadRequest):
        await query.message.edit_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )

# --- CALLBACK HANDLERS ---

@router.callback_query(F.data == 'menu_main')
async def handle_main_menu(query: CallbackQuery):
    await query.answer()
    await show_main_menu(query)

@router.callback_query(F.data.in_({'menu_docker', 'menu_processes'}))
async def handle_modules(query: CallbackQuery):
    await query.answer()
    data = query.data
    
    if data == 'menu_docker':
        text = await run_blocking(SystemMonitor.get_docker_stats)
    elif data == 'menu_processes':
        text = await run_blocking(SystemMonitor.get_process_info)
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Refresh", callback_data=data, icon_custom_emoji_id='5877410604225924969')],
        [InlineKeyboardButton(text="Back", callback_data='menu_main', style='primary', icon_custom_emoji_id='5875082500023258804')]
    ])
    await safe_edit_message(query, text, kb)

@router.callback_query(F.data == 'menu_qbit')
async def handle_menu_qbit(query: CallbackQuery):
    await query.answer()
    text, has_active, has_torrents = await run_blocking(SystemMonitor.get_qbit_stats)
    
    kb_list = [
        [InlineKeyboardButton(text="Refresh", callback_data='menu_qbit', icon_custom_emoji_id='5877410604225924969')]
    ]
    
    if has_torrents:
        if has_active:
            kb_list.append([InlineKeyboardButton(text="Pause All", callback_data='qbit_pause_all', icon_custom_emoji_id='5386710023722265615')])
        else:
            kb_list.append([InlineKeyboardButton(text="Resume All", callback_data='qbit_resume_all', icon_custom_emoji_id='5386331688643093638')])
            
    kb_list.append([InlineKeyboardButton(text="Back", callback_data='menu_main', style='primary', icon_custom_emoji_id='5875082500023258804')])
    
    kb = InlineKeyboardMarkup(inline_keyboard=kb_list)
    await safe_edit_message(query, text, kb)

@router.callback_query(F.data.in_({'qbit_pause_all', 'qbit_resume_all'}))
async def handle_qbit_actions(query: CallbackQuery):
    action = query.data
    
    def do_action():
        client = SystemMonitor.get_qbit_client()
        if not client:
            return False, "Failed to connect to qBittorrent"
        try:
            if action == 'qbit_pause_all':
                client.torrents_pause(torrent_hashes='all')
                return True, "✓ All torrents paused successfully"
            else:
                client.torrents_resume(torrent_hashes='all')
                return True, "✓ All torrents resumed successfully"
        except Exception as e:
            return False, f"⚠ Error: {str(e)[:50]}"
    
    success, msg = await run_blocking(do_action)
    
    if success:
        # Give qBittorrent a moment to update states before fetching stats
        await asyncio.sleep(1.0)
    
    text, has_active, has_torrents = await run_blocking(SystemMonitor.get_qbit_stats)
    
    kb_list = [
        [InlineKeyboardButton(text="Refresh", callback_data='menu_qbit', icon_custom_emoji_id='5877410604225924969')]
    ]
    
    if has_torrents:
        if has_active:
            kb_list.append([InlineKeyboardButton(text="Pause All", callback_data='qbit_pause_all', icon_custom_emoji_id='5386710023722265615')])
        else:
            kb_list.append([InlineKeyboardButton(text="Resume All", callback_data='qbit_resume_all', icon_custom_emoji_id='5386331688643093638')])
            
    kb_list.append([InlineKeyboardButton(text="Back", callback_data='menu_main', style='primary', icon_custom_emoji_id='5875082500023258804')])
    
    kb = InlineKeyboardMarkup(inline_keyboard=kb_list)
    await safe_edit_message(query, text, kb)
    
    await query.answer(msg)

@router.callback_query(F.data == 'menu_system')
async def handle_menu_system(query: CallbackQuery):
    await query.answer()
    text = (
        f"<tg-emoji emoji-id=\"5341715473882955310\">⚙️</tg-emoji>"
        f"<b> System Controls</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<tg-emoji emoji-id=\"5386313314773002654\">⚠️</tg-emoji> "
        f"<i>Handle with care</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Reboot", callback_data='confirm_reboot', icon_custom_emoji_id='5877410604225924969'),
            InlineKeyboardButton(text="Shutdown", callback_data='confirm_shutdown', icon_custom_emoji_id='5778335621491723621')
        ],
        [InlineKeyboardButton(text="Back", callback_data='menu_main', style='primary', icon_custom_emoji_id='5875082500023258804')]
    ])
    await safe_edit_message(query, text, kb)

@router.callback_query(F.data == 'menu_tools')
async def handle_menu_tools(query: CallbackQuery):
    await query.answer()
    text = (
        f"<tg-emoji emoji-id=\"5449428597922079323\">🧰</tg-emoji>"
        f"<b> Tools & Utilities\n</b>"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Network", callback_data='tool_network', icon_custom_emoji_id='5879585266426973039'),
            InlineKeyboardButton(text="Power", callback_data='tool_power', icon_custom_emoji_id='5843553939672274145')
        ],
        [
            InlineKeyboardButton(text="Speedtest", callback_data='tool_speed', icon_custom_emoji_id='5348062301675078252'),
            InlineKeyboardButton(text="Logins", callback_data='tool_logins', icon_custom_emoji_id='5870695289714643076')
        ],
        [
            InlineKeyboardButton(text="Updates", callback_data='tool_updates', icon_custom_emoji_id='6030822047150512346'),            
            InlineKeyboardButton(text="Cleanup", callback_data='confirm_cleanup', icon_custom_emoji_id='5843482192243594901')
        ],
        [
            InlineKeyboardButton(text="Back", callback_data='menu_main', style='primary', icon_custom_emoji_id='5875082500023258804'),
        ]
    ])
    await safe_edit_message(query, text, kb)

@router.callback_query(F.data.startswith('tool_'))
async def handle_tools(query: CallbackQuery):
    await query.answer()
    data = query.data
    
    if data == 'tool_network':
        text = await run_blocking(SystemMonitor.get_network_info)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data='menu_tools', style='primary', icon_custom_emoji_id='5875082500023258804')]])
        
    elif data == 'tool_power':
        text = await run_blocking(SystemMonitor.get_power_detail)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Refresh", callback_data='tool_power', icon_custom_emoji_id='5877410604225924969')],
            [InlineKeyboardButton(text="Back", callback_data='menu_tools', style='primary', icon_custom_emoji_id='5875082500023258804')]
        ])
    
    elif data == 'tool_updates':
        await safe_edit_message(query, "<tg-emoji emoji-id=\"5427181942934088912\">⏳</tg-emoji> <b>Checking repositories...</b>", None)
        text = await run_blocking(SystemMonitor.get_updates_info)
        
        has_updates = "Updates Available" in text
        
        buttons = []
        if has_updates:
            buttons.append([InlineKeyboardButton(text="Upgrade All", callback_data='confirm_upgrade', style='success', icon_custom_emoji_id='5899757765743615694')])
        
        buttons.append([InlineKeyboardButton(text="Back", callback_data='menu_tools', style='primary', icon_custom_emoji_id='5875082500023258804')])
        
        await safe_edit_message(query, text, InlineKeyboardMarkup(inline_keyboard=buttons))
        
    elif data == 'tool_logins':
        result = await run_blocking(subprocess.run, ["last", "-n", "10"], capture_output=True, text=True)
        text = f"<tg-emoji emoji-id=\"5197288647275071607\">🔑</tg-emoji><b> Recent Logins </b>\n\n<pre>{result.stdout}</pre>"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data='menu_tools', style='primary', icon_custom_emoji_id='5875082500023258804')]])
        
    elif data == 'tool_speed':
        await safe_edit_message(query, "<tg-emoji emoji-id=\"5427181942934088912\">⏳</tg-emoji> <b>Running Speedtest.</b>\n<i>This may take a while</i>", None)
        text = await run_blocking(SystemMonitor.run_speedtest)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data='menu_tools', style='primary', icon_custom_emoji_id='5875082500023258804')]])
    
    await safe_edit_message(query, text, kb)

@router.callback_query(F.data == 'tool_updates')
async def handle_tool_updates(query: CallbackQuery):
    await query.answer("Checking for updates...")
    await safe_edit_message(query, "<tg-emoji emoji-id=\"5427181942934088912\">⏳</tg-emoji> <b>Checking repositories...</b>", None)
    
    text = await run_blocking(SystemMonitor.get_updates_info)
    
    # Show "Upgrade" button only if updates exist
    has_updates = "Updates Available" in text
    
    buttons = []
    if has_updates:
        buttons.append([InlineKeyboardButton(text="Upgrade All", callback_data='confirm_upgrade', style='success', icon_custom_emoji_id='5899757765743615694')])
    
    buttons.append([InlineKeyboardButton(text="Back", callback_data='menu_tools', style='primary', icon_custom_emoji_id='5875082500023258804')])
    
    await safe_edit_message(query, text, InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data == 'do_upgrade')
async def handle_upgrade_action(query: CallbackQuery):
    await safe_edit_message(query, "<tg-emoji emoji-id=\"5303396278179210513\">📦</tg-emoji> <b>Upgrading System...</b>\n<i>This may take a while. Do not turn off.</i>", None)
    
    try:
        env = os.environ.copy()
        env['DEBIAN_FRONTEND'] = 'noninteractive'
        
        await run_blocking(
            subprocess.run, 
            ["sudo", "apt-get", "upgrade", "-y"], 
            check=True, 
            env=env
        )
        await safe_edit_message(query, "<tg-emoji emoji-id=\"5427009714745517609\">✅</tg-emoji> <b>Upgrade Complete!</b>\n\nSystem packages updated successfully.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data='menu_tools', icon_custom_emoji_id='5875082500023258804')]]))
    except Exception as e:
        await safe_edit_message(query, f"<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> <b>Upgrade Failed</b>\n<pre>{str(e)[:100]}</pre>", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data='menu_tools', icon_custom_emoji_id='5875082500023258804')]]))

@router.callback_query(F.data.startswith('confirm_'))
async def handle_confirmations(query: CallbackQuery):
    await query.answer()
    action = query.data.replace('confirm_', '')
    confirm_map = {
        'reboot': ("<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> <b>CONFIRM REBOOT</b>", 'menu_system'),
        'shutdown': ("<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> <b>CONFIRM SHUTDOWN</b>", 'menu_system'),
        'upgrade': ("<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> <b>CONFIRM SYSTEM UPGRADE</b>\n\nThis will run <code>apt-get upgrade -y</code>.\nBot may be unresponsive during process.", 'tool_updates'),
        'cleanup': ("<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> <b>CONFIRM CLEANUP</b>\n<i>Runs apt autoremove & clean</i>", 'menu_tools')
        
    }
    
    if action in confirm_map:
        text, back = confirm_map[action]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Confirm", callback_data=f'do_{action}', style='success', icon_custom_emoji_id='5825794181183836432'),
                InlineKeyboardButton(text="Cancel", callback_data=back, style='danger', icon_custom_emoji_id='5778527486270770928')
            ]
        ])
        await safe_edit_message(query, text, kb)

@router.callback_query(F.data.startswith('do_'))
async def handle_actions(query: CallbackQuery):
    data = query.data
    
    if data == 'do_cleanup':
        await query.answer("Cleaning up...")
        await safe_edit_message(query, "<tg-emoji emoji-id=\"5431371576157162781\">🧹</tg-emoji> <b>Running cleanup...</b>", None)
        try:
            await run_blocking(subprocess.run, ["sudo", "apt-get", "autoremove", "-y"], check=True)
            await run_blocking(subprocess.run, ["sudo", "apt-get", "clean"], check=True)
            text = "<tg-emoji emoji-id=\"5427009714745517609\">✅</tg-emoji> <b>Cleanup Complete</b>"
        except Exception as e:
            text = f"<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> <b>Cleanup Failed</b>\n<pre>{str(e)[:100]}</pre>"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data='menu_tools', style='primary', icon_custom_emoji_id='5875082500023258804')]])
        await safe_edit_message(query, text, kb)
        
    elif data == 'do_reboot':        
        await safe_edit_message(query, "<tg-emoji emoji-id=\"5877410604225924969\">🔄</tg-emoji> <b>System Rebooting...</b>", None)
        await run_blocking(subprocess.run, ["sudo", "/usr/sbin/reboot"])
        
    elif data == 'do_shutdown':
        await safe_edit_message(query, "<tg-emoji emoji-id=\"5316809327900631927\">🛑</tg-emoji> <b>System Shutting Down...</b>", None)
        await run_blocking(subprocess.run, ["sudo", "/usr/sbin/shutdown", "now"])
    
    elif data == 'do_upgrade':
        await safe_edit_message(query, "<tg-emoji emoji-id=\"5821388031336156546\">📦</tg-emoji> <b>Upgrading System...</b>\n<i>This may take a while. Do not turn off.</i>", None)
        
        try:
            # Set non-interactive environment to prevent hanging on config prompts
            env = os.environ.copy()
            env['DEBIAN_FRONTEND'] = 'noninteractive'
            
            await run_blocking(
                subprocess.run, 
                ["sudo", "apt-get", "upgrade", "-y"], 
                check=True, 
                env=env
            )
            text = "<tg-emoji emoji-id=\"5427009714745517609\">✅</tg-emoji> <b>Upgrade Complete</b>"
        except Exception as e:
            text = f"<tg-emoji emoji-id=\"5447644880824181073\">⚠️</tg-emoji> <b>Upgrade Failed</b>\n<pre>{str(e)[:100]}</pre>"
            
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data='menu_tools', style='primary', icon_custom_emoji_id='5875082500023258804')]])
        await safe_edit_message(query, text, kb)

async def on_startup(bot: Bot):
    logger.info("🟢 Bot Started")
    stats = await run_blocking(SystemMonitor.get_stats)
    keyboard = get_main_keyboard()

    with suppress(Exception):
        await bot.send_message(
            conf.ADMIN_ID,
            f"<tg-emoji emoji-id=\"5465647158935963624\">🟢</tg-emoji> "
            f"<b>Server Bot Online</b>"
        )
        await bot.send_message(
            conf.ADMIN_ID,
            f"{stats}",
            reply_markup=keyboard
        )

# --- MAIN ---
async def main():
    # Setting link_preview_is_disabled globally removes the need for disable_web_page_preview anywhere else
    bot = Bot(
        token=conf.TOKEN, 
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=True
        )
    )
    
    dp = Dispatcher()
    dp.include_router(router)
    dp.startup.register(on_startup)

    logger.info("🚀 Starting Server Monitor Bot...")
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")