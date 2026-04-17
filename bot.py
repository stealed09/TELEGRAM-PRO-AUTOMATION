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
            pass
        else:
            print(f"BadRequest error: {e}")
    except Exception as e:
        print(f"Error: {e}")

# ============ STARTUP ============

async def auto_start_users():
    """Auto-start monitoring"""
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
                            client = await client_manager.create_client(
                                user_id, account['id'],
                                account['api_id'], account['api_hash'],
                                account['session_string']
                            )
                            
                            await escrow_manager.setup_group_monitoring(user_id, account['id'])
                            await auto_reply_handler.setup_auto_reply(user_id, account['id'], client)
                            
                            print(f"✅ Auto-started user {user_id}")
                        except Exception as e:
                            print(f"❌ Failed user {user_id}: {e}")
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
            f"👋 **Welcome!**\n\n"
            f"Hello {user.first_name}!\n\n"
            f"✨ **Features:**\n"
            f"• 💬 Instant messaging\n"
            f"• ⏰ Scheduler (India time)\n"
            f"• 💼 Escrow (groups)\n"
            f"• 🤖 Auto-reply (personal)\n\n"
            f"Click to login:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"👋 **Welcome Back!**\n\n"
            f"✅ Active: {account['phone']}\n\n"
            f"Choose action:",
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
        menu_text += f"Active: {account['phone']}\n\nChoose:"
        keyboard = menu_ui.main_menu()
    else:
        menu_text = "❌ No account. Login first."
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
        pass

# ============ SEND MESSAGE ============

async def send_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send message"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "💬 **Send Message**\n\n"
            "Type: `<target> <message>`\n\n"
            "Example:\n"
            "`@username Hello!`",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    
    context.user_data['awaiting_send_message'] = True

async def process_send_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process send message"""
    if not context.user_data.get('awaiting_send_message'):
        return
    
    user_id = update.effective_user.id
    text = update.message.text.strip().split(' ', 1)
    
    if len(text) < 2:
        await update.message.reply_text(
            "❌ Invalid format.\n\nUse: `<target> <message>`",
            parse_mode='Markdown',
            reply_markup=menu_ui.main_menu()
        )
        return
    
    target = text[0]
    message = text[1]
    
    result = await message_sender.send_message(user_id, target, message)
    
    context.user_data['awaiting_send_message'] = False
    
    if result['success']:
        await update.message.reply_text(
            f"✅ **Sent!**\n\n"
            f"Target: {target}\n"
            f"Message ID: {result['message_id']}",
            parse_mode='Markdown',
            reply_markup=menu_ui.main_menu()
        )
    else:
        await update.message.reply_text(
            f"❌ Failed: {result['error']}",
            reply_markup=menu_ui.main_menu()
        )

# ============ SCHEDULER ============

async def schedule_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Schedule menu"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "⏰ **Scheduler**\n\n"
            "Choose:",
            reply_markup=menu_ui.schedule_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def schedule_time_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Time schedule"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "⏱️ **Schedule (India Time)**\n\n"
            "Type: `<HH:MM:SS> <target> <message>`\n\n"
            "Example:\n"
            "`21:40:30 @username Hello!`",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    
    context.user_data['awaiting_schedule'] = True

async def process_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process schedule"""
    if not context.user_data.get('awaiting_schedule'):
        return
    
    user_id = update.effective_user.id
    text = update.message.text.strip().split(' ', 2)
    
    if len(text) < 3:
        await update.message.reply_text(
            "❌ Invalid format.\n\nUse: `<HH:MM:SS> <target> <message>`",
            parse_mode='Markdown',
            reply_markup=menu_ui.main_menu()
        )
        return
    
    time_str = text[0]
    target = text[1]
    message = text[2]
    
    account = await db.get_active_account(user_id)
    if not account:
        await update.message.reply_text(
            "❌ No active account.",
            reply_markup=menu_ui.main_menu()
        )
        return
    
    result = await scheduler_manager.add_time_schedule(
        user_id, account['id'], target, message, time_str
    )
    
    context.user_data['awaiting_schedule'] = False
    
    if result['success']:
        await update.message.reply_text(
            f"✅ **Scheduled!**\n\n"
            f"ID: {result['schedule_id']}\n"
            f"Target: {target}\n"
            f"Time: {result['scheduled_for']}\n\n"
            f"⚡ India timezone",
            parse_mode='Markdown',
            reply_markup=menu_ui.main_menu()
        )
    else:
        await update.message.reply_text(
            f"❌ Error: {result['error']}",
            reply_markup=menu_ui.main_menu()
        )

