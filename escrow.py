import re
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
        self.monitoring_active = {}  # {user_id: bool}
    
    def parse_escrow_form(self, text):
        """Parse escrow form - handles special characters and any format"""
        try:
            data = {}
            
            # Normalize text
            normalized_text = text.replace('●', '•').replace('○', '•')
            
            # Deal type - REQUIRED
            patterns = [
                r'[•●]\s*ᴅᴇᴀʟ\s+ᴏꜰ\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
                r'DEAL\s+OF\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
            ]
            for pattern in patterns:
                match = re.search(pattern, normalized_text, re.IGNORECASE | re.MULTILINE)
                if match:
                    data['deal_type'] = match.group(1).strip()
                    break
            
            if 'deal_type' not in data:
                return None
            
            # Amount - REQUIRED
            patterns = [
                r'[•●]\s*ᴛᴏᴛᴀʟ\s+ᴀᴍᴏᴜɴᴛ\s*[:\-]+\s*(\d+(?:\.\d+)?)',
                r'TOTAL\s+AMOUNT\s*[:\-]+\s*(\d+(?:\.\d+)?)',
            ]
            for pattern in patterns:
                match = re.search(pattern, normalized_text, re.IGNORECASE)
                if match:
                    data['amount'] = float(match.group(1))
                    break
            
            if 'amount' not in data:
                return None
            
            # Maximum time - REQUIRED
            patterns = [
                r'[•●]\s*ᴍᴀxɪᴍᴜᴍ\s+ᴛɪᴍᴇ\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
                r'MAXIMUM\s+TIME\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
            ]
            for pattern in patterns:
                match = re.search(pattern, normalized_text, re.IGNORECASE | re.MULTILINE)
                if match:
                    data['max_time'] = match.group(1).strip()
                    break
            
            if 'max_time' not in data:
                return None
            
            # Terms - REQUIRED
            patterns = [
                r'[•●]\s*ᴛᴇʀᴍꜱ\s*&\s*ᴄᴏɴᴅɪᴛɪᴏɴ\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
                r'TERMS\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
            ]
            for pattern in patterns:
                match = re.search(pattern, normalized_text, re.IGNORECASE | re.MULTILINE)
                if match:
                    data['terms'] = match.group(1).strip()
                    break
            
            if 'terms' not in data:
                return None
            
            # Seller - REQUIRED
            patterns = [
                r'[•●]\s*[𝑺𝒔Ss]𝒆𝒍𝒍𝒆𝒓\s*[:\-\s]+(\+?\d+)',
                r'Seller\s*[:\-\s]+(\+?\d+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    data['seller_id'] = match.group(1).strip()
                    break
            
            if 'seller_id' not in data:
                return None
            
            # Buyer - REQUIRED
            patterns = [
                r'[•●]\s*[𝑩𝒃Bb]𝒖𝒚𝒆𝒓\s*[:\-\s]+(\+?\d+)',
                r'Buyer\s*[:\-\s]+(\+?\d+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    data['buyer_id'] = match.group(1).strip()
                    break
            
            if 'buyer_id' not in data:
                return None
            
            # Buyer bank - OPTIONAL
            patterns = [
                r'[•●]\s*Buyer\s+Bank\s+Name\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
            ]
            for pattern in patterns:
                match = re.search(pattern, normalized_text, re.IGNORECASE | re.MULTILINE)
                if match:
                    data['buyer_bank'] = match.group(1).strip()
                    break
            
            if 'buyer_bank' not in data:
                data['buyer_bank'] = 'N/A'
            
            # Validate all required fields
            required = ['deal_type', 'amount', 'max_time', 'terms', 'seller_id', 'buyer_id']
            if all(key in data and data[key] for key in required):
                print(f"✅ Escrow form parsed: Deal={data['deal_type']}, Amount={data['amount']}")
                return data
            else:
                return None
                
        except Exception as e:
            print(f"❌ Error parsing escrow form: {e}")
            return None
    
    async def setup_group_monitoring(self, user_id, account_id):
        """Setup Telethon event handler for escrow form detection IN GROUPS ONLY"""
        try:
            client = await client_manager.get_client(user_id, account_id)
            if not client:
                return False
            
            escrow_groups = await db.get_escrow_groups(user_id)
            
            if not escrow_groups:
                print(f"ℹ️ No escrow groups configured for user {user_id}")
                return False
            
            print(f"📡 Setting up escrow monitoring for user {user_id}")
            
            @client.on(events.NewMessage())
            async def escrow_form_detector(event):
                try:
                    # ONLY PROCESS GROUP MESSAGES FOR ESCROW
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
                    
                    deal_data = self.parse_escrow_form(event.text)
                    
                    if deal_data:
                        print(f"🎯 ESCROW FORM DETECTED in group")
                        await self.process_detected_form(
                            user_id, account_id, event.chat_id, deal_data, event.message.id
                        )
                
                except Exception as e:
                    print(f"❌ Error in form detector: {e}")
            
            self.monitoring_active[user_id] = True
            print(f"✅ Escrow monitoring ACTIVE for user {user_id}")
            return True
            
        except Exception as e:
            print(f"❌ Error setting up monitoring: {e}")
            return False
    
    async def process_detected_form(self, user_id, account_id, chat_id, deal_data, original_msg_id):
        """Process detected escrow form - Reply BOTH AGREE and TAG original message"""
        try:
            # Create escrow deal in database
            deal_id = await db.create_escrow_deal(
                user_id, account_id, chat_id, deal_data
            )
            
            print(f"✅ Escrow deal #{deal_id} created")
            
            # Get client to reply
            client = await client_manager.get_client(user_id, account_id)
            
            if client:
                # Reply to the original message with simple text and TAG
                simple_reply = "🤝 𝐁𝐎𝐓𝐇 𝐀𝐆𝐑𝐄𝐄 ✅"
                
                # Send message as reply to original (this tags/quotes the original message)
                await client.send_message(
                    chat_id,
                    simple_reply,
                    reply_to=original_msg_id
                )
                
                print(f"✅ Replied 'BOTH AGREE' and tagged message {original_msg_id}")
                
                # Send notification to bot user with deal details
                bot = Bot(token=BOT_TOKEN)
                
                notification_msg = (
                    f"🔔 **ESCROW FORM DETECTED & REPLIED**\n\n"
                    f"Deal ID: #{deal_id}\n"
                    f"💰 Amount: {deal_data['amount']}\n"
                    f"⏰ Time: {deal_data['max_time']}\n"
                    f"📝 Type: {deal_data['deal_type']}\n\n"
                    f"👥 **Parties:**\n"
                    f"• Seller: {deal_data['seller_id']}\n"
                    f"• Buyer: {deal_data['buyer_id']}\n\n"
                    f"📋 Terms: {deal_data['terms']}\n"
                    f"🏦 Bank: {deal_data['buyer_bank']}\n\n"
                    f"✅ Replied: 'BOTH AGREE' with tagged message"
                )
                
                await bot.send_message(
                    chat_id=user_id,
                    text=notification_msg,
                    parse_mode='Markdown'
                )
                
                print(f"✅ Notification sent to user {user_id}")
                
                # Store active deal info
                self.active_deals[deal_id] = {
                    'message_id': original_msg_id,
                    'chat_id': chat_id,
                    'user_id': user_id,
                    'account_id': account_id,
                    'deal_data': deal_data
                }
                
                await db.log_action(user_id, 'escrow_auto_detected', {'deal_id': deal_id})
        
        except Exception as e:
            print(f"❌ Error processing form: {e}")
            import traceback
            traceback.print_exc()
    
    async def toggle_monitoring(self, user_id, enable=True):
        """Toggle escrow monitoring"""
        self.monitoring_active[user_id] = enable
        status = "started" if enable else "stopped"
        await db.set_user_setting(user_id, 'escrow_monitoring', enable)
        return status
    
    async def add_escrow_group_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add group for monitoring"""
        from menu import menu_ui
        
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                "➕ **Add Escrow Group**\n\n"
                "Send command:\n"
                "`<group_username_or_id>`\n\n"
                "Example:\n"
                "`@mygroup`",
                parse_mode='Markdown',
                reply_markup=menu_ui.back_button()
            )
        except BadRequest:
            pass
        
        context.user_data['awaiting_escrow_group'] = True
    
    async def view_escrow_groups_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View monitored groups"""
        from menu import menu_ui
        
        await update.callback_query.answer()
        user_id = update.effective_user.id
        
        groups = await db.get_escrow_groups(user_id)
        
        if not groups:
            try:
                await update.callback_query.edit_message_text(
                    "📋 **Escrow Groups**\n\n"
                    "No groups added.\n\n"
                    "Click 'Add Group' to start.",
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
        
        monitoring_status = self.monitoring_active.get(user_id, True)
        text += f"\n📡 Status: {'✅ ON' if monitoring_status else '⏸️ OFF'}"
        
        keyboard = [
            [
                InlineKeyboardButton(
                    "⏸️ Stop" if monitoring_status else "▶️ Start",
                    callback_data="toggle_escrow_monitoring"
                )
            ],
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
        
        text = f"{'✅ Monitoring ON' if new_status else '⏸️ Monitoring OFF'}"
        
        try:
            await update.callback_query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Back", callback_data="view_escrow_groups")
                ]])
            )
        except BadRequest:
            pass

escrow_manager = EscrowManager()
