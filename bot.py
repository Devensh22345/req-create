import logging
import sqlite3
import os
from datetime import datetime

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardRemove, ParseMode
)
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    CallbackQueryHandler, ConversationHandler, CallbackContext
)
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get bot token from environment variable
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set!")

# Database setup
DB_NAME = 'channels.db'

def init_db():
    """Initialize database"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT UNIQUE,
            channel_name TEXT,
            added_date TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# Conversation states
LINK, CHANNEL_SELECTION = range(2)

# Admin list - set your admin user IDs here
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '8242413007').split(',') if id.strip()]

def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id in ADMIN_IDS

def start(update: Update, context: CallbackContext):
    """Send welcome message"""
    welcome_text = (
        "🤖 **Channel Manager Bot**\n\n"
        "**Available Commands:**\n"
        "/add <channel_id> - Add a channel (Admin only)\n"
        "/list - List all channels with remove option\n"
        "/post - Create and post to channels\n\n"
        "*Note:* Bot must be admin in the channels."
    )
    
    update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN
    )

def add_channel(update: Update, context: CallbackContext):
    """Add a channel to database"""
    user_id = update.effective_user.id
    
    # Check if user is admin
    if not is_admin(user_id):
        update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    # Check if channel ID is provided
    if not context.args:
        update.message.reply_text("Usage: /add <channel_id>")
        return
    
    channel_id = context.args[0]
    
    try:
        # Check if bot is admin in the channel
        chat_member = context.bot.get_chat_member(channel_id, context.bot.id)
        if chat_member.status not in ['administrator', 'creator']:
            update.message.reply_text("❌ I must be an admin in that channel!")
            return
        
        # Get channel name
        chat = context.bot.get_chat(channel_id)
        channel_name = chat.title
        
        # Add to database
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "INSERT INTO channels (channel_id, channel_name, added_date) VALUES (?, ?, ?)",
                (channel_id, channel_name, datetime.now())
            )
            conn.commit()
            
            update.message.reply_text(
                f"✅ Channel '{channel_name}' added successfully!"
            )
        except sqlite3.IntegrityError:
            update.message.reply_text("⚠️ This channel is already in the database!")
        
        conn.close()
        
    except Exception as e:
        logger.error(f"Error adding channel: {e}")
        update.message.reply_text(
            "❌ Error adding channel. Make sure:\n"
            "1. Channel ID is correct (use @username for public or -100ID for private)\n"
            "2. I'm added to that channel as admin\n"
            "3. For private channels, use numeric ID starting with -100"
        )

def list_channels(update: Update, context: CallbackContext):
    """List all channels with inline buttons to remove"""
    # Check if user is admin
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    # Get channels from database
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_name FROM channels")
    channels = cursor.fetchall()
    conn.close()
    
    if not channels:
        update.message.reply_text("📭 No channels in database. Use /add to add channels.")
        return
    
    # Create inline keyboard
    keyboard = []
    for channel_id, channel_name in channels:
        keyboard.append([
            InlineKeyboardButton(
                text=f"❌ {channel_name}",
                callback_data=f"remove_{channel_id}"
            )
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        "📋 **Channel List**\nClick on a channel to remove it:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

def button_callback(update: Update, context: CallbackContext):
    """Handle inline button callbacks for removing channels"""
    query = update.callback_query
    query.answer()
    
    # Check if user is admin
    if not is_admin(query.from_user.id):
        query.edit_message_text("❌ You are not authorized to remove channels.")
        return
    
    # Extract channel_id from callback data
    channel_id = query.data.replace("remove_", "")
    
    # Remove from database
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    if deleted:
        # Get channel name for the message
        try:
            chat = context.bot.get_chat(channel_id)
            channel_name = chat.title
        except:
            channel_name = channel_id
        
        # Update message
        query.edit_message_text(
            f"✅ Channel '{channel_name}' removed successfully!\n\nUse /list to see remaining channels."
        )
    else:
        query.edit_message_text("❌ Channel not found in database.")

def post_start(update: Update, context: CallbackContext):
    """Start the post creation process"""
    # Check if user is admin
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ You are not authorized to use this command.")
        return ConversationHandler.END
    
    update.message.reply_text(
        "📝 Please send me the link for the post:",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return LINK

def get_link(update: Update, context: CallbackContext):
    """Get link and show channel selection"""
    link = update.message.text
    
    # Validate link (basic validation)
    if not link.startswith(('http://', 'https://')):
        update.message.reply_text("❌ Please provide a valid HTTP/HTTPS link.")
        return LINK
    
    # Store link in context
    context.user_data['post_link'] = link
    
    # Get channels from database
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_name FROM channels")
    channels = cursor.fetchall()
    conn.close()
    
    if not channels:
        update.message.reply_text("❌ No channels in database. Add channels first using /add")
        return ConversationHandler.END
    
    # Create inline keyboard for channel selection
    keyboard = []
    
    # Add "All Channels" button
    keyboard.append([
        InlineKeyboardButton(
            text="🌐 Post to ALL Channels",
            callback_data="all"
        )
    ])
    
    # Add individual channel buttons
    for channel_id, channel_name in channels:
        keyboard.append([
            InlineKeyboardButton(
                text=f"📢 {channel_name}",
                callback_data=f"channel_{channel_id}"
            )
        ])
    
    # Add cancel button
    keyboard.append([
        InlineKeyboardButton(
            text="❌ Cancel",
            callback_data="cancel"
        )
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Show post preview
    post_text = create_post_text(link)
    update.message.reply_text(
        f"📄 **Post Preview:**\n\n{post_text}\n\n"
        "Select where to post:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )
    
    return CHANNEL_SELECTION

def create_post_text(link: str) -> str:
    """Create the post text with proper formatting"""
    post_text = (
        "**𝗪𝗵𝗼 𝗜𝘀 𝗬𝗼𝘂𝗿 𝗙𝗮𝘃𝗼𝘂𝗿𝗮𝘁𝗲 𝗔𝗰𝘁𝗿𝗲𝘀𝘀 ?** 😍"
    )
    return post_text

def create_post_markup(link: str) -> InlineKeyboardMarkup:
    """Create inline keyboard for the post"""
    keyboard = [
            [InlineKeyboardButton("𝗖𝗢𝗠𝗔𝗧𝗢𝗭𝗭𝗘", url=link)],
            [InlineKeyboardButton("𝗘𝗩𝗔 𝗘𝗟𝗙𝗜𝗘", url=link)],
            [InlineKeyboardButton("𝗔𝗡𝗚𝗘𝗟𝗔 𝗪𝗛𝗜𝗧𝗘", url=link)],
            [InlineKeyboardButton("𝗦𝗨𝗡𝗡𝗬 𝗟𝗘𝗢𝗡", url=link)],
            [InlineKeyboardButton("𝗠𝗜𝗔 𝗠𝗔𝗟𝗞𝗢𝗩𝗔", url=link)],
            [InlineKeyboardButton("𝗠𝗜𝗔 𝗞𝗛𝗔𝗟𝗜𝗙𝗔", url=link)]
    ]
    return InlineKeyboardMarkup(keyboard)

def channel_selection(update: Update, context: CallbackContext):
    """Handle channel selection for posting"""
    query = update.callback_query
    query.answer()
    
    if query.data == "cancel":
        query.edit_message_text("❌ Post cancelled.")
        return ConversationHandler.END
    
    # Get the link from context
    link = context.user_data.get('post_link')
    if not link:
        query.edit_message_text("❌ Error: Link not found.")
        return ConversationHandler.END
    
    # Prepare post
    post_text = create_post_text(link)
    post_markup = create_post_markup(link)
    
    # Get channels
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_name FROM channels")
    channels = cursor.fetchall()
    conn.close()
    
    success_count = 0
    failed_channels = []
    
    if query.data == "all":
        # Post to all channels
        for channel_id, channel_name in channels:
            try:
                context.bot.send_message(
                    chat_id=channel_id,
                    text=post_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=post_markup
                )
                success_count += 1
            except Exception as e:
                logger.error(f"Error posting to {channel_name}: {e}")
                failed_channels.append(channel_name)
        
        # Send summary
        summary = f"✅ Posted to {success_count} channel(s)"
        if failed_channels:
            summary += f"\n❌ Failed: {', '.join(failed_channels)}"
        
        query.edit_message_text(summary)
    
    else:
        # Post to single channel
        channel_id = query.data.replace("channel_", "")
        
        # Find channel name
        channel_name = ""
        for cid, cname in channels:
            if cid == channel_id:
                channel_name = cname
                break
        
        try:
            context.bot.send_message(
                chat_id=channel_id,
                text=post_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=post_markup
            )
            query.edit_message_text(f"✅ Posted to {channel_name} successfully!")
        except Exception as e:
            logger.error(f"Error posting to {channel_name}: {e}")
            query.edit_message_text(f"❌ Failed to post to {channel_name}")
    
    return ConversationHandler.END

def cancel_post(update: Update, context: CallbackContext):
    """Cancel the post creation process"""
    update.message.reply_text(
        "❌ Post creation cancelled.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

def error_handler(update: Update, context: CallbackContext):
    """Log errors"""
    logger.error(msg="Exception occurred:", exc_info=context.error)

def main():
    """Main function to start the bot"""
    # Initialize database
    init_db()
    
    # Create updater and dispatcher
    updater = Updater(BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    
    # Register handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("add", add_channel))
    dispatcher.add_handler(CommandHandler("list", list_channels))
    
    # Conversation handler for /post command
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('post', post_start)],
        states={
            LINK: [MessageHandler(Filters.text & ~Filters.command, get_link)],
            CHANNEL_SELECTION: [CallbackQueryHandler(channel_selection)]
        },
        fallbacks=[CommandHandler('cancel', cancel_post)]
    )
    dispatcher.add_handler(conv_handler)
    
    # Callback query handler for removing channels
    dispatcher.add_handler(CallbackQueryHandler(button_callback, pattern='^remove_'))
    
    # Error handler
    dispatcher.add_error_handler(error_handler)
    
    # Start the bot
    print("🤖 Bot is starting...")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