async def my_schedules_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View schedules"""
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
    
    for sch in schedules[:10]:
        text += f"🆔 {sch['id']}\n"
        text += f"📍 {sch['target']}\n"
        text += f"⏰ {sch['schedule_time']}\n\n"
    
    try:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=menu_ui.back_button(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ============ AUTO REPLY ============

async def auto_reply_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-reply menu"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    account = await db.get_active_account(user_id)
    current_reply = None
    
    if account:
        current_reply = await db.get_auto_reply(user_id, account['id'])
    
    text = "🤖 **Auto-Reply**\n\n"
    text += "Works in PERSONAL chats only.\n\n"
    
    if current_reply:
        text += f"📝 Current:\n`{current_reply['reply_text']}`"
    else:
        text += "❌ Not set"
    
    keyboard = [
        [InlineKeyboardButton("➕ Set", callback_data="set_auto_reply")],
    ]
    
    if current_reply:
        keyboard.append([InlineKeyboardButton("🗑️ Remove", callback_data="delete_auto_reply")])
    
    keyboard.append([InlineKeyboardButton("« Back", callback_data="main_menu")])
    
    try:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def set_auto_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set auto-reply"""
    await update.callback_query.answer()
    
    try:
        await update.callback_query.edit_message_text(
            "🤖 **Set Auto-Reply**\n\n"
            "Type your message:\n\n"
            "Example:\n"
            "`I'm unavailable. Will reply soon!`",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    
    context.user_data['awaiting_auto_reply'] = True

async def process_auto_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process auto-reply"""
    if not context.user_data.get('awaiting_auto_reply'):
        return
    
    user_id = update.effective_user.id
    message = update.message.text.strip()
    
    account = await db.get_active_account(user_id)
    if not account:
        await update.message.reply_text(
            "❌ No active account.",
            reply_markup=menu_ui.main_menu()
        )
        return
    
    await db.add_auto_reply(user_id, account['id'], message)
    
    client = await client_manager.get_client(user_id, account['id'])
    if client:
        await auto_reply_handler.setup_auto_reply(user_id, account['id'], client)
    
    context.user_data['awaiting_auto_reply'] = False
    
    await update.message.reply_text(
        f"✅ **Auto-Reply Set!**\n\n"
        f"Message: `{message}`\n\n"
        f"Works in personal chats.",
        reply_markup=menu_ui.main_menu(),
        parse_mode='Markdown'
    )

async def delete_auto_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete auto-reply"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    account = await db.get_active_account(user_id)
    if account:
        await db.delete_auto_reply(user_id, account['id'])
    
    try:
        await update.callback_query.edit_message_text(
            "✅ Auto-reply removed!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="auto_reply")
            ]])
        )
    except BadRequest:
        pass

# ============ ESCROW ============

async def escrow_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Escrow menu"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "💼 **Escrow System**\n\n"
            "✨ Auto-detection in groups\n"
            "⚡ Instant 'BOTH AGREE' reply\n\n"
            "Choose:",
            reply_markup=menu_ui.escrow_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def process_escrow_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process escrow group"""
    if not context.user_data.get('awaiting_escrow_group'):
        return
    
    user_id = update.effective_user.id
    group_identifier = update.message.text.strip()
    
    account = await db.get_active_account(user_id)
    if not account:
        await update.message.reply_text(
            "❌ No active account.",
            reply_markup=menu_ui.main_menu()
        )
        return
    
    try:
        info = await message_sender.get_chat_info(user_id, group_identifier, account['id'])
        
        if info:
            await db.add_escrow_group(
                user_id, account['id'], info.id, info.title or group_identifier
            )
            
            await escrow_manager.setup_group_monitoring(user_id, account['id'])
            
            context.user_data['awaiting_escrow_group'] = False
            
            await update.message.reply_text(
                f"✅ **Group Added!**\n\n"
                f"Group: {info.title}\n"
                f"ID: `{info.id}`\n\n"
                f"📡 Monitoring ACTIVE",
                parse_mode='Markdown',
                reply_markup=menu_ui.main_menu()
            )
        else:
            await update.message.reply_text(
                "❌ Not found. Are you a member?",
                reply_markup=menu_ui.main_menu()
            )
    
    except Exception as e:
        await update.message.reply_text(
            f"❌ Error: {str(e)}",
            reply_markup=menu_ui.main_menu()
        )

# ============ SCRAPER ============

async def scraper_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scraper menu"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "🔍 **Scraper**\n\n"
            "Extract data:",
            reply_markup=menu_ui.scraper_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def scrape_members_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scrape members"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "👥 **Scrape Members**\n\n"
            "Type: `<group> [limit]`\n\n"
            "Example:\n"
            "`@mygroup 500`",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    
    context.user_data['awaiting_scrape'] = True

async def process_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process scrape"""
    if not context.user_data.get('awaiting_scrape'):
        return
    
    user_id = update.effective_user.id
    text = update.message.text.strip().split()
    
    if len(text) < 1:
        await update.message.reply_text(
            "❌ Usage: `<group> [limit]`",
            parse_mode='Markdown',
            reply_markup=menu_ui.main_menu()
        )
        return
    
    group = text[0]
    limit = int(text[1]) if len(text) > 1 else 1000
    
    context.user_data['awaiting_scrape'] = False
    
    await update.message.reply_text("🔍 Scraping...")
    
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
            caption=f"✅ Scraped {result['total']} members",
            reply_markup=menu_ui.main_menu()
        )
    else:
        await update.message.reply_text(
            f"❌ Error: {result['error']}",
            reply_markup=menu_ui.main_menu()
        )

# ============ MULTI-ACCOUNT ============

async def multi_account_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Multi-account menu"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "👥 **Multi-Account**\n\n"
            "Manage accounts:",
            reply_markup=menu_ui.multi_account_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def view_accounts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View accounts"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    accounts = await db.get_all_accounts(user_id)
    
    if not accounts:
        try:
            await update.callback_query.edit_message_text(
                "📋 **Your Accounts**\n\n"
                "No accounts.",
                reply_markup=menu_ui.multi_account_menu()
            )
        except BadRequest:
            pass
        return
    
    text = "📋 **Your Accounts**\n\n"
    
    for acc in accounts:
        status = "✅" if acc['is_active'] else "⚪"
        text += f"{status} {acc['phone']} (ID: {acc['id']})\n"
    
    try:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=menu_ui.multi_account_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ============ ANALYTICS ============

async def analytics_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analytics"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    stats = await analytics.get_user_stats(user_id)
    
    text = (
        f"📊 **Analytics**\n\n"
        f"📨 Sent: {stats['total_sent']}\n"
        f"⏰ Schedules: {stats['active_schedules']}\n"
        f"🤖 Auto-replies: {stats['active_auto_replies']}\n"
        f"💼 Escrow: {stats['total_escrow_deals']}\n"
        f"👥 Accounts: {stats['total_accounts']}"
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
    """Sent messages"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    messages = await db.get_sent_messages(user_id, limit=10)
    
    if not messages:
        try:
            await update.callback_query.edit_message_text(
                "📨 **Sent Messages**\n\n"
                "No messages yet.",
                reply_markup=menu_ui.back_button()
            )
        except BadRequest:
            pass
        return
    
    text = "📨 **Recent Messages**\n\n"
    
    for msg in messages[:10]:
        text += f"To: {msg['target']}\n"
        text += f"Text: {msg['message'][:40]}...\n\n"
    
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
    """Status"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    account = await db.get_active_account(user_id)
    
    if account:
        client = await client_manager.get_client(user_id, account['id'])
        is_connected = client.is_connected() if client else False
        
        escrow_status = escrow_manager.monitoring_active.get(user_id, False)
        scheduler_status = scheduler_manager.is_running
        
        text = (
            f"📈 **Status**\n\n"
            f"✅ Account: {account['phone']}\n"
            f"{'🟢' if is_connected else '🔴'} Connection: {'Active' if is_connected else 'Off'}\n\n"
            f"📡 Escrow: {'✅' if escrow_status else '⏸️'}\n"
            f"⏰ Scheduler: {'✅' if scheduler_status else '❌'}"
        )
    else:
        text = "❌ No account. Login first."
    
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
    """Logout"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    
    account = await db.get_active_account(user_id)
    
    if account:
        await client_manager.remove_client(user_id, account['id'])
        await db.delete_account(account['id'], user_id)
        
        try:
            await update.callback_query.edit_message_text(
                "✅ Logged out!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔐 Login", callback_data="add_account")
                ]])
            )
        except BadRequest:
            pass
    else:
        await update.callback_query.edit_message_text("❌ No account.")

# ============ TEXT MESSAGE ROUTER ============

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route text messages"""
    
    if context.user_data.get('awaiting_auto_reply'):
        await process_auto_reply(update, context)
        return
    
    if context.user_data.get('awaiting_escrow_group'):
        await process_escrow_group(update, context)
        return
    
    if context.user_data.get('awaiting_schedule'):
        await process_schedule(update, context)
        return
    
    if context.user_data.get('awaiting_send_message'):
        await process_send_message(update, context)
        return
    
    if context.user_data.get('awaiting_scrape'):
        await process_scrape(update, context)
        return
    
    await update.message.reply_text(
        "👋 Use /start for menu!",
        reply_markup=menu_ui.main_menu()
    )

# ============ POST INIT ============

async def post_init(application: Application):
    """Post-init"""
    await db.init_db()
    scheduler_manager.start_scheduler_job()
    await auto_start_users()
    
    print("✅ Bot initialized!")
    print("⏰ Scheduler running (1s interval)")
    print("📡 Auto-start complete")

# ============ MAIN ============
def main():
    """Main function"""
    
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    application.add_error_handler(error_handler)
    
    # Login
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
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(login_conv)
    
    # Callbacks
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern='^main_menu$'))
    application.add_handler(CallbackQueryHandler(send_message_handler, pattern='^send_message$'))
    application.add_handler(CallbackQueryHandler(multi_account_handler, pattern='^multi_account$'))
    application.add_handler(CallbackQueryHandler(view_accounts_handler, pattern='^view_accounts$'))
    
    application.add_handler(CallbackQueryHandler(schedule_handler, pattern='^schedule$'))
    application.add_handler(CallbackQueryHandler(schedule_time_handler, pattern='^schedule_time$'))
    application.add_handler(CallbackQueryHandler(my_schedules_handler, pattern='^my_schedules$'))
    
    application.add_handler(CallbackQueryHandler(auto_reply_menu_handler, pattern='^auto_reply$'))
    application.add_handler(CallbackQueryHandler(set_auto_reply_handler, pattern='^set_auto_reply$'))
    application.add_handler(CallbackQueryHandler(delete_auto_reply_handler, pattern='^delete_auto_reply$'))
    
    application.add_handler(CallbackQueryHandler(scraper_handler, pattern='^scraper$'))
    application.add_handler(CallbackQueryHandler(scrape_members_handler, pattern='^scrape_members$'))
    
    application.add_handler(CallbackQueryHandler(escrow_handler, pattern='^escrow$'))
    application.add_handler(CallbackQueryHandler(escrow_manager.add_escrow_group_handler, pattern='^add_escrow_group$'))
    application.add_handler(CallbackQueryHandler(escrow_manager.view_escrow_groups_handler, pattern='^view_escrow_groups$'))
    application.add_handler(CallbackQueryHandler(escrow_manager.toggle_monitoring_handler, pattern='^toggle_escrow_monitoring$'))
    
    application.add_handler(CallbackQueryHandler(analytics_handler, pattern='^analytics$'))
    application.add_handler(CallbackQueryHandler(sent_messages_handler, pattern='^sent_messages$'))
    application.add_handler(CallbackQueryHandler(status_handler, pattern='^status$'))
    application.add_handler(CallbackQueryHandler(logout_handler, pattern='^logout$'))
    
    # Text handler
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_text_messages
    ))
    
    print("🚀 Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
