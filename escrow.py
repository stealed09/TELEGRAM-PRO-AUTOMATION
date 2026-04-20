import re
import asyncio
import unicodedata
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from database import db
from client_manager import client_manager
from config import BOT_TOKEN
from telethon import events
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.types import ChannelParticipantAdmin, ChannelParticipantCreator


# ============ HELPERS ============

def _to_ascii(text: str) -> str:
    """Convert Unicode bold/italic math chars to plain ASCII lowercase."""
    result = []
    for ch in text:
        n = unicodedata.normalize('NFKD', ch)
        a = n.encode('ascii', 'ignore').decode('ascii')
        result.append(a if a else ' ')
    return ''.join(result).lower()


def is_boss_escrow_form(text: str) -> bool:
    """Detect Boss Escrow form — works on Unicode bold text."""
    ascii_text = _to_ascii(text)
    return 'boss escrow' in ascii_text or (
        'escrow' in ascii_text and 'deal description' in ascii_text
    )


def parse_escrow_form(text: str):
    """
    Parse Boss Escrow Deal form line-by-line.
    Returns dict if ALL fields are filled, None if any field is blank.
    """
    if not is_boss_escrow_form(text):
        return None

    data = {}
    for line in text.splitlines():
        if ':' not in line:
            continue
        colon_idx = line.index(':')
        label = _to_ascii(line[:colon_idx])
        raw_value = line[colon_idx + 1:].strip()

        if 'deal' in label and 'description' in label:
            data['deal_description'] = raw_value
        elif 'name' in label and 'pay' in label:
            data['paying_name'] = raw_value
        elif 'total' in label and 'amount' in label:
            data['amount_raw'] = raw_value
            numeric = re.sub(r'[^\d.]', '', raw_value)
            data['amount'] = float(numeric) if numeric else None
        elif 'time' in label and 'finish' in label:
            data['time_to_finish'] = raw_value
        elif 'refund' in label and 'condition' in label:
            data['refund_condition'] = raw_value
        elif 'release' in label and 'condition' in label:
            data['release_condition'] = raw_value
        elif 'seller' in label and 'buyer' not in label:
            data['seller'] = raw_value
        elif 'buyer' in label and 'seller' not in label:
            data['buyer'] = raw_value

    required = {
        'deal_description': 'Deal Description',
        'paying_name':      'Name of paying',
        'time_to_finish':   'Time To Finish',
        'refund_condition': 'Refund Condition',
        'release_condition':'Release Condition',
        'seller':           'Seller',
        'buyer':            'Buyer',
    }
    missing = [friendly for key, friendly in required.items()
               if not data.get(key, '').strip()]
    if not data.get('amount'):
        missing.append('Total Deal Amount')

    if missing:
        print(f"[Escrow] Blank fields — NOT replying: {missing}")
        return None

    # Rule 3: Do NOT reply if Total Deal Amount > 6000
    if data.get('amount') and data['amount'] > 6000:
        print(f"[Escrow] Amount {data['amount']} > 6000 — NOT replying")
        return None

    # Rule 4: Do NOT reply if Release Condition = NO
    if data.get('release_condition', '').strip().upper() == 'NO':
        print(f"[Escrow] Release condition is NO — NOT replying")
        return None

    # Rule 5: Do NOT reply if Refund Condition = NO
    if data.get('refund_condition', '').strip().upper() == 'NO':
        print(f"[Escrow] Refund condition is NO — NOT replying")
        return None

    print(f"[Escrow] Form parsed OK")
    return data


def seconds_to_next_minute(t: datetime) -> float:
    """
    09:56:23 -> sleep 37s -> reply at 09:57:00
    07:45:23 -> sleep 37s -> reply at 07:46:00
    """
    next_min = t.replace(second=0, microsecond=0) + timedelta(minutes=1)
    delta = (next_min - t).total_seconds()
    return delta if delta > 0 else 60.0


async def is_admin_in_chat(client, chat_id) -> bool:
    """
    Check if the logged-in Telethon account is admin/creator in the group.
    Works for both public and private groups/channels.
    """
    try:
        me = await client.get_me()
        participant = await client(GetParticipantRequest(
            channel=chat_id,
            participant=me.id
        ))
        p = participant.participant
        return isinstance(p, (ChannelParticipantAdmin, ChannelParticipantCreator))
    except Exception as e:
        print(f"[Escrow] Admin check error: {e}")
        return False


