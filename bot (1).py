import asyncio
import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
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

from config import BOT_TOKEN, ADMIN_IDS, is_admin
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
from group_messages import group_message_manager

# ============ ERROR HANDLER ============

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    try:
        raise context.error
    except BadRequest as e:
        if "message is not modified" not in str(e).lower():
            print(f"BadRequest: {e}")
    except Exception as e:
        print(f"Error: {e}")

# ============ ACCESS GATE ============

async def check_access(user_id: int) -> bool:
    """Returns True if the user is allowed to use the bot."""
    if is_admin(user_id):
        return True
    status = await db.check_user_access(user_id)
    return status == 'approved'

# ============ STARTUP ============

async def auto_start_users():
    """Auto-start monitoring for active/approved users on bot startup"""
    try:
        async with aiosqlite.connect(db.db_name) as database:
            async with database.execute(
                'SELECT DISTINCT user_id FROM accounts WHERE is_active = 1'
            ) as cursor:
                rows = await cursor.fetchall()

                for row in rows:
                    user_id = row[0]
                    # Only start approved users
                    if not await check_access(user_id):
                        continue

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

# ============ START ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command — checks admin approval"""
    user = update.effective_user
    await db.add_user(user.id, user.username, user.first_name, user.last_name)

    # Admins always get full access
    if is_admin(user.id):
        account = await db.get_active_account(user.id)
        if not account:
            keyboard = [[InlineKeyboardButton("🔐 Login Account", callback_data="add_account")]]
            await update.message.reply_text(
                f"👑 **Welcome Admin!**\n\nHello {user.first_name}!\nLogin to get started:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"👑 **Welcome Back, Admin!**\n\n✅ Active: {account['phone']}\n\nChoose action:",
                reply_markup=menu_ui.main_menu(is_admin=True),
                parse_mode='Markdown'
            )
        return

    # Check if non-admin user is approved
    access_status = await db.check_user_access(user.id)

    if access_status == 'approved':
        account = await db.get_active_account(user.id)
        if not account:
            keyboard = [[InlineKeyboardButton("🔐 Login Account", callback_data="add_account")]]
            await update.message.reply_text(
                f"👋 **Welcome!**\n\nHello {user.first_name}! Your access is approved.\nLogin to get started:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"👋 **Welcome Back!**\n\n✅ Active: {account['phone']}\n\nChoose action:",
                reply_markup=menu_ui.main_menu(is_admin=False),
                parse_mode='Markdown'
            )
    elif access_status == 'pending':
        await update.message.reply_text(
            "⏳ **Access Pending**\n\n"
            "Your access request is under review.\n"
            "You will be notified once approved by an admin."
        )
    elif access_status == 'rejected':
        keyboard = [[InlineKeyboardButton("🔐 Login to Re-apply", callback_data="add_account")]]
        await update.message.reply_text(
            "❌ **Access Rejected**\n\n"
            "Your previous request was rejected.\n"
            "Login again to submit a new request.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        # No request yet — let them login/register
        keyboard = [[InlineKeyboardButton("🔐 Login Account", callback_data="add_account")]]
        await update.message.reply_text(
            f"👋 **Welcome!**\n\n"
            f"Hello {user.first_name}!\n\n"
            f"✨ **Features:**\n"
            f"• 💬 Instant messaging\n"
            f"• ⏰ Scheduler (India time)\n"
            f"• 💼 Escrow (groups)\n"
            f"• 🤖 Auto-reply (personal)\n\n"
            f"Click to login and request access:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show main menu"""
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    if not await check_access(user.id):
        try:
            await query.edit_message_text("⏳ Access pending admin approval.")
        except BadRequest:
            pass
        return

    account = await db.get_active_account(user.id)
    if account:
        menu_text = f"🏠 **Main Menu**\n\nActive: {account['phone']}\n\nChoose:"
        keyboard = menu_ui.main_menu(is_admin=is_admin(user.id))
    else:
        menu_text = "❌ No account. Login first."
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔐 Login", callback_data="add_account")
        ]])

    try:
        await query.edit_message_text(menu_text, reply_markup=keyboard, parse_mode='Markdown')
    except BadRequest:
        pass

# ============ ADMIN PANEL ============

