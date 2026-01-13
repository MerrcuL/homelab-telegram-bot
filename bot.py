import os
import logging
import psutil
import qbittorrentapi
import subprocess
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    TypeHandler,
    ApplicationHandlerStop
)

# 1. Load environment variables
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))

# Basic logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- HELPER: GET SYSTEM STATS ---
def get_system_stats():
    # CPU usage (interval=None is non-blocking)
    cpu = psutil.cpu_percent(interval=None)
    
    # RAM usage
    ram = psutil.virtual_memory()
    ram_used_gb = ram.used / (1024 ** 3)
    ram_total_gb = ram.total / (1024 ** 3)
    
    # Disk usage (Root partition)
    disk1 = psutil.disk_usage('/')
    disk1_used_gb = disk1.used / (1024 ** 3)
    disk1_free_gb = disk1.free / (1024 ** 3)
    disk1_total_gb = disk1.total / (1024 ** 3)

    # Disk usage (Data partition))
    disk2 = psutil.disk_usage('/srv/dev-disk-by-uuid-f77e35b6-7553-430f-a508-1efab916c2af')
    disk2_used_gb = disk2.used / (1024 ** 3)
    disk2_free_gb = disk2.free / (1024 ** 3)
    disk2_total_gb = disk2.total / (1024 ** 3)

    # Format the message
    stats_msg = (
        f"<b>📊 Your System Dashboard</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>CPU Load:</b> {cpu}%\n"
        f"<b>RAM:</b> {ram_used_gb:.1f} GB / {ram_total_gb:.1f} GB ({ram.percent}%)\n"
        f"<b>Disk (Root):</b> {disk1_used_gb:.1f} / {disk1_total_gb:.1f} GB ({disk1_free_gb:.1f} GB free)\n"
        f"<b>Disk (Data):</b> {disk2_used_gb:.1f} / {disk2_total_gb:.1f} GB ({disk2_free_gb:.1f} GB free)\n"
    )
    return stats_msg

def get_qbit_stats():
    try:
        # Connect
        qbt_client = qbittorrentapi.Client(
            host=os.getenv('QBIT_URL'),
            username=os.getenv('QBIT_USER'),
            password=os.getenv('QBIT_PASS')
        )
        qbt_client.auth_log_in()
        
        # Get all torrents
        torrents = qbt_client.torrents_info()
        
        # Count statuses
        downloading = sum(1 for t in torrents if t.state in ['downloading', 'stalledDL', 'metaDL'])
        seeding = sum(1 for t in torrents if t.state in ['uploading', 'stalledUP', 'queuedUP', 'forcedUP'])
        completed = sum(1 for t in torrents if t.progress == 1) # 1 means 100%
        
        msg = (
            f"<b>⬇️ qBittorrent Stats</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Downloading:</b> {downloading}\n"
            f"<b>Seeding:</b> {seeding}\n"
            f"<b>Total Completed:</b> {completed}\n"
        )
        return msg
        
    except Exception as e:
        print(f"qBit Error: {e}")
        return "⚠️ Error: Could not connect to qBittorrent."

# --- FIREWALL ---
async def firewall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and user.id != ADMIN_ID:
        print(f"Unauthorized access attempt from {user.first_name} (ID: {user.id})")
        raise ApplicationHandlerStop

# --- MENUS ---
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the main menu with buttons."""
    keyboard = [
        [
            InlineKeyboardButton("💻 Terminal", callback_data='menu_terminal'),
            InlineKeyboardButton("⚙️ Controls", callback_data='menu_sys_controls')
        ],
        [
            InlineKeyboardButton("⬇️ qBittorrent", callback_data='menu_qbittorrent'),
            
            InlineKeyboardButton("🐳 Containers", callback_data='menu_containers')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = get_system_stats()

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
    elif update.callback_query:
        # Edit message creates a seamless transition
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

# --- BUTTON HANDLER ---
async def button_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() 
    
    data = query.data
    
    if data == 'menu_main':
        await main_menu(update, context)
        
    elif data == 'menu_containers':
        await query.edit_message_text(
            text="🐳 Docker management coming soon.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='menu_main')]])
        )
        
    elif data == 'menu_qbittorrent':
        stats_text = get_qbit_stats()
        # Add a refresh button just like the main dashboard
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data='menu_qbittorrent')],
            [InlineKeyboardButton("🔙 Back", callback_data='menu_main')]
        ]
        await query.edit_message_text(
            text=stats_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    elif data == 'menu_terminal':
        await query.edit_message_text(
            text="💻 SSH Terminal coming soon.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='menu_main')]])
        )
    # --- 1. System Controls Submenu ---
    elif data == 'menu_sys_controls':
        keyboard = [
            [
                InlineKeyboardButton("🔄 Reboot Server", callback_data='confirm_reboot'),
                InlineKeyboardButton("🛑 Shutdown Server", callback_data='confirm_shutdown')
            ],            
            [
                InlineKeyboardButton("🔙 Back", callback_data='menu_main')
            ]
        ]
        await query.edit_message_text(
            text="<b>⚙️ System Controls</b>\n\n⚠️ Be careful! These actions affect the entire server.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    # --- 2. Confirmation Dialogs ---
    elif data == 'confirm_reboot':
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, Reboot", callback_data='action_reboot'),
                InlineKeyboardButton("❌ Cancel", callback_data='menu_sys_controls')
            ]
        ]
        await query.edit_message_text(
            text="⚠️ <b>CONFIRM REBOOT</b> ⚠️\n\nAre you sure you want to reboot the server?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    elif data == 'confirm_shutdown':
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, Shutdown", callback_data='action_shutdown'),
                InlineKeyboardButton("❌ Cancel", callback_data='menu_sys_controls')
            ]
        ]
        await query.edit_message_text(
            text="⚠️ <b>CONFIRM SHUTDOWN</b> ⚠️\n\nAre you sure you want to power off the server immediately?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    # --- 3. Execution ---
    elif data == 'action_reboot':
        await query.edit_message_text(text="🔄 System is rebooting now... See you!")
        # Execute the reboot command
        subprocess.run(["sudo", "/usr/sbin/reboot"])

    elif data == 'action_shutdown':
        await query.edit_message_text(text="🛑 System is shutting down now... Bye!")
        # Execute the shutdown command
        subprocess.run(["sudo", "/usr/sbin/shutdown", "now"])

# --- STARTUP CONFIG ---
async def post_init(application):
    """
    Sets the blue 'Menu' button commands on startup.
    This replaces the need to talk to BotFather for commands.
    """
    commands = [
        BotCommand("start", "Open Dashboard Menu"),
        BotCommand("help", "Show help info"),
    ]
    await application.bot.set_my_commands(commands)
    
    await application.bot.send_message(
        chat_id=ADMIN_ID,
        text="<b>🖥 System Online</b>\nBot is up and running.",
        parse_mode='HTML'
    )
    print("Bot commands updated successfully.")

# --- MAIN ---
if __name__ == '__main__':
    # We add post_init to run setup logic when bot starts
    application = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    firewall_handler = TypeHandler(Update, firewall)
    application.add_handler(firewall_handler, group=-1)

    application.add_handler(CommandHandler('start', main_menu))
    application.add_handler(CallbackQueryHandler(button_tap))

    print("Bot is running...")
    application.run_polling()