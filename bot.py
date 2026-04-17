import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from telethon import events

from config import BOT_TOKEN, ADMIN_IDS
from database import db
from client_manager import client_manager
from login import login_handler, API_ID, API_HASH, PHONE, OTP, PASSWORD
from menu import menu_ui
from messaging import message_sender
from scheduler import scheduler_manager
from scraper import scraper
from escrow import escrow_manager
from auto_reply import auto_reply_handler
from analytics import analytics

# Global storage for user states
user_states = {}

# ============ START & MAIN MENU ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    user = update.effective_user
    
    # Add user to database
    await db.add_user(user.id, user.username)
    
    # Check if user has active account
    account = await db.get_active_account(user.id)
    
    if not account:
        # No account - show login option
        keyboard = [[
            InlineKeyboardButton("🔐 Login Account", callback_data="add_account")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"👋 **Welcome to Telegram Automation Bot!**\n\n"
            f"Hello {user.first_name}!\n\n"
            f"To get started, please login with your Telegram account.\n\n"
            f"Click the button below to begin:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        # Has account - show main menu
        await update.message.reply_text(
            f"👋 **Welcome Back, {user.first_name}!**\n\n"
            f"✅ Active Account: {account['phone']}\n\n"
            f"Choose an action from the menu below:",
            reply_markup=menu_ui.main_menu(),
            parse_mode='Markdown'
        )

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show main menu"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    account = await db.get_active_account(user.id)
    
    if account:
        await query.edit_message_text(
            f"🏠 **Main Menu**\n\n"
            f"Active Account: {account['phone']}\n\n"
            f"Choose an action:",
            reply_markup=menu_ui.main_menu(),
            parse_mode='Markdown'
        )
    else:
        await query.edit_message_text(
            "❌ No active account. Please login first.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔐 Login", callback_data="add_account")
            ]])
        )

# ============ SEND MESSAGE ============

async def send_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle send message"""
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "💬 **Send Message**\n\n"
        "Format:\n"
        "`/send <target> <message>`\n\n"
        "Examples:\n"
        "`/send @username Hello!`\n"
        "`/send 123456789 Hi there`\n"
        "`/send -1001234567890 Group message`",
        parse_mode='Markdown',
        reply_markup=menu_ui.back_button()
    )

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send message command"""
    user_id = update.effective_user.id
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Invalid format.\n\n"
            "Use: `/send <target> <message>`",
            parse_mode='Markdown'
        )
        return
    
    target = context.args[0]
    message = ' '.join(context.args[1:])
    
    # Send message
    result = await message_sender.send_message(user_id, target, message)
    
    if result['success']:
        await update.message.reply_text(
            f"✅ Message sent successfully!\n\n"
            f"Target: {target}\n"
            f"Message ID: {result['message_id']}"
        )
    else:
        await update.message.reply_text(
            f"❌ Failed to send message:\n{result['error']}"
        )

# ============ MULTI-ACCOUNT ============