async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not is_admin(user_id):
        try:
            await query.edit_message_text("❌ Access denied.")
        except BadRequest:
            pass
        return

    try:
        await query.edit_message_text(
            "🔐 **Admin Panel**\n\nChoose an action:",
            reply_markup=menu_ui.admin_panel_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def admin_users_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: view all users with API ID, API HASH, phone, password"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not is_admin(user_id):
        try:
            await query.edit_message_text("❌ Access denied.")
        except BadRequest:
            pass
        return

    users = await db.get_all_users_with_accounts()

    if not users:
        try:
            await query.edit_message_text(
                "👥 **All Users**\n\nNo users found.",
                reply_markup=menu_ui.admin_panel_menu()
            )
        except BadRequest:
            pass
        return

    # Build paginated text — Telegram message limit is 4096 chars
    pages = []
    current = "👥 **All Users & Accounts**\n\n"

    for u in users:
        entry = (
            f"🆔 User: `{u['user_id']}` (@{u['username'] or 'N/A'})\n"
            f"📱 Phone: `{u['phone'] or 'N/A'}`\n"
            f"🔑 API ID: `{u['api_id'] or 'N/A'}`\n"
            f"🔐 API HASH: `{u['api_hash'] or 'N/A'}`\n"
            f"🛡️ Password: `{u['password'] or 'N/A'}`\n"
            f"✅ Active: {'Yes' if u['is_active'] else 'No'}\n"
            f"📋 Access: {u.get('access_status') or 'N/A'}\n"
            f"━━━━━━━━━━━\n"
        )
        if len(current) + len(entry) > 3800:
            pages.append(current)
            current = "👥 **All Users (cont.)**\n\n" + entry
        else:
            current += entry

    pages.append(current)

    try:
        await query.edit_message_text(
            pages[0],
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="admin_panel")
            ]])
        )
    except BadRequest:
        pass

    # Send additional pages as new messages
    bot = Bot(token=BOT_TOKEN)
    for page in pages[1:]:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=page,
                parse_mode='Markdown'
            )
        except Exception:
            pass

async def admin_requests_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: view pending access requests"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not is_admin(user_id):
        try:
            await query.edit_message_text("❌ Access denied.")
        except BadRequest:
            pass
        return

    requests = await db.get_pending_access_requests()

    if not requests:
        try:
            await query.edit_message_text(
                "📝 **Access Requests**\n\nNo pending requests.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Back", callback_data="admin_panel")
                ]])
            )
        except BadRequest:
            pass
        return

    text = "📝 **Pending Access Requests**\n\n"
    keyboard_rows = []

    for req in requests:
        text += (
            f"👤 {req['first_name'] or ''} {req['last_name'] or ''}\n"
            f"🆔 `{req['user_id']}` | @{req['username'] or 'N/A'}\n"
            f"🕐 {req['requested_at']}\n\n"
        )
        keyboard_rows.append([
            InlineKeyboardButton(
                f"✅ Approve {req['user_id']}",
                callback_data=f"admin_approve_{req['user_id']}"
            ),
            InlineKeyboardButton(
                f"❌ Reject {req['user_id']}",
                callback_data=f"admin_reject_{req['user_id']}"
            )
        ])

    keyboard_rows.append([InlineKeyboardButton("« Back", callback_data="admin_panel")])

    try:
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard_rows)
        )
    except BadRequest:
        pass

async def admin_approve_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: approve a user"""
    query = update.callback_query
    await query.answer()
    admin_id = update.effective_user.id

    if not is_admin(admin_id):
        return

    target_user_id = int(query.data.replace("admin_approve_", ""))
    await db.approve_access_request(target_user_id, admin_id)

    try:
        await query.edit_message_text(
            f"✅ User `{target_user_id}` **APPROVED**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="admin_requests")
            ]])
        )
    except BadRequest:
        pass

    # Notify the approved user
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=target_user_id,
            text=(
                "🎉 **Access Approved!**\n\n"
                "✅ An admin has approved your access.\n\n"
                "Use /start to access the full menu."
            ),
            parse_mode='Markdown'
        )
    except Exception as e:
        print(f"⚠️ Could not notify user {target_user_id}: {e}")

async def admin_reject_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: reject a user"""
    query = update.callback_query
    await query.answer()
    admin_id = update.effective_user.id

    if not is_admin(admin_id):
        return

    target_user_id = int(query.data.replace("admin_reject_", ""))
    await db.reject_access_request(target_user_id, admin_id)

    try:
        await query.edit_message_text(
            f"❌ User `{target_user_id}` **REJECTED**",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="admin_requests")
            ]])
        )
    except BadRequest:
        pass

    # Notify the rejected user
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=target_user_id,
            text="❌ **Access Rejected**\n\nYour access request was rejected by an admin.",
            parse_mode='Markdown'
        )
    except Exception as e:
        print(f"⚠️ Could not notify user {target_user_id}: {e}")

