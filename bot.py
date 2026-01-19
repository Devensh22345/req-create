import os
import logging
from typing import Dict, List, Tuple
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from telegram.constants import ParseMode
import sqlite3
import secrets
import string

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database setup
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('bot_data.db', check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        # Post channels table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS post_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE,
                channel_name TEXT,
                added_at TIMESTAMP
            )
        ''')
        
        # Req channels table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS req_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE,
                channel_name TEXT,
                registered_at TIMESTAMP
            )
        ''')
        
        # Request links table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS request_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                req_channel_id TEXT,
                post_channel_id TEXT,
                link_token TEXT UNIQUE,
                link_title TEXT,
                created_at TIMESTAMP,
                FOREIGN KEY (req_channel_id) REFERENCES req_channels (channel_id),
                FOREIGN KEY (post_channel_id) REFERENCES post_channels (channel_id)
            )
        ''')
        
        # Bot owner table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS owner (
                id INTEGER PRIMARY KEY,
                user_id TEXT UNIQUE
            )
        ''')
        
        self.conn.commit()
    
    def add_owner(self, user_id: str):
        cursor = self.conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO owner (id, user_id) VALUES (1, ?)', (user_id,))
        self.conn.commit()
    
    def get_owner(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT user_id FROM owner WHERE id = 1')
        result = cursor.fetchone()
        return result[0] if result else None
    
    def add_post_channel(self, channel_id: str, channel_name: str):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO post_channels (channel_id, channel_name, added_at)
            VALUES (?, ?, ?)
        ''', (channel_id, channel_name, datetime.now()))
        self.conn.commit()
    
    def get_post_channels(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT channel_id, channel_name FROM post_channels')
        return cursor.fetchall()
    
    def remove_post_channel(self, channel_id: str):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM post_channels WHERE channel_id = ?', (channel_id,))
        cursor.execute('DELETE FROM request_links WHERE post_channel_id = ?', (channel_id,))
        self.conn.commit()
    
    def add_req_channel(self, channel_id: str, channel_name: str):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO req_channels (channel_id, channel_name, registered_at)
            VALUES (?, ?, ?)
        ''', (channel_id, channel_name, datetime.now()))
        self.conn.commit()
    
    def get_req_channel(self, channel_id: str):
        cursor = self.conn.cursor()
        cursor.execute('SELECT channel_id, channel_name FROM req_channels WHERE channel_id = ?', (channel_id,))
        return cursor.fetchone()
    
    def create_request_links(self, req_channel_id: str, req_channel_name: str, bot_username: str):
        cursor = self.conn.cursor()
        post_channels = self.get_post_channels()
        
        # Generate unique tokens for each request link
        for post_channel_id, post_channel_name in post_channels:
            token = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
            
            cursor.execute('''
                INSERT OR REPLACE INTO request_links 
                (req_channel_id, post_channel_id, link_token, link_title, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (req_channel_id, post_channel_id, token, post_channel_name, datetime.now()))
        
        self.conn.commit()
        return len(post_channels)
    
    def get_request_links(self, req_channel_id: str, bot_username: str):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT rl.link_token, rl.link_title, pc.channel_name
            FROM request_links rl
            JOIN post_channels pc ON rl.post_channel_id = pc.channel_id
            WHERE rl.req_channel_id = ?
        ''', (req_channel_id,))
        
        links = []
        for token, title, post_channel_name in cursor.fetchall():
            link = f"https://t.me/{bot_username}?start={token}"
            links.append((link, title, post_channel_name))
        return links
    
    def get_request_link_for_post(self, req_channel_id: str, post_channel_id: str, bot_username: str):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT link_token FROM request_links 
            WHERE req_channel_id = ? AND post_channel_id = ?
        ''', (req_channel_id, post_channel_id))
        
        result = cursor.fetchone()
        if result:
            return f"https://t.me/{bot_username}?start={result[0]}"
        return None

# Initialize database
db = Database()

# Bot setup
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
OWNER_ID = os.getenv('OWNER_ID', 'YOUR_USER_ID_HERE')  # Replace with your Telegram user ID

# Store bot username globally
bot_username = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command with request link token."""
    user = update.effective_user
    args = context.args
    
    if args:
        token = args[0]
        # Handle the request link - in a real bot, you'd add user to channel here
        await update.message.reply_text(
            f"✅ Request link activated!\n"
            f"Welcome {user.mention_html()}!\n\n"
            f"This link was for a specific channel request.",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            f"👋 Hello {user.mention_html()}!\n\n"
            f"I'm a channel management bot.\n"
            f"Use me in channels with appropriate commands.",
            parse_mode=ParseMode.HTML
        )

async def set_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set bot owner (run once)."""
    user = update.effective_user
    db.add_owner(str(user.id))
    await update.message.reply_text("✅ You have been set as bot owner!")

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a post channel - /add <channel_id>"""
    # Check if user is owner
    owner_id = db.get_owner()
    if str(update.effective_user.id) != owner_id:
        await update.message.reply_text("❌ Only owner can use this command!")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /add <channel_id>\nExample: /add -1001234567890")
        return
    
    channel_id = context.args[0]
    
    # Get channel info (bot must be in channel)
    try:
        chat = await context.bot.get_chat(channel_id)
        db.add_post_channel(channel_id, chat.title)
        
        await update.message.reply_text(
            f"✅ Channel added successfully!\n"
            f"Name: {chat.title}\n"
            f"ID: {channel_id}"
        )
    except Exception as e:
        logger.error(f"Error adding channel: {e}")
        await update.message.reply_text("❌ Failed to add channel. Make sure:\n1. Channel ID is correct\n2. Bot is added to channel\n3. Bot is admin in channel")

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all post channels with inline buttons to remove."""
    # Check if user is owner
    owner_id = db.get_owner()
    if str(update.effective_user.id) != owner_id:
        await update.message.reply_text("❌ Only owner can use this command!")
        return
    
    channels = db.get_post_channels()
    
    if not channels:
        await update.message.reply_text("📭 No post channels added yet!")
        return
    
    keyboard = []
    for channel_id, channel_name in channels:
        keyboard.append([
            InlineKeyboardButton(
                f"🗑 {channel_name}",
                callback_data=f"remove_{channel_id}"
            )
        ])
    
    # Add a cancel button
    keyboard.append([
        InlineKeyboardButton("❌ Cancel", callback_data="cancel_list")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📋 **Post Channels List**\n\n"
        "Click on any channel to remove it from the list:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("remove_"):
        channel_id = data.split("_")[1]
        db.remove_post_channel(channel_id)
        
        await query.edit_message_text(
            "✅ Channel removed successfully!",
            reply_markup=None
        )
    
    elif data == "cancel_list":
        await query.edit_message_text(
            "❌ Operation cancelled.",
            reply_markup=None
        )

async def req_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /req command - create request links for the channel."""
    # Check if command is sent in a channel
    if update.effective_chat.type not in ['group', 'supergroup', 'channel']:
        await update.message.reply_text("❌ This command can only be used in channels!")
        return
    
    # Check if user is admin
    try:
        chat_member = await context.bot.get_chat_member(
            update.effective_chat.id,
            update.effective_user.id
        )
        if chat_member.status not in ['creator', 'administrator']:
            await update.message.reply_text("❌ Only admins can use this command!")
            return
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        await update.message.reply_text("❌ Error checking permissions!")
        return
    
    channel_id = str(update.effective_chat.id)
    channel_name = update.effective_chat.title
    
    # Register or update req channel
    db.add_req_channel(channel_id, channel_name)
    
    # Create request links
    global bot_username
    if not bot_username:
        bot_username = (await context.bot.get_me()).username
    
    num_links = db.create_request_links(channel_id, channel_name, bot_username)
    
    # Get and display the links
    links = db.get_request_links(channel_id, bot_username)
    
    message_text = f"🔗 **Request Links for {channel_name}**\n\n"
    message_text += f"Created {num_links} request links:\n\n"
    
    for i, (link, title, post_channel_name) in enumerate(links, 1):
        message_text += f"{i}. **{title}**\n`{link}`\n\n"
    
    await update.message.reply_text(
        message_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /send command - send posts to all post channels."""
    # Check if command is sent in a req channel
    if update.effective_chat.type not in ['group', 'supergroup', 'channel']:
        await update.message.reply_text("❌ This command can only be used in channels!")
        return
    
    # Check if user is admin
    try:
        chat_member = await context.bot.get_chat_member(
            update.effective_chat.id,
            update.effective_user.id
        )
        if chat_member.status not in ['creator', 'administrator']:
            await update.message.reply_text("❌ Only admins can use this command!")
            return
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        await update.message.reply_text("❌ Error checking permissions!")
        return
    
    req_channel_id = str(update.effective_chat.id)
    req_channel = db.get_req_channel(req_channel_id)
    
    if not req_channel:
        await update.message.reply_text("❌ This channel is not registered as a req channel!\nUse /req first to register.")
        return
    
    # Get all post channels
    post_channels = db.get_post_channels()
    
    if not post_channels:
        await update.message.reply_text("❌ No post channels configured!")
        return
    
    global bot_username
    if not bot_username:
        bot_username = (await context.bot.get_me()).username
    
    # Send post to each post channel
    success_count = 0
    failed_channels = []
    
    for post_channel_id, post_channel_name in post_channels:
        try:
            # Get request link for this specific post channel
            request_link = db.get_request_link_for_post(
                req_channel_id,
                post_channel_id,
                bot_username
            )
            
            if not request_link:
                failed_channels.append(f"{post_channel_name} (No link found)")
                continue
            
            # Create inline keyboard with join buttons
            keyboard = []
            # You can add multiple buttons if needed
            for i in range(1, 4):  # Creates 3 buttons as per your requirement
                keyboard.append([
                    InlineKeyboardButton(
                        f"{i} - JOIN",
                        url=request_link
                    )
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send the post
            await context.bot.send_message(
                chat_id=post_channel_id,
                text=f"📢 **Click here to join**\n\nJoin our channel for more updates!",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
            success_count += 1
            
        except Exception as e:
            logger.error(f"Error sending to {post_channel_name}: {e}")
            failed_channels.append(f"{post_channel_name} (Error: {str(e)})")
    
    # Send report
    report_text = f"📊 **Send Report**\n\n"
    report_text += f"✅ Successfully sent to: {success_count} channels\n"
    
    if failed_channels:
        report_text += f"\n❌ Failed to send to:\n"
        for channel in failed_channels:
            report_text += f"• {channel}\n"
    
    await update.message.reply_text(report_text, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message."""
    help_text = """
🤖 **Bot Commands Guide**

**Owner Commands:**
• `/add <channel_id>` - Add a post channel
• `/list` - List all post channels with remove options

**Admin Commands (in channels):**
• `/req` - Create request links for the current channel
• `/send` - Send posts to all post channels

**Notes:**
1. Bot must be admin in all channels
2. Use /req before /send
3. Channel IDs should start with -100

**Setup Steps:**
1. Add bot to your channel as admin
2. Use /req in your channel
3. Use /send to post to all registered channels
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

def main():
    """Start the bot."""
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setowner", set_owner))
    application.add_handler(CommandHandler("add", add_channel))
    application.add_handler(CommandHandler("list", list_channels))
    application.add_handler(CommandHandler("req", req_command))
    application.add_handler(CommandHandler("send", send_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # Add callback query handler for inline buttons
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Set owner on first run
    if OWNER_ID and OWNER_ID != 'YOUR_USER_ID_HERE':
        db.add_owner(OWNER_ID)
        logger.info(f"Owner set to: {OWNER_ID}")
    
    # Start the bot
    print("🤖 Bot is starting...")
    print("Press Ctrl+C to stop")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