async def multi_account_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Multi-account menu"""
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "👥 **Multi-Account Management**\n\n"
        "Manage your Telegram accounts:",
        reply_markup=menu_ui.multi_account_menu(),
        parse_mode='Markdown'
    )

async def view_accounts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View all accounts"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    accounts = await db.get_all_accounts(user_id)
    
    if not accounts:
        await update.callback_query.edit_message_text(
            "📋 **Your Accounts**\n\n"
            "No accounts found. Add one to get started!",
            reply_markup=menu_ui.multi_account_menu()
        )
        return
    
    text = "📋 **Your Accounts**\n\n"
    
    for acc in accounts:
        status = "✅ Active" if acc['is_active'] else "⚪ Inactive"
        text += f"{status} - {acc['phone']} (ID: {acc['id']})\n"
    
    text += "\nUse `/switch <account_id>` to change active account."
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=menu_ui.multi_account_menu(),
        parse_mode='Markdown'
    )

async def switch_account_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Switch active account"""
    user_id = update.effective_user.id
    
    if len(context.args) < 1:
        await update.message.reply_text("Usage: `/switch <account_id>`", parse_mode='Markdown')
        return
    
    try:
        account_id = int(context.args[0])
        await db.set_active_account(user_id, account_id)
        await update.message.reply_text(f"✅ Switched to account ID: {account_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ============ SCHEDULER ============

async def schedule_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Schedule menu"""
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "⏰ **Message Scheduler**\n\n"
        "Schedule messages to be sent automatically:",
        reply_markup=menu_ui.schedule_menu(),
        parse_mode='Markdown'
    )

async def schedule_onetime_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """One-time schedule"""
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "⏱️ **One-Time Schedule**\n\n"
        "Format:\n"
        "`/schedule <target> <datetime> <message>`\n\n"
        "Example:\n"
        "`/schedule @username 2024-01-15 14:30 Hello!`\n\n"
        "Datetime format: YYYY-MM-DD HH:MM",
        parse_mode='Markdown',
        reply_markup=menu_ui.back_button()
    )

async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Schedule message command"""
    user_id = update.effective_user.id
    
    if len(context.args) < 4:
        await update.message.reply_text(
            "❌ Invalid format.\n\n"
            "Use: `/schedule <target> <date> <time> <message>`",
            parse_mode='Markdown'
        )
        return
    
    target = context.args[0]
    date_str = context.args[1]
    time_str = context.args[2]
    message = ' '.join(context.args[3:])
    
    try:
        from datetime import datetime
        schedule_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        
        account = await db.get_active_account(user_id)
        if not account:
            await update.message.reply_text("❌ No active account.")
            return
        
        schedule_id = await scheduler_manager.add_one_time_schedule(
            user_id, account['id'], target, message, schedule_time
        )
        
        await update.message.reply_text(
            f"✅ Message scheduled!\n\n"
            f"Schedule ID: {schedule_id}\n"
            f"Target: {target}\n"
            f"Time: {schedule_time}\n"
            f"Message: {message}"
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def my_schedules_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View scheduled messages"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    schedules = await db.get_pending_schedules(user_id)
    
    if not schedules:
        await update.callback_query.edit_message_text(
            "📅 **My Schedules**\n\n"
            "No pending schedules.",
            reply_markup=menu_ui.back_button()
        )
        return
    
    text = "📅 **My Schedules**\n\n"
    
    for sch in schedules:
        text += f"ID: {sch['id']}\n"
        text += f"Target: {sch['target']}\n"
        text += f"Time: {sch['schedule_time']}\n"
        text += f"Message: {sch['message'][:50]}...\n\n"
    
    text += "Use `/delschedule <id>` to delete a schedule."
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=menu_ui.back_button(),
        parse_mode='Markdown'
    )

# ============ AUTO REPLY ============

async def auto_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-reply menu"""
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "🤖 **Auto Reply System**\n\n"
        "Automatically reply to incoming messages:",
        reply_markup=menu_ui.auto_reply_menu(),
        parse_mode='Markdown'
    )

async def add_auto_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add auto-reply rule"""
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "➕ **Add Auto-Reply Rule**\n\n"
        "Format:\n"
        "`/addreply <trigger> | <reply>`\n\n"
        "Example:\n"
        "`/addreply hello | Hi there!`",
        parse_mode='Markdown',
        reply_markup=menu_ui.back_button()
    )

async def addreply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add auto-reply rule command"""
    user_id = update.effective_user.id
    
    text = update.message.text.replace('/addreply', '').strip()
    
    if '|' not in text:
        await update.message.reply_text(
            "❌ Invalid format.\n\n"
            "Use: `/addreply <trigger> | <reply>`",
            parse_mode='Markdown'
        )
        return
    
    parts = text.split('|')
    trigger = parts[0].strip()
    reply = parts[1].strip()
    
    account = await db.get_active_account(user_id)
    if not account:
        await update.message.reply_text("❌ No active account.")
        return
    
    rule_id = await db.add_auto_reply(user_id, account['id'], trigger, reply)
    
    await update.message.reply_text(
        f"✅ Auto-reply rule added!\n\n"
        f"Rule ID: {rule_id}\n"
        f"Trigger: {trigger}\n"
        f"Reply: {reply}"
    )

# ============ SCRAPER ============

async def scraper_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scraper menu"""
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "🔍 **Scraper Tools**\n\n"
        "Extract data from Telegram:",
        reply_markup=menu_ui.scraper_menu(),
        parse_mode='Markdown'
    )