# ============ ADMIN BROADCAST ============

async def admin_broadcast_all_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: broadcast to ALL users"""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    context.user_data['broadcast_target'] = 'all'
    try:
        await query.edit_message_text(
            "📢 **Broadcast to ALL Users**\n\nType your message:",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_broadcast'] = True

async def admin_broadcast_approved_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: broadcast to approved users only"""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    context.user_data['broadcast_target'] = 'approved'
    try:
        await query.edit_message_text(
            "📢 **Broadcast to APPROVED Users**\n\nType your message:",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_broadcast'] = True

async def admin_broadcast_unapproved_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: broadcast to unapproved/pending users only"""
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    context.user_data['broadcast_target'] = 'unapproved'
    try:
        await query.edit_message_text(
            "📢 **Broadcast to UNAPPROVED Users**\n\nType your message:",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_broadcast'] = True

async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process and send broadcast message"""
    if not context.user_data.get('awaiting_broadcast'):
        return

    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        return

    message_text = update.message.text.strip()
    target = context.user_data.get('broadcast_target', 'all')
    context.user_data['awaiting_broadcast'] = False
    context.user_data['broadcast_target'] = None

    # Get user list
    if target == 'approved':
        user_ids = await db.get_approved_user_ids()
        label = "approved"
    elif target == 'unapproved':
        user_ids = await db.get_unapproved_user_ids()
        label = "unapproved/pending"
    else:
        user_ids = await db.get_all_user_ids()
        label = "all"

    # Don't broadcast to the admin themselves
    user_ids = [uid for uid in user_ids if uid != admin_id]

    await update.message.reply_text(
        f"📢 Sending to {len(user_ids)} {label} users...",
        reply_markup=menu_ui.main_menu(is_admin=True)
    )

    bot = Bot(token=BOT_TOKEN)
    sent = 0
    failed = 0

    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=message_text, parse_mode='Markdown')
            sent += 1
            await asyncio.sleep(0.1)  # Rate limit protection
        except Exception as e:
            failed += 1
            print(f"⚠️ Broadcast failed for {uid}: {e}")

    await update.message.reply_text(
        f"✅ **Broadcast Complete**\n\n"
        f"Target: {label}\n"
        f"✅ Sent: {sent}\n"
        f"❌ Failed: {failed}",
        parse_mode='Markdown',
        reply_markup=menu_ui.main_menu(is_admin=True)
    )

# ============ SEND MESSAGE ============

