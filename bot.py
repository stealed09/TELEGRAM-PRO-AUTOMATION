import asyncio
import aiosqlite
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
from telegram.error import BadRequest
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

# Global storage
user_states = {}

# ============ ERROR HANDLER ============

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    try:
        raise context.error
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            # Ignore message not modified errors
            pass
        else:
            print(f"BadRequest error: {e}")
    except Exception as e:
        print(f"Error: {e}")
        if update and hasattr(update, 'effective_user'):
            try:
                await context.bot.send_message(
                    chat_id=update.effective_user.id,
                    text=f"❌ An error occurred. Please try again.\n\nError: {str(e)[:100]}"
                )
            except:
                pass

# ============ STARTUP ============

async def auto_start_users():
    """Auto-start monitoring for users who have accounts"""
    try:
        async with aiosqlite.connect(db.db_name) as database:
            async with database.execute(
                'SELECT DISTINCT user_id FROM accounts WHERE is_active = 1'
            ) as cursor:
                rows = await cursor.fetchall()
                
                for row in rows:
                    user_id = row[0]
                    account = await db.get_active_account(user_id)
                    
                    if account:
                        try:
                            # Reconnect client
                            client = await client_manager.create_client(
                                user_id, account['id'],
                                account['api_id'], account['api_hash'],
                                account['session_string']
                            )
                            
                            # Setup escrow monitoring
                            await escrow_manager.setup_group_monitoring(user_id, account['id'])
                            
                            print(f"✅ Auto-started user {user_id}")
                        except Exception as e:
                            print(f"❌ Failed to auto-start user {user_id}: {e}")
    except Exception as e:
        print(f"❌ Auto-start error: {e}")

