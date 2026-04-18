import re
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from database import db
from client_manager import client_manager
from messaging import message_sender
from config import ADMIN_IDS, BOT_TOKEN
from telethon import events


class EscrowManager:
    def __init__(self):
        self.pending_forms = {}
        self.active_deals = {}
        self.monitoring_active = {}

    def _normalize_label(self, raw: str) -> str:
        """
        Convert any Unicode bold/italic math letters to plain ASCII,
        then lowercase and strip spaces so we can keyword-match reliably.

        Unicode math italic block: U+1D400–U+1D7FF
        We map each character back to its ASCII base via unicodedata.
        """
        import unicodedata
        result = []
        for ch in raw:
            # Decompose then keep only ASCII letters/digits/spaces
            normalized = unicodedata.normalize('NFKD', ch)
            ascii_chars = normalized.encode('ascii', 'ignore').decode('ascii')
            result.append(ascii_chars if ascii_chars else ch)
        return ''.join(result).lower().strip()

    def parse_escrow_form(self, text):
        """
        Line-based parser for the Boss Escrow Deal form.
        Strategy:
          1. Split text into lines.
          2. For lines containing ' : ', strip the bullet/unicode label,
             normalise it to plain ASCII lowercase, then keyword-match.
          3. The value is everything after the first ' : ' on that line.
        Returns dict or None if any required field is blank/missing.
        """
        try:
            # Quick check — must look like a Boss Escrow form
            if 'Escrow' not in text and 'escrow' not in text.lower():
                return None

            data = {}

            for line in text.splitlines():
                # Only process lines that contain a colon separator
                if ':' not in line:
                    continue

                # Split on FIRST colon only
                colon_idx = line.index(':')
                raw_label = line[:colon_idx]
                raw_value = line[colon_idx + 1:].strip()

                # Skip empty values — we will validate later
                label = self._normalize_label(raw_label)

                # Match keywords in the normalised label
                if 'deal' in label and 'description' in label:
                    data['deal_description'] = raw_value

                elif 'name' in label and 'pay' in label:
                    data['paying_name'] = raw_value

                elif 'total' in label and 'amount' in label:
                    data['amount_raw'] = raw_value
                    try:
                        numeric = re.sub(r'[^\d.]', '', raw_value)
                        data['amount'] = float(numeric) if numeric else 0.0
                    except Exception:
                        data['amount'] = 0.0

                elif 'time' in label and 'finish' in label:
                    data['time_to_finish'] = raw_value

                elif 'refund' in label and 'condition' in label:
                    data['refund_condition'] = raw_value

                elif 'release' in label and 'condition' in label:
                    data['release_condition'] = raw_value

                elif 'seller' in label and 'buyer' not in label:
                    # Avoid matching "buyer" line on the seller check
                    data['seller'] = raw_value

                elif 'buyer' in label and 'seller' not in label:
                    data['buyer'] = raw_value

            # ---- Validate: ALL fields must be non-empty ----
            required = {
                'deal_description': 'Deal Description',
                'paying_name':      'Name of paying',
                'time_to_finish':   'Time To Finish',
                'refund_condition': 'Refund Condition',
                'release_condition':'Release Condition',
                'seller':           'Seller',
                'buyer':            'Buyer',
            }

            missing = []
            for key, friendly in required.items():
                val = data.get(key, '')
                if not val or str(val).strip() == '':
                    missing.append(friendly)

            if data.get('amount') is None:
                missing.append('Total Deal Amount')

            if missing:
                print(f"⚠️ Escrow form has blank/missing fields: {missing}")
                return None

            print(f"✅ Boss Escrow form parsed OK: {data}")
            return data

        except Exception as e:
            print(f"❌ Error parsing escrow form: {e}")
            return None

    def _seconds_until_next_minute(self, sent_time: datetime) -> float:
        """
        Calculate seconds from sent_time until the START of the NEXT minute.
        Example: sent at 09:40:30 -> next minute boundary = 09:41:00 -> wait 30s
        """
        next_minute = sent_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
        delta = (next_minute - sent_time).total_seconds()
        # Guard: if already exactly at minute boundary, wait full 60s
        if delta <= 0:
            delta = 60.0
        return delta

    async def setup_group_monitoring(self, user_id, account_id):
        """Setup escrow monitoring for configured groups"""
        try:
            client = await client_manager.get_client(user_id, account_id)
            if not client:
                return False

            escrow_groups = await db.get_escrow_groups(user_id)

            if not escrow_groups:
                print(f"ℹ️ No escrow groups for user {user_id}")
                return False

            print(f"📡 Setting up escrow monitoring for user {user_id}")

            @client.on(events.NewMessage())
            async def escrow_form_detector(event):
                try:
                    # GROUPS ONLY
                    if not (event.is_group or event.is_channel):
                        return

                    if not self.monitoring_active.get(user_id, True):
                        return

                    chat_id = str(event.chat_id)

                    is_monitored = any(
                        chat_id == str(g['group_id']) or
                        chat_id == str(g['group_id']).replace('-100', '') or
                        f"-100{chat_id}" == str(g['group_id']) or
                        chat_id.replace('-100', '') == str(g['group_id']).replace('-100', '')
                        for g in escrow_groups
                    )

                    if not is_monitored or not event.text:
                        return

                    # Check if this looks like a Boss Escrow form
                    if '𝐁𝐨𝐬𝐬 𝐄𝐬𝐜𝐫𝐨𝐰' not in event.text and 'Escrow' not in event.text:
                        return

                    # Record exact time message was received
                    received_at = datetime.now()

                    deal_data = self.parse_escrow_form(event.text)

                    if deal_data:
                        print(f"🎯 BOSS ESCROW FORM DETECTED at {received_at.strftime('%H:%M:%S')}")
                        # Schedule timed reply (at next minute boundary)
                        asyncio.create_task(
                            self.process_detected_form(
                                user_id, account_id, event.chat_id,
                                deal_data, event.message.id, received_at
                            )
                        )
                    else:
                        print(f"⚠️ Escrow form detected but has blank/missing fields — skipping reply")

                except Exception as e:
                    print(f"❌ Escrow detector error: {e}")

            self.monitoring_active[user_id] = True
            print(f"✅ Escrow monitoring ACTIVE for user {user_id}")
            return True

        except Exception as e:
            print(f"❌ Setup escrow monitoring error: {e}")
            return False

    async def process_detected_form(self, user_id, account_id, chat_id,
                                     deal_data, original_msg_id, received_at: datetime):
        """
        Process a detected escrow form.
        Wait until the START of the next minute after received_at, then reply BOTH AGREE.
        e.g. received at 09:40:30 → reply at 09:41:00 (wait ~30s)
             received at 10:34:23 → reply at 10:35:00 (wait ~37s)
        """
        try:
            # Save deal to DB
            deal_id = await db.create_escrow_deal(user_id, account_id, chat_id, deal_data)
            print(f"✅ Deal #{deal_id} created")

            # Calculate delay
            delay_seconds = self._seconds_until_next_minute(received_at)
            reply_at = received_at.replace(second=0, microsecond=0) + timedelta(minutes=1)

            print(
                f"⏳ Will reply BOTH AGREE at {reply_at.strftime('%H:%M:%S')} "
                f"(in {delay_seconds:.1f}s)"
            )

            # Wait until next minute boundary
            await asyncio.sleep(delay_seconds)

            client = await client_manager.get_client(user_id, account_id)

            if client:
                # Get sender's username/mention to tag them in the reply
                try:
                    msg = await client.get_messages(chat_id, ids=original_msg_id)
                    sender = await msg.get_sender()
                    if sender and sender.username:
                        mention = f"@{sender.username}"
                    elif sender:
                        mention = f"[{sender.first_name}](tg://user?id={sender.id})"
                    else:
                        mention = ""
                except Exception:
                    mention = ""

                # Build BOTH AGREE reply with mention
                if mention:
                    reply_text = f"🤝 𝐁𝐎𝐓𝐇 𝐀𝐆𝐑𝐄𝐄 ✅\n{mention}"
                else:
                    reply_text = "🤝 𝐁𝐎𝐓𝐇 𝐀𝐆𝐑𝐄𝐄 ✅"

                await client.send_message(
                    chat_id,
                    reply_text,
                    reply_to=original_msg_id
                )

                print(f"✅ Replied BOTH AGREE at {datetime.now().strftime('%H:%M:%S')} (targeted {reply_at.strftime('%H:%M:%S')})")

                # Notify bot user
                try:
                    bot = Bot(token=BOT_TOKEN)
                    notification = (
                        f"🔔 **ESCROW DEAL DETECTED**\n\n"
                        f"Deal ID: #{deal_id}\n"
                        f"📝 Description: {deal_data['deal_description']}\n"
                        f"👤 Paying: {deal_data['paying_name']}\n"
                        f"💰 Amount: {deal_data.get('amount_raw', deal_data['amount'])}\n"
                        f"⏰ Time To Finish: {deal_data['time_to_finish']}\n"
                        f"🔄 Refund: {deal_data['refund_condition']}\n"
                        f"✅ Release: {deal_data['release_condition']}\n"
                        f"👥 Seller: {deal_data['seller']}\n"
                        f"🛒 Buyer: {deal_data['buyer']}\n\n"
                        f"✅ Replied BOTH AGREE at {reply_at.strftime('%H:%M:%S')}"
                    )
                    await bot.send_message(
                        chat_id=user_id,
                        text=notification,
                        parse_mode='Markdown'
                    )
                except Exception as notify_err:
                    print(f"⚠️ Could not send notification: {notify_err}")

                self.active_deals[deal_id] = {
                    'message_id': original_msg_id,
                    'chat_id': chat_id,
                    'user_id': user_id,
                    'account_id': account_id,
                    'deal_data': deal_data
                }

                await db.log_action(user_id, 'escrow_detected', {'deal_id': deal_id})

        except Exception as e:
            print(f"❌ Process escrow form error: {e}")

    async def toggle_monitoring(self, user_id, enable=True):
        """Toggle monitoring on/off"""
        self.monitoring_active[user_id] = enable
        await db.set_user_setting(user_id, 'escrow_monitoring', enable)
        return "started" if enable else "stopped"

    # ============ TELEGRAM BOT HANDLERS ============

    async def add_escrow_group_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add escrow group"""
        from menu import menu_ui
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                "➕ **Add Escrow Group**\n\n"
                "Type the group username or ID:\n\n"
                "Example: `@mygroup`",
                parse_mode='Markdown',
                reply_markup=menu_ui.back_button()
            )
        except BadRequest:
            pass
        context.user_data['awaiting_escrow_group'] = True

    async def view_escrow_groups_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View escrow groups"""
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
        for group in groups:
            status = "🟢" if group['is_active'] else "🔴"
            text += f"{status} {group['group_name']}\n"

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
                text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except BadRequest:
            pass

    async def toggle_monitoring_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Toggle monitoring"""
        await update.callback_query.answer()
        user_id = update.effective_user.id
        current = self.monitoring_active.get(user_id, True)
        new_status = not current
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
                    