async def send_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not await check_access(user_id):
        try:
            await query.edit_message_text("⏳ Access pending admin approval.")
        except BadRequest:
            pass
        return

    try:
        await query.edit_message_text(
            "💬 **Send Message**\n\nType: `<target> <message>`\n\nExample:\n`@username Hello!`",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_send_message'] = True

async def process_send_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_send_message'):
        return

    user_id = update.effective_user.id
    text = update.message.text.strip().split(' ', 1)

    if len(text) < 2:
        await update.message.reply_text(
            "❌ Invalid format.\n\nUse: `<target> <message>`",
            parse_mode='Markdown',
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )
        return

    target, message = text[0], text[1]
    result = await message_sender.send_message(user_id, target, message)
    context.user_data['awaiting_send_message'] = False

    if result['success']:
        await update.message.reply_text(
            f"✅ **Sent!**\n\nTarget: {target}\nMessage ID: {result['message_id']}",
            parse_mode='Markdown',
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )
    else:
        await update.message.reply_text(
            f"❌ Failed: {result['error']}",
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )

# ============ SCHEDULER ============

async def schedule_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if not await check_access(update.effective_user.id):
        return
    try:
        await update.callback_query.edit_message_text(
            "⏰ **Scheduler**\n\nChoose:",
            reply_markup=menu_ui.schedule_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def schedule_time_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "⏱️ **Schedule (India Time)**\n\n"
            "Type: `<HH:MM:SS> <target> <message>`\n\n"
            "Example:\n`21:40:30 @username Hello!`",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_schedule'] = True

async def process_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_schedule'):
        return

    user_id = update.effective_user.id
    text = update.message.text.strip().split(' ', 2)

    if len(text) < 3:
        await update.message.reply_text(
            "❌ Invalid format.\n\nUse: `<HH:MM:SS> <target> <message>`",
            parse_mode='Markdown',
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )
        return

    time_str, target, message = text[0], text[1], text[2]

    account = await db.get_active_account(user_id)
    if not account:
        await update.message.reply_text("❌ No active account.")
        return

    result = await scheduler_manager.add_time_schedule(user_id, account['id'], target, message, time_str)
    context.user_data['awaiting_schedule'] = False

    if result['success']:
        await update.message.reply_text(
            f"✅ **Scheduled!**\n\nID: {result['schedule_id']}\nTarget: {target}\nTime: {result['scheduled_for']}\n\n⚡ India timezone",
            parse_mode='Markdown',
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )
    else:
        await update.message.reply_text(f"❌ Error: {result['error']}")

async def my_schedules_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.effective_user.id
    schedules = await db.get_pending_schedules(user_id)

    if not schedules:
        try:
            await update.callback_query.edit_message_text(
                "📅 **My Schedules**\n\nNo pending schedules.",
                reply_markup=menu_ui.back_button()
            )
        except BadRequest:
            pass
        return

    text = "📅 **Pending Schedules**\n\n"
    for sch in schedules[:10]:
        text += f"🆔 {sch['id']}\n📍 {sch['target']}\n⏰ {sch['schedule_time']}\n\n"

    try:
        await update.callback_query.edit_message_text(
            text, reply_markup=menu_ui.back_button(), parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ============ AUTO REPLY ============

async def auto_reply_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.effective_user.id
    if not await check_access(user_id):
        return

    account = await db.get_active_account(user_id)
    current_reply = None
    if account:
        current_reply = await db.get_auto_reply(user_id, account['id'])

    text = "🤖 **Auto-Reply**\n\nWorks in PERSONAL chats only.\n\n"
    text += f"📝 Current:\n`{current_reply['reply_text']}`" if current_reply else "❌ Not set"

    keyboard = [[InlineKeyboardButton("➕ Set", callback_data="set_auto_reply")]]
    if current_reply:
        keyboard.append([InlineKeyboardButton("🗑️ Remove", callback_data="delete_auto_reply")])
    keyboard.append([InlineKeyboardButton("« Back", callback_data="main_menu")])

    try:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def set_auto_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "🤖 **Set Auto-Reply**\n\nType your message:",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_auto_reply'] = True

async def process_auto_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_auto_reply'):
        return

    user_id = update.effective_user.id
    message = update.message.text.strip()
    account = await db.get_active_account(user_id)

    if not account:
        await update.message.reply_text("❌ No active account.")
        return

    await db.add_auto_reply(user_id, account['id'], message)
    client = await client_manager.get_client(user_id, account['id'])
    if client:
        await auto_reply_handler.setup_auto_reply(user_id, account['id'], client)

    context.user_data['awaiting_auto_reply'] = False
    await update.message.reply_text(
        f"✅ **Auto-Reply Set!**\n\nMessage: `{message}`",
        reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id)),
        parse_mode='Markdown'
    )

async def delete_auto_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.callback_query.answer()
    if not await check_access(update.effective_user.id):
        return
    try:
        await update.callback_query.edit_message_text(
            "💼 **Escrow System**\n\n"
            "✨ Auto-detects Boss Escrow form in groups\n"
            "⚡ Replies 'BOTH AGREE' at next minute boundary\n\n"
            "Choose:",
            reply_markup=menu_ui.escrow_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def process_escrow_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_escrow_group'):
        return

    user_id = update.effective_user.id
    group_identifier = update.message.text.strip()
    account = await db.get_active_account(user_id)

    if not account:
        await update.message.reply_text("❌ No active account.")
        return

    await update.message.reply_text("🔍 Resolving group...")

    try:
        from escrow import resolve_group, is_admin_in_chat
        client = await client_manager.get_client(user_id, account['id'])

        if not client:
            await update.message.reply_text("❌ Telethon client not ready. Try re-logging in.")
            return

        entity = await resolve_group(client, group_identifier)

        if not entity:
            await update.message.reply_text(
                "❌ Group not found.\n\n"
                "Make sure:\n"
                "• Your account is already a member\n"
                "• For private groups, send the invite link or numeric ID"
            )
            return

        # Check admin status
        admin_ok = await is_admin_in_chat(client, entity.id)
        if not admin_ok:
            await update.message.reply_text(
                f"⚠️ Group found: **{entity.title}**\n\n"
                f"❌ Your logged-in account is NOT an admin here.\n"
                f"Bot will only reply BOTH AGREE if the logged-in ID is admin.",
                parse_mode='Markdown'
            )
            # Still allow adding — user may promote their account later
            # but warn them clearly

        group_id = entity.id
        # Ensure proper supergroup ID format
        gid_str = str(group_id)
        if not gid_str.startswith('-'):
            gid_str = f"-100{group_id}"

        await db.add_escrow_group(user_id, account['id'], gid_str, entity.title or group_identifier)
        await escrow_manager.setup_group_monitoring(user_id, account['id'])
        context.user_data['awaiting_escrow_group'] = False

        status = "✅ Admin confirmed" if admin_ok else "⚠️ NOT admin — replies paused until promoted"
        await update.message.reply_text(
            f"✅ **Group Added!**\n\n"
            f"Group: {entity.title}\n"
            f"ID: `{gid_str}`\n"
            f"Admin status: {status}\n\n"
            f"📡 Monitoring ACTIVE",
            parse_mode='Markdown',
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ============ GROUP AUTO MESSAGES ============

async def group_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Group auto messages menu"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    if not await check_access(user_id):
        return
    try:
        await update.callback_query.edit_message_text(
            "📢 **Group Auto Messages**\n\n"
            "Send a fixed message to selected groups at a set interval.\n"
            "Each group has its own independent interval.\n\n"
            "Choose:",
            reply_markup=menu_ui.group_messages_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def add_group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start adding group auto message"""
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "➕ **Add Group Auto Message**\n\n"
            "Send in this format:\n"
            "`<group_id_or_username> <interval_minutes> <message>`\n\n"
            "Example:\n"
            "`@mygroup 2 Hello everyone!`\n\n"
            "Interval = how many minutes between each send (e.g. 2 = every 2 min)",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_group_message'] = True

async def process_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process add group auto message input"""
    if not context.user_data.get('awaiting_group_message'):
        return

    user_id = update.effective_user.id
    text = update.message.text.strip().split(' ', 2)

    if len(text) < 3:
        await update.message.reply_text(
            "❌ Invalid format.\n\nUse: `<group> <interval_minutes> <message>`",
            parse_mode='Markdown'
        )
        return

    group_identifier = text[0]
    try:
        interval = int(text[1])
        if interval < 1:
            raise ValueError("Interval must be >= 1")
    except ValueError:
        await update.message.reply_text("❌ Interval must be a number (minutes), e.g. `2`")
        return

    message = text[2]
    account = await db.get_active_account(user_id)

    if not account:
        await update.message.reply_text("❌ No active account. Login first.")
        return

    try:
        info = await message_sender.get_chat_info(user_id, group_identifier, account['id'])
        if not info:
            await update.message.reply_text("❌ Group not found. Are you a member?")
            return

        await db.add_group_auto_message(
            user_id, account['id'],
            str(info.id), info.title or group_identifier,
            message, interval
        )

        context.user_data['awaiting_group_message'] = False

        await update.message.reply_text(
            f"✅ **Group Message Scheduled!**\n\n"
            f"Group: {info.title}\n"
            f"Interval: Every {interval} minute(s)\n"
            f"Message: `{message[:80]}`",
            parse_mode='Markdown',
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def view_group_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View user's active group auto messages"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    messages_list = await db.get_user_group_messages(user_id)

    if not messages_list:
        try:
            await update.callback_query.edit_message_text(
                "📋 **My Group Messages**\n\nNo active group messages.",
                reply_markup=menu_ui.group_messages_menu()
            )
        except BadRequest:
            pass
        return

    text = "📋 **Active Group Messages**\n\n"
    keyboard_rows = []

    for msg in messages_list:
        text += (
            f"🆔 #{msg['id']} | {msg['group_name']}\n"
            f"⏱ Every {msg['interval_minutes']} min\n"
            f"📝 {msg['message'][:50]}{'...' if len(msg['message']) > 50 else ''}\n\n"
        )
        keyboard_rows.append([
            InlineKeyboardButton(
                f"🗑 Delete #{msg['id']}",
                callback_data=f"del_group_msg_{msg['id']}"
            )
        ])

    keyboard_rows.append([InlineKeyboardButton("« Back", callback_data="group_messages")])

    try:
        await update.callback_query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard_rows)
        )
    except BadRequest:
        pass

async def delete_group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a group auto message"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    msg_id = int(update.callback_query.data.replace("del_group_msg_", ""))
    await db.delete_group_auto_message(msg_id, user_id)

    try:
        await update.callback_query.edit_message_text(
            f"✅ Group message #{msg_id} deleted.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="view_group_messages")
            ]])
        )
    except BadRequest:
        pass