async def resolve_group(client, identifier: str):
    """
    Resolve a group by:
    - @username
    - invite link (t.me/joinchat/... or t.me/+...)
    - numeric ID (with or without -100 prefix)
    Returns the entity or None.
    """
    identifier = identifier.strip()
    try:
        # Try direct resolve (works for public @username and numeric IDs)
        if identifier.lstrip('-').isdigit():
            # Numeric ID — add -100 prefix for supergroups if missing
            num = int(identifier)
            if num > 0:
                num = int(f"-100{num}")
            return await client.get_entity(num)
        else:
            return await client.get_entity(identifier)
    except Exception:
        pass

    # Try as invite link
    try:
        if 't.me/' in identifier or 'telegram.me/' in identifier:
            result = await client(
                __import__('telethon.tl.functions.messages', fromlist=['ImportChatInviteRequest'])
                .ImportChatInviteRequest(identifier.split('/')[-1].lstrip('+'))
            )
            return result.chats[0] if result.chats else None
    except Exception as e:
        # Already a member — just get the entity
        try:
            return await client.get_entity(identifier)
        except Exception:
            pass

    return None


# ============ MANAGER CLASS ============

class EscrowManager:
    def __init__(self):
        self.pending_forms = {}
        self.active_deals = {}
        self.monitoring_active = {}

    async def setup_group_monitoring(self, user_id, account_id):
        """
        Setup Telethon NewMessage listener.
        Works for both PUBLIC and PRIVATE groups (via ID or invite link).
        Only replies if the logged-in account IS an admin in that group.
        """
        try:
            client = await client_manager.get_client(user_id, account_id)
            if not client:
                print(f"[Escrow] No client for user {user_id}")
                return False

            escrow_groups = await db.get_escrow_groups(user_id)
            if not escrow_groups:
                print(f"[Escrow] No escrow groups for user {user_id}")
                return False

            print(f"[Escrow] Monitoring {len(escrow_groups)} group(s) for user {user_id}")

            @client.on(events.NewMessage())
            async def escrow_form_detector(event):
                try:
                    if not (event.is_group or event.is_channel):
                        return
                    if not self.monitoring_active.get(user_id, True):
                        return
                    if not event.text:
                        return

                    # Rule 1: skip if message is already deleted/unavailable
                    if getattr(event.message, 'media', None) is None and not event.text:
                        return

                    chat_id = str(event.chat_id)
                    is_monitored = False
                    for g in escrow_groups:
                        gid = str(g['group_id'])
                        a = chat_id.lstrip('-').lstrip('100')
                        b = gid.lstrip('-').lstrip('100')
                        if (chat_id == gid or
                                a == b or
                                chat_id == gid.replace('-100', '') or
                                f"-100{chat_id}" == gid or
                                chat_id.replace('-100', '') == gid.replace('-100', '')):
                            is_monitored = True
                            break

                    if not is_monitored:
                        return

                    if not is_boss_escrow_form(event.text):
                        return

                    admin_ok = await is_admin_in_chat(client, event.chat_id)
                    if not admin_ok:
                        print(f"[Escrow] Logged-in ID is NOT admin in {event.chat_id} — skipping")
                        return

                    received_at = datetime.now()
                    msg_id = event.message.id
                    print(f"[Escrow] Form detected at {received_at.strftime('%H:%M:%S')}")

                    deal_data = parse_escrow_form(event.text)
                    if deal_data:
                        asyncio.create_task(
                            self.process_detected_form(
                                user_id, account_id,
                                event.chat_id, deal_data,
                                msg_id, received_at
                            )
                        )
                    else:
                        print("[Escrow] Form did not pass validation — NOT replying")

                except Exception as e:
                    print(f"[Escrow] Detector error: {e}")

            # Rule 1: if the form message is deleted before reply time, cancel reply
            @client.on(events.MessageDeleted())
            async def escrow_delete_detector(event):
                try:
                    deleted_ids = event.deleted_ids
                    # Remove any pending forms that match deleted message IDs
                    to_cancel = [k for k, v in self.pending_forms.items()
                                 if v.get('msg_id') in deleted_ids]
                    for k in to_cancel:
                        task = self.pending_forms[k].get('task')
                        if task and not task.done():
                            task.cancel()
                            print(f"[Escrow] Form message deleted — reply cancelled for msg {k}")
                        del self.pending_forms[k]
                except Exception as e:
                    print(f"[Escrow] Delete detector error: {e}")

            self.monitoring_active[user_id] = True
            print(f"[Escrow] Monitoring ACTIVE for user {user_id}")
            return True

        except Exception as e:
            print(f"[Escrow] setup_group_monitoring error: {e}")
            return False

    async def process_detected_form(self, user_id, account_id, chat_id,
                                    deal_data, original_msg_id, received_at: datetime):
        """
        Wait until next minute boundary, then reply BOTH AGREE.
        Rule 1: if form deleted before reply time, cancel silently.
        """
        try:
            deal_id = await db.create_escrow_deal(user_id, account_id, chat_id, deal_data)

            # Compute exact target time ONCE
            reply_at = received_at.replace(second=0, microsecond=0) + timedelta(minutes=1)
            delay = (reply_at - datetime.now()).total_seconds()
            print(f"[Escrow] Will reply at {reply_at.strftime('%H:%M:%S')} (sleep {delay:.2f}s)")

            # Register task so MessageDeleted event can cancel it
            self.pending_forms[original_msg_id] = asyncio.current_task()

            # Sleep most of the wait, then spin the last 50ms for precision
            await asyncio.sleep(max(0, delay - 0.05))
            while datetime.now() < reply_at:
                await asyncio.sleep(0.001)

            # Clean up pending registry
            self.pending_forms.pop(original_msg_id, None)

            client = await client_manager.get_client(user_id, account_id)
            if not client:
                print(f"[Escrow] Client gone before reply")
                return

            # Rule 1: verify message still exists before replying
            try:
                check = await client.get_messages(chat_id, ids=original_msg_id)
                if not check or not getattr(check, 'text', None):
                    print(f"[Escrow] Message deleted — NOT replying")
                    return
            except Exception:
                print(f"[Escrow] Message inaccessible — NOT replying")
                return

            reply_text = "🤝 𝐁𝐎𝐓𝐇 𝐀𝐆𝐑𝐄𝐄 ✅"
            await client.send_message(chat_id, reply_text, reply_to=original_msg_id)
            print(f"[Escrow] Replied BOTH AGREE at {datetime.now().strftime('%H:%M:%S')}")

            # Notify the bot owner
            try:
                bot = Bot(token=BOT_TOKEN)
                await bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"🔔 **ESCROW DETECTED**\n\n"
                        f"Deal ID: #{deal_id}\n"
                        f"📝 {deal_data['deal_description']}\n"
                        f"👤 Paying: {deal_data['paying_name']}\n"
                        f"💰 Amount: {deal_data.get('amount_raw', deal_data['amount'])}\n"
                        f"⏰ Time: {deal_data['time_to_finish']}\n"
                        f"🔄 Refund: {deal_data['refund_condition']}\n"
                        f"✅ Release: {deal_data['release_condition']}\n"
                        f"👥 Seller: {deal_data['seller']}\n"
                        f"🛒 Buyer: {deal_data['buyer']}\n\n"
                        f"✅ Replied at {reply_at.strftime('%H:%M:%S')}"
                    ),
                    parse_mode='Markdown'
                )
            except Exception as e:
                print(f"[Escrow] Notify error: {e}")

            self.active_deals[deal_id] = {
                'message_id': original_msg_id,
                'chat_id': chat_id,
                'user_id': user_id,
                'account_id': account_id,
                'deal_data': deal_data
            }
            await db.log_action(user_id, 'escrow_detected', {'deal_id': deal_id})

        except Exception as e:
            print(f"[Escrow] process_detected_form error: {e}")

    async def toggle_monitoring(self, user_id, enable=True):
        self.monitoring_active[user_id] = enable
        await db.set_user_setting(user_id, 'escrow_monitoring', enable)
        return "started" if enable else "stopped"

    # ============ BOT UI HANDLERS ============

    async def add_escrow_group_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from menu import menu_ui
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                "➕ **Add Escrow Group**\n\n"
                "Send the group **@username**, **invite link**, or **numeric ID**:\n\n"
                "Examples:\n"
                "`@mygroup`\n"
                "`https://t.me/+AbCdEfGhIjK`\n"
                "`-1001234567890`\n\n"
                "Works for both public and private groups.\n"
                "⚠️ Your logged-in account must be an **admin** in the group.",
                parse_mode='Markdown',
                reply_markup=menu_ui.back_button()
            )
        except BadRequest:
            pass
        context.user_data['awaiting_escrow_group'] = True

    async def view_escrow_groups_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from menu import menu_ui
        await update.callback_query.answer()
        user_id = update.effective_user.id
        groups = await db.get_escrow_groups(user_id)

        if not groups:
            try:
                await update.callback_query.edit_message_text(
                    "📋 **Escrow Groups**\n\nNo groups added.",
                    parse_mode='Markdown',
                    reply_markup=menu_ui.escrow_menu()
                )
            except BadRequest:
                pass
            return

        text = "📋 **Monitored Groups**\n\n"
        for g in groups:
            text += f"{'🟢' if g['is_active'] else '🔴'} {g['group_name']}\n"
        monitoring = self.monitoring_active.get(user_id, True)
        text += f"\n📡 Status: {'✅ ON' if monitoring else '⏸️ OFF'}"

        keyboard = [
            [InlineKeyboardButton(
                "⏸️ Stop" if monitoring else "▶️ Start",
                callback_data="toggle_escrow_monitoring"
            )],
            [InlineKeyboardButton("« Back", callback_data="escrow")]
        ]
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except BadRequest:
            pass

    async def toggle_monitoring_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.answer()
        user_id = update.effective_user.id
        new_status = not self.monitoring_active.get(user_id, True)
        await self.toggle_monitoring(user_id, new_status)
        try:
            await update.callback_query.edit_message_text(
                f"{'✅ Monitoring ON' if new_status else '⏸️ Monitoring OFF'}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Back", callback_data="view_escrow_groups")
                ]])
            )
        except BadRequest:
            pass


escrow_manager = EscrowManager()
        