# ============ START & MAIN MENU ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    user = update.effective_user
    
    await db.add_user(user.id, user.username)
    
    account = await db.get_active_account(user.id)
    
    if not account:
        keyboard = [[
            InlineKeyboardButton("🔐 Login Account", callback_data="add_account")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"👋 **Welcome to Advanced Telegram Automation Bot!**\n\n"
            f"Hello {user.first_name}!\n\n"
            f"✨ **Features:**\n"
            f"• 💬 Instant messaging (0 delay)\n"
            f"• ⏰ Smart scheduler (HH:MM:SS)\n"
            f"• 💼 Auto escrow detection\n"
            f"• 🤖 Auto-reply system\n"
            f"• 🔍 Group scraper\n\n"
            f"Click below to login:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"👋 **Welcome Back, {user.first_name}!**\n\n"
            f"✅ Active Account: {account['phone']}\n\n"
            f"Choose an action:",
            reply_markup=menu_ui.main_menu(),
            parse_mode='Markdown'
        )

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show main menu"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    account = await db.get_active_account(user.id)
    
    menu_text = f"🏠 **Main Menu**\n\n"
    
    if account:
        menu_text += f"Active Account: {account['phone']}\n\n"
        menu_text += f"Choose an action:"
        keyboard = menu_ui.main_menu()
    else:
        menu_text = "❌ No active account. Please login first."
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔐 Login", callback_data="add_account")
        ]])
    
    try:
        await query.edit_message_text(
            menu_text,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    except BadRequest:
        # Message already has same content, ignore
        pass

# ============ SEND MESSAGE ============

async def send_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle send message"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "💬 **Send Message (Instant)**\n\n"
            "Format:\n"
            "`/send <target> <message>`\n\n"
            "Examples:\n"
            "`/send @username Hello!`\n"
            "`/send 123456789 Hi there`\n"
            "`/send -1001234567890 Group message`\n\n"
            "⚡ **Sends instantly with ZERO delay!**",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass

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
    
    result = await message_sender.send_message(user_id, target, message)
    
    if result['success']:
        await update.message.reply_text(
            f"✅ Message sent **INSTANTLY**!\n\n"
            f"Target: {target}\n"
            f"Message ID: {result['message_id']}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(f"❌ Failed: {result['error']}")

# ============ SCHEDULER (FIXED) ============

async def schedule_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Schedule menu"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "⏰ **Advanced Message Scheduler**\n\n"
            "Choose scheduling type:",
            reply_markup=menu_ui.schedule_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def schedule_instant_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Instant schedule"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "⚡ **Instant Send (Now or X seconds)**\n\n"
            "Format:\n"
            "`/sendnow <target> <message>`  → Send NOW\n"
            "`/sendin <seconds> <target> <message>`  → Send in X seconds\n\n"
            "Examples:\n"
            "`/sendnow @user Hi!`  → Instant\n"
            "`/sendin 30 @user Hello!`  → In 30 seconds\n\n"
            "⚡ **ZERO delay execution!**",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass

async def schedule_time_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Time-based schedule"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "⏱️ **Time Schedule (HH:MM:SS)**\n\n"
            "Format:\n"
            "`/scheduleat <HH:MM:SS> <target> <message>`\n"
            "`/scheduleat <HH:MM> <target> <message>`  (seconds = 00)\n\n"
            "Examples:\n"
            "`/scheduleat 14:30:00 @user Hello!`\n"
            "`/scheduleat 09:15 @group Good morning!`\n\n"
            "⏰ Executes at exact time (today or tomorrow)\n"
            "⚡ **ZERO delay when time arrives!**",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass

async def sendnow_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send message NOW"""
    user_id = update.effective_user.id
    
    if len(context.args) < 2:
        await update.message.reply_text("Usage: `/sendnow <target> <message>`", parse_mode='Markdown')
        return
    
    target = context.args[0]
    message = ' '.join(context.args[1:])
    
    account = await db.get_active_account(user_id)
    if not account:
        await update.message.reply_text("❌ No active account.")
        return
    
    result = await scheduler_manager.add_instant_schedule(
        user_id, account['id'], target, message, 0
    )
    
    if result['success']:
        await update.message.reply_text(
            f"⚡ **Queued for INSTANT execution!**\n\n"
            f"Schedule ID: {result['schedule_id']}\n"
            f"Target: {target}\n"
            f"Executes: **NOW** (within 1 second)",
            parse_mode='Markdown'
        )

async def sendin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send message in X seconds"""
    user_id = update.effective_user.id
    
    if len(context.args) < 3:
        await update.message.reply_text("Usage: `/sendin <seconds> <target> <message>`", parse_mode='Markdown')
        return
    
    try:
        delay = int(context.args[0])
        target = context.args[1]
        message = ' '.join(context.args[2:])
        
        account = await db.get_active_account(user_id)
        if not account:
            await update.message.reply_text("❌ No active account.")
            return
        
        result = await scheduler_manager.add_instant_schedule(
            user_id, account['id'], target, message, delay
        )
        
        if result['success']:
            await update.message.reply_text(
                f"⏰ **Scheduled!**\n\n"
                f"Schedule ID: {result['schedule_id']}\n"
                f"Target: {target}\n"
                f"Executes in: **{delay} seconds**\n"
                f"Exact time: {result['scheduled_for']}",
                parse_mode='Markdown'
            )
    except ValueError:
        await update.message.reply_text("❌ Invalid delay. Must be a number.")

async def scheduleat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Schedule at specific time (HH:MM:SS)"""
    user_id = update.effective_user.id
    
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: `/scheduleat <HH:MM:SS> <target> <message>`",
            parse_mode='Markdown'
        )
        return
    
    time_str = context.args[0]
    target = context.args[1]
    message = ' '.join(context.args[2:])
    
    account = await db.get_active_account(user_id)
    if not account:
        await update.message.reply_text("❌ No active account.")
        return
    
    result = await scheduler_manager.add_time_schedule(
        user_id, account['id'], target, message, time_str
    )
    
    if result['success']:
        await update.message.reply_text(
            f"✅ **Scheduled!**\n\n"
            f"Schedule ID: {result['schedule_id']}\n"
            f"Target: {target}\n"
            f"Time: {time_str}\n"
            f"Executes at: {result['scheduled_for']}\n\n"
            f"⚡ Will execute with **ZERO delay** at exact time!",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(f"❌ Error: {result['error']}")

async def my_schedules_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View scheduled messages"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    schedules = await db.get_pending_schedules(user_id)
    
    if not schedules:
        try:
            await update.callback_query.edit_message_text(
                "📅 **My Schedules**\n\n"
                "No pending schedules.",
                reply_markup=menu_ui.back_button()
            )
        except BadRequest:
            pass
        return
    
    text = "📅 **Pending Schedules**\n\n"
    
    for sch in schedules[:10]:  # Show max 10
        text += f"🆔 ID: {sch['id']}\n"
        text += f"📍 Target: {sch['target']}\n"
        text += f"⏰ Time: {sch['schedule_time']}\n"
        text += f"💬 Message: {sch['message'][:40]}...\n\n"
    
    text += "Use `/cancel <id>` to cancel a schedule."
    
    try:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=menu_ui.back_button(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ============ ESCROW (ADVANCED) ============

async def escrow_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Escrow main menu"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "💼 **Advanced Escrow System**\n\n"
            "✨ **Auto-detection** in monitored groups\n"
            "⚡ **Instant responses** from your account\n"
            "🎛️ **Start/Stop** monitoring anytime\n\n"
            "Choose an option:",
            reply_markup=menu_ui.escrow_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def addescrowgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add escrow monitoring group"""
    user_id = update.effective_user.id
    
    if len(context.args) < 1:
        await update.message.reply_text(
            "Usage: `/addescrowgroup <group_id_or_username>`",
            parse_mode='Markdown'
        )
        return
    
    group_identifier = context.args[0]
    
    account = await db.get_active_account(user_id)
    if not account:
        await update.message.reply_text("❌ No active account.")
        return
    
    try:
        # Get group info
        info = await message_sender.get_chat_info(user_id, group_identifier, account['id'])
        
        if info:
            # Add to database
            await db.add_escrow_group(
                user_id, account['id'], info.id, info.title or group_identifier
            )
            
            # Setup monitoring
            await escrow_manager.setup_group_monitoring(user_id, account['id'])
            
            await update.message.reply_text(
                f"✅ **Escrow group added!**\n\n"
                f"Group: {info.title}\n"
                f"ID: `{info.id}`\n\n"
                f"📡 Auto-detection is now **ACTIVE**\n\n"
                f"Send escrow forms in this group and I'll auto-reply!",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Could not find group. Make sure you're a member.")
    
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ============ MULTI-ACCOUNT ============

async def multi_account_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Multi-account menu"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "👥 **Multi-Account Management**\n\n"
            "Manage your Telegram accounts:",
            reply_markup=menu_ui.multi_account_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def view_accounts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View all accounts"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    accounts = await db.get_all_accounts(user_id)
    
    if not accounts:
        try:
            await update.callback_query.edit_message_text(
                "📋 **Your Accounts**\n\n"
                "No accounts found. Add one to get started!",
                reply_markup=menu_ui.multi_account_menu()
            )
        except BadRequest:
            pass
        return
    
    text = "📋 **Your Accounts**\n\n"
    
    for acc in accounts:
        status = "✅ Active" if acc['is_active'] else "⚪ Inactive"
        text += f"{status} - {acc['phone']} (ID: {acc['id']})\n"
    
    text += "\nUse `/switch <account_id>` to change active account."
    
    try:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=menu_ui.multi_account_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

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

# ============ AUTO REPLY ============

async def auto_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-reply menu"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "🤖 **Auto Reply System**\n\n"
            "Automatically reply to incoming messages:",
            reply_markup=menu_ui.auto_reply_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def add_auto_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add auto-reply rule"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "➕ **Add Auto-Reply Rule**\n\n"
            "Format:\n"
            "`/addreply <trigger> | <reply>`\n\n"
            "Example:\n"
            "`/addreply hello | Hi there!`",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass

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
    try:
        await update.callback_query.edit_message_text(
            "🔍 **Scraper Tools**\n\n"
            "Extract data from Telegram:",
            reply_markup=menu_ui.scraper_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def scrape_members_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scrape group members"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "👥 **Scrape Group Members**\n\n"
            "Format:\n"
            "`/scrape <group_username> [limit]`\n\n"
            "Example:\n"
            "`/scrape @mygroup 500`",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass

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
    
    try:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=menu_ui.back_button(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ============ SENT MESSAGES ============

async def sent_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View sent messages"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    messages = await db.get_sent_messages(user_id, limit=20)
    
    if not messages:
        try:
            await update.callback_query.edit_message_text(
                "📨 **Sent Messages**\n\n"
                "No messages sent yet.",
                reply_markup=menu_ui.back_button()
            )
        except BadRequest:
            pass
        return
    
    text = "📨 **Recent Sent Messages**\n\n"
    
    for msg in messages[:10]:
        text += f"To: {msg['target']}\n"
        text += f"Message: {msg['message'][:50]}...\n"
        text += f"Time: {msg['sent_at']}\n\n"
    
    try:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=menu_ui.back_button(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ============ STATUS ============

async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show status"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    account = await db.get_active_account(user_id)
    
    if account:
        client = await client_manager.get_client(user_id, account['id'])
        is_connected = client.is_connected() if client else False
        
        escrow_status = escrow_manager.monitoring_active.get(user_id, False)
        scheduler_status = scheduler_manager.is_running
        
        text = (
            f"📈 **System Status**\n\n"
            f"✅ Active Account: {account['phone']}\n"
            f"{'🟢' if is_connected else '🔴'} Connection: {'Active' if is_connected else 'Disconnected'}\n"
            f"🆔 Account ID: {account['id']}\n\n"
            f"📡 Escrow Monitoring: {'✅ ON' if escrow_status else '⏸️ OFF'}\n"
            f"⏰ Scheduler: {'✅ Running (1s check)' if scheduler_status else '❌ Stopped'}\n\n"
            f"🚀 All systems operational!"
        )
    else:
        text = "❌ No active account. Please login first."
    
    try:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=menu_ui.back_button(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ============ LOGOUT ============

async def logout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Logout current account"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    account = await db.get_active_account(user_id)
    
    if account:
        await client_manager.remove_client(user_id, account['id'])
        await db.delete_account(account['id'], user_id)
        
        try:
            await update.callback_query.edit_message_text(
                "✅ Logged out successfully!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔐 Login Again", callback_data="add_account")
                ]])
            )
        except BadRequest:
            pass
    else:
        await update.callback_query.edit_message_text("❌ No active account to logout.")

# ============ MAIN APPLICATION ============
async def post_init(application: Application):
    """Post-initialization tasks"""
    # Initialize database
    await db.init_db()
    
    # Start scheduler (checking every SECOND)
    scheduler_manager.start_scheduler_job()
    
    # Auto-start users
    await auto_start_users()
    
    print("✅ Bot initialized successfully!")
    print("⏰ Scheduler running (1-second interval)")
    print("📡 Auto-start complete")

def main():
    """Main function"""
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    # Add error handler
    application.add_error_handler(error_handler)
    
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
        fallbacks=[CommandHandler('cancel', login_handler.cancel_login)]
    )
    
    # Add handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(login_conv)
    
    # Callback query handlers
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern='^main_menu$'))
    application.add_handler(CallbackQueryHandler(send_message_handler, pattern='^send_message$'))
    application.add_handler(CallbackQueryHandler(multi_account_handler, pattern='^multi_account$'))
    application.add_handler(CallbackQueryHandler(view_accounts_handler, pattern='^view_accounts$'))
    
    # Scheduler handlers
    application.add_handler(CallbackQueryHandler(schedule_handler, pattern='^schedule$'))
    application.add_handler(CallbackQueryHandler(schedule_instant_handler, pattern='^schedule_instant$'))
    application.add_handler(CallbackQueryHandler(schedule_time_handler, pattern='^schedule_time$'))
    application.add_handler(CallbackQueryHandler(my_schedules_handler, pattern='^my_schedules$'))
    
    # Auto-reply handlers
    application.add_handler(CallbackQueryHandler(auto_reply_handler, pattern='^auto_reply$'))
    application.add_handler(CallbackQueryHandler(add_auto_reply_handler, pattern='^add_auto_reply$'))
    
    # Scraper handlers
    application.add_handler(CallbackQueryHandler(scraper_handler, pattern='^scraper$'))
    application.add_handler(CallbackQueryHandler(scrape_members_handler, pattern='^scrape_members$'))
    
    # Escrow handlers
    application.add_handler(CallbackQueryHandler(escrow_handler, pattern='^escrow$'))
    application.add_handler(CallbackQueryHandler(escrow_manager.add_escrow_group_handler, pattern='^add_escrow_group$'))
    application.add_handler(CallbackQueryHandler(escrow_manager.view_escrow_groups_handler, pattern='^view_escrow_groups$'))
    application.add_handler(CallbackQueryHandler(escrow_manager.toggle_monitoring_handler, pattern='^toggle_escrow_monitoring$'))
    application.add_handler(CallbackQueryHandler(escrow_manager.approve_escrow, pattern='^escrow_approve_'))
    application.add_handler(CallbackQueryHandler(escrow_manager.reject_escrow, pattern='^escrow_reject_'))

    # Other handlers
    application.add_handler(CallbackQueryHandler(analytics_handler, pattern='^analytics$'))
    application.add_handler(CallbackQueryHandler(sent_messages_handler, pattern='^sent_messages$'))
    application.add_handler(CallbackQueryHandler(status_handler, pattern='^status$'))
    application.add_handler(CallbackQueryHandler(logout_handler, pattern='^logout$'))
    
    # Command handlers
    application.add_handler(CommandHandler('send', send_command))
    application.add_handler(CommandHandler('sendnow', sendnow_command))
    application.add_handler(CommandHandler('sendin', sendin_command))
    application.add_handler(CommandHandler('scheduleat', scheduleat_command))
    application.add_handler(CommandHandler('switch', switch_account_command))
    application.add_handler(CommandHandler('addreply', addreply_command))
    application.add_handler(CommandHandler('scrape', scrape_command))
    application.add_handler(CommandHandler('addescrowgroup', addescrowgroup_command))
    
    # Start bot
    print("🚀 Starting Advanced Telegram Automation Bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