# ============ SCRAPER ============

async def scraper_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if not await check_access(update.effective_user.id):
        return
    try:
        await update.callback_query.edit_message_text(
            "🔍 **Scraper**\n\nExtract data:",
            reply_markup=menu_ui.scraper_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def scrape_members_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "👥 **Scrape Members**\n\nType: `<group> [limit]`\n\nExample:\n`@mygroup 500`",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    except BadRequest:
        pass
    context.user_data['awaiting_scrape'] = True

async def process_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_scrape'):
        return

    user_id = update.effective_user.id
    text = update.message.text.strip().split()
    group = text[0]
    limit = int(text[1]) if len(text) > 1 else 1000
    context.user_data['awaiting_scrape'] = False

    await update.message.reply_text("🔍 Scraping...")
    result = await scraper.scrape_group_members(user_id, group, limit)

    if result['success']:
        import csv, io
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=['id', 'username', 'first_name', 'last_name', 'phone'])
        writer.writeheader()
        writer.writerows(result['members'])
        output.seek(0)
        await update.message.reply_document(
            document=output.getvalue().encode(),
            filename=f"{group}_members.csv",
            caption=f"✅ Scraped {result['total']} members",
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )
    else:
        await update.message.reply_text(f"❌ Error: {result['error']}")

# ============ MULTI-ACCOUNT ============