async def scrape_members_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scrape group members"""
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "👥 **Scrape Group Members**\n\n"
        "Format:\n"
        "`/scrape <group_username> [limit]`\n\n"
        "Example:\n"
        "`/scrape @mygroup 500`",
        parse_mode='Markdown',
        reply_markup=menu_ui.back_button()
    )

async def scrape_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scrape group members command"""
    user_id = update.effective_user.id
    
    if len(context.args) < 1:
        await update.message.reply_text(
            "❌ Usage: `/scrape <group_username> [limit]`",
            parse_mode='Markdown'
        )
        return
    
    group = context.args[0]
    limit = int(context.args[1]) if len(context.args) > 1 else 1000
    
    await update.message.reply_text("🔍 Scraping members... Please wait.")
    
    result = await scraper.scrape_group_members(user_id, group, limit)
    
    if result['success']:
        # Create CSV file
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=['id', 'username', 'first_name', 'last_name', 'phone'])
        writer.writeheader()
        writer.writerows(result['members'])
        
        output.seek(0)
        
        await update.message.reply_document(
            document=output.getvalue().encode(),
            filename=f"{group}_members.csv",
            caption=f"✅ Scraped {result['total']} members from {group}"
        )
    else:
        await update.message.reply_text(f"❌ Error: {result['error']}")

# ============ ESCROW ============

async def escrow_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Escrow system"""
    await escrow_manager.start_escrow_process(update, context)

async def escrow_form_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle escrow form submission"""
    if context.user_data.get('awaiting_escrow_form'):
        await escrow_manager.process_escrow_form(update, context)

# ============ ANALYTICS ============

async def analytics_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show analytics"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    stats = await analytics.get_user_stats(user_id)
    
    text = (
        f"📊 **Your Analytics**\n\n"
        f"📨 Total Sent: {stats['total_sent']}\n"
        f"⏰ Active Schedules: {stats['active_schedules']}\n"
        f"🤖 Auto-Reply Rules: {stats['active_auto_replies']}\n"
        f"💼 Escrow Deals: {stats['total_escrow_deals']}\n"
        f"👥 Total Accounts: {stats['total_accounts']}\n"
        f"✅ Active Accounts: {stats['active_accounts']}"
    )
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=menu_ui.back_button(),
        parse_mode='Markdown'
    )

# ============ SENT MESSAGES ============

async def sent_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View sent messages"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    messages = await db.get_sent_messages(user_id, limit=20)
    
    if not messages:
        await update.callback_query.edit_message_text(
            "📨 **Sent Messages**\n\n"
            "No messages sent yet.",
            reply_markup=menu_ui.back_button()
        )
        return
    
    text = "📨 **Recent Sent Messages**\n\n"
    
    for msg in messages[:10]:
        text += f"To: {msg['target']}\n"
        text += f"Message: {msg['message'][:50]}...\n"
        text += f"Time: {msg['sent_at']}\n\n"
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=menu_ui.back_button(),
        parse_mode='Markdown'
    )

# ============ STATUS ============

async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show status"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    account = await db.get_active_account(user_id)
    
    if account:
        client = await client_manager.get_client(user_id, account['id'])
        is_connected = client.is_connected() if client else False
        
        text = (
            f"📈 **System Status**\n\n"
            f"✅ Active Account: {account['phone']}\n"
            f"{'🟢' if is_connected else '🔴'} Connection: {'Active' if is_connected else 'Disconnected'}\n"
            f"🆔 Account ID: {account['id']}\n\n"
            f"Everything is working properly!"
        )
    else:
        text = "❌ No active account. Please login first."
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=menu_ui.back_button(),
        parse_mode='Markdown'
    )