async def multi_account_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            "👥 **Multi-Account**\n\nManage accounts:",
            reply_markup=menu_ui.multi_account_menu(),
            parse_mode='Markdown'
        )
    except BadRequest:
        pass

async def view_accounts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.effective_user.id
    accounts = await db.get_all_accounts(user_id)

    if not accounts:
        try:
            await update.callback_query.edit_message_text(
                "📋 **Your Accounts**\n\nNo accounts.",
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
            text, reply_markup=menu_ui.multi_account_menu(), parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ============ ANALYTICS ============

async def analytics_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            text, reply_markup=menu_ui.back_button(), parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ============ SENT MESSAGES ============

async def sent_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.effective_user.id
    messages = await db.get_sent_messages(user_id, limit=10)

    if not messages:
        try:
            await update.callback_query.edit_message_text(
                "📨 **Sent Messages**\n\nNo messages yet.",
                reply_markup=menu_ui.back_button()
            )
        except BadRequest:
            pass
        return

    text = "📨 **Recent Messages**\n\n"
    for msg in messages:
        text += f"To: {msg['target']}\nText: {msg['message'][:40]}...\n\n"

    try:
        await update.callback_query.edit_message_text(
            text, reply_markup=menu_ui.back_button(), parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ============ STATUS ============

async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            text, reply_markup=menu_ui.back_button(), parse_mode='Markdown'
        )
    except BadRequest:
        pass

# ============ LOGOUT ============

async def logout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        try:
            await update.callback_query.edit_message_text("❌ No account.")
        except BadRequest:
            pass

# ============ TEXT MESSAGE ROUTER ============

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all free-text messages to appropriate handlers"""
    user_id = update.effective_user.id

    # Broadcast (admin only)
    if context.user_data.get('awaiting_broadcast') and is_admin(user_id):
        await process_broadcast(update, context)
        return

    # Access gate for non-admin text interactions
    if not await check_access(user_id) and not is_admin(user_id):
        await update.message.reply_text("⏳ Your access is pending admin approval.")
        return

    if context.user_data.get('awaiting_auto_reply'):
        await process_auto_reply(update, context)
    elif context.user_data.get('awaiting_escrow_group'):
        await process_escrow_group(update, context)
    elif context.user_data.get('awaiting_schedule'):
        await process_schedule(update, context)
    elif context.user_data.get('awaiting_send_message'):
        await process_send_message(update, context)
    elif context.user_data.get('awaiting_scrape'):
        await process_scrape(update, context)
    elif context.user_data.get('awaiting_group_message'):
        await process_group_message(update, context)
    else:
        await update.message.reply_text(
            "👋 Use /start for menu!",
            reply_markup=menu_ui.main_menu(is_admin=is_admin(user_id))
        )

# ============ POST INIT ============

async def post_init(application: Application):
    await db.init_db()
    scheduler_manager.start_scheduler_job()
    await auto_start_users()
    asyncio.create_task(group_message_manager.start_group_message_job())
    print("✅ Bot initialized!")
    print("⏰ Scheduler running")
    print("📢 Group message job started")
    print("📡 Auto-start complete")

# ============ MAIN ============

def main():
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    application.add_error_handler(error_handler)

    # Login conversation
    login_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(login_handler.start_login, pattern='^add_account$')],
        states={
            API_ID:    [MessageHandler(filters.TEXT & ~filters.COMMAND, login_handler.receive_api_id)],
            API_HASH:  [MessageHandler(filters.TEXT & ~filters.COMMAND, login_handler.receive_api_hash)],
            PHONE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, login_handler.receive_phone)],
            OTP:       [MessageHandler(filters.TEXT & ~filters.COMMAND, login_handler.receive_otp)],
            PASSWORD:  [MessageHandler(filters.TEXT & ~filters.COMMAND, login_handler.receive_password)],
        },
        fallbacks=[CommandHandler('cancel', login_handler.cancel_login)]
    )

    application.add_handler(CommandHandler('start', start))
    application.add_handler(login_conv)

    # Main navigation
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

    # Group auto messages
    application.add_handler(CallbackQueryHandler(group_messages_handler, pattern='^group_messages$'))
    application.add_handler(CallbackQueryHandler(add_group_message_handler, pattern='^add_group_message$'))
    application.add_handler(CallbackQueryHandler(view_group_messages_handler, pattern='^view_group_messages$'))
    application.add_handler(CallbackQueryHandler(delete_group_message_handler, pattern='^del_group_msg_'))

    # Admin panel
    application.add_handler(CallbackQueryHandler(admin_panel_handler, pattern='^admin_panel$'))
    application.add_handler(CallbackQueryHandler(admin_users_handler, pattern='^admin_users$'))
    application.add_handler(CallbackQueryHandler(admin_requests_handler, pattern='^admin_requests$'))
    application.add_handler(CallbackQueryHandler(admin_broadcast_all_handler, pattern='^admin_broadcast_all$'))
    application.add_handler(CallbackQueryHandler(admin_broadcast_approved_handler, pattern='^admin_broadcast_approved$'))
    application.add_handler(CallbackQueryHandler(admin_broadcast_unapproved_handler, pattern='^admin_broadcast_unapproved$'))
    application.add_handler(CallbackQueryHandler(admin_approve_handler, pattern='^admin_approve_'))
    application.add_handler(CallbackQueryHandler(admin_reject_handler, pattern='^admin_reject_'))

    # Text handler (must be last)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_text_messages
    ))

    print("🚀 Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