# ============ LOGOUT ============

async def logout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Logout current account"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    account = await db.get_active_account(user_id)
    
    if account:
        await client_manager.remove_client(user_id, account['id'])
        await db.delete_account(account['id'], user_id)
        
        await update.callback_query.edit_message_text(
            "✅ Logged out successfully!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔐 Login Again", callback_data="add_account")
            ]])
        )
    else:
        await update.callback_query.edit_message_text("❌ No active account to logout.")

# ============ TELETHON EVENT HANDLERS ============

async def setup_userbot_handlers(user_id, account_id, client):
    """Setup event handlers for userbot"""
    
    @client.on(events.NewMessage(incoming=True))
    async def handle_incoming(event):
        # Auto-reply handler
        await auto_reply_handler.handle_incoming_message(event, user_id, account_id)
        
        # Escrow reply handler
        await escrow_manager.handle_escrow_reply(event)
    
    print(f"Userbot handlers setup for user {user_id}, account {account_id}")

# ============ MAIN APPLICATION ============

async def post_init(application: Application):
    """Post-initialization tasks"""
    # Initialize database
    await db.init_db()
    
    # Start scheduler
    scheduler_manager.start_scheduler_job()
    
    print("✅ Bot initialized successfully!")

def main():
    """Main function - FIXED VERSION"""
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    # Login conversation handler
    login_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(login_handler.start_login, pattern='^add_account$')],
        states={
            API_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_handler.receive_api_id)],
            API_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_handler.receive_api_hash)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_handler.receive_phone)],
            OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_handler.receive_otp)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_handler.receive_password)],
        },
        fallbacks=[CommandHandler('cancel', login_handler.cancel_login)],
        per_message=True
    )
    
    # Add handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(login_conv)
    
    # Callback query handlers
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern='^main_menu$'))
    application.add_handler(CallbackQueryHandler(send_message_handler, pattern='^send_message$'))
    application.add_handler(CallbackQueryHandler(multi_account_handler, pattern='^multi_account$'))
    application.add_handler(CallbackQueryHandler(view_accounts_handler, pattern='^view_accounts$'))
    application.add_handler(CallbackQueryHandler(schedule_handler, pattern='^schedule$'))
    application.add_handler(CallbackQueryHandler(schedule_onetime_handler, pattern='^schedule_onetime$'))
    application.add_handler(CallbackQueryHandler(my_schedules_handler, pattern='^my_schedules$'))
    application.add_handler(CallbackQueryHandler(auto_reply_handler, pattern='^auto_reply$'))
    application.add_handler(CallbackQueryHandler(add_auto_reply_handler, pattern='^add_auto_reply$'))
    application.add_handler(CallbackQueryHandler(scraper_handler, pattern='^scraper$'))
    application.add_handler(CallbackQueryHandler(scrape_members_handler, pattern='^scrape_members$'))
    application.add_handler(CallbackQueryHandler(escrow_handler, pattern='^escrow$'))
    application.add_handler(CallbackQueryHandler(analytics_handler, pattern='^analytics$'))
    application.add_handler(CallbackQueryHandler(sent_messages_handler, pattern='^sent_messages$'))
    application.add_handler(CallbackQueryHandler(status_handler, pattern='^status$'))
    application.add_handler(CallbackQueryHandler(logout_handler, pattern='^logout$'))
    
    # Escrow admin handlers
    application.add_handler(CallbackQueryHandler(escrow_manager.approve_escrow, pattern='^escrow_approve_'))
    application.add_handler(CallbackQueryHandler(escrow_manager.reject_escrow, pattern='^escrow_reject_'))
    
    # Command handlers
    application.add_handler(CommandHandler('send', send_command))
    application.add_handler(CommandHandler('switch', switch_account_command))
    application.add_handler(CommandHandler('schedule', schedule_command))
    application.add_handler(CommandHandler('addreply', addreply_command))
    application.add_handler(CommandHandler('scrape', scrape_command))
    
    # Message handler for escrow forms
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, escrow_form_handler))
    
    # Start bot
    print("🚀 Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
