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
        self.monitoring_active = {}
    
    def parse_escrow_form(self, text):
        """Parse escrow form"""
        try:
            data = {}
            normalized_text = text.replace('●', '•').replace('○', '•')
            
            # Deal type
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
            
            # Amount
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
            
            # Maximum time
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
            
            # Terms
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
            
            # Seller
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
            
            # Buyer
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
            
            # Buyer bank
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
            
            required = ['deal_type', 'amount', 'max_time', 'terms', 'seller_id', 'buyer_id']
            if all(key in data and data[key] for key in required):
                print(f"✅ Escrow form parsed")
                return data
            else:
                return None
                
        except Exception as e:
            print(f"❌ Error parsing: {e}")
            return None
    
    async def setup_group_monitoring(self, user_id, account_id):
        """Setup escrow monitoring for GROUPS ONLY"""
        try:
            client = await client_manager.get_client(user_id, account_id)
            if not client:
                return False
            
            escrow_groups = await db.get_escrow_groups(user_id)
            
            if not escrow_groups:
                print(f"ℹ️ No escrow groups for user {user_id}")
                return False
            
            print(f"📡 Setting up escrow monitoring")
            
            @client.on(events.NewMessage())
            async def escrow_form_detector(event):
                try:
                    # ONLY GROUPS
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
                        print(f"🎯 ESCROW FORM DETECTED")
                        await self.process_detected_form(
                            user_id, account_id, event.chat_id, deal_data, event.message.id
                        )
                
                except Exception as e:
                    print(f"❌ Error: {e}")
            
            self.monitoring_active[user_id] = True
            print(f"✅ Escrow monitoring ACTIVE")
            return True
            
        except Exception as e:
            print(f"❌ Setup error: {e}")
            return False
    
    async def process_detected_form(self, user_id, account_id, chat_id, deal_data, original_msg_id):
        """Process form - Reply BOTH AGREE and TAG"""
        try:
            deal_id = await db.create_escrow_deal(
                user_id, account_id, chat_id, deal_data
            )
            
            print(f"✅ Deal #{deal_id} created")
            
            client = await client_manager.get_client(user_id, account_id)
            
            if client:
                # Reply with BOTH AGREE and TAG original message
                simple_reply = "🤝 𝐁𝐎𝐓𝐇 𝐀𝐆𝐑𝐄𝐄 ✅"
                
                await client.send_message(
                    chat_id,
                    simple_reply,
                    reply_to=original_msg_id
                )
                
                print(f"✅ Replied and tagged message")
                
                # Send notification to bot user
                bot = Bot(token=BOT_TOKEN)
                
                notification = (
                    f"🔔 **ESCROW DETECTED**\n\n"
                    f"Deal ID: #{deal_id}\n"
                    f"💰 Amount: {deal_data['amount']}\n"
                    f"⏰ Time: {deal_data['max_time']}\n"
                    f"📝 Type: {deal_data['deal_type']}\n\n"
                    f"👥 Parties:\n"
                    f"• Seller: {deal_data['seller_id']}\n"
                    f"• Buyer: {deal_data['buyer_id']}\n\n"
                    f"📋 Terms: {deal_data['terms']}\n"
                    f"🏦 Bank: {deal_data['buyer_bank']}\n\n"
                    f"✅ Replied: BOTH AGREE"
                )
                
                await bot.send_message(
                    chat_id=user_id,
                    text=notification,
                    parse_mode='Markdown'
                )
                
                print(f"✅ Notification sent")
                
                self.active_deals[deal_id] = {
                    'message_id': original_msg_id,
                    'chat_id': chat_id,
                    'user_id': user_id,
                    'account_id': account_id,
                    'deal_data': deal_data
                }
                
                await db.log_action(user_id, 'escrow_detected', {'deal_id': deal_id})
        
        except Exception as e:
            print(f"❌ Process error: {e}")
    
    async def toggle_monitoring(self, user_id, enable=True):
        """Toggle monitoring"""
        self.monitoring_active[user_id] = enable
        await db.set_user_setting(user_id, 'escrow_monitoring', enable)
        return "started" if enable else "stopped"
    
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
        """View groups"""
        from menu import menu_ui
        
        await update.callback_query.answer()
        user_id = update.effective_user.id
        
        groups = await db.get_escrow_groups(user_id)
        
        if not groups:
            try:
                await update.callback_query.edit_message_text(
                    "📋 **Escrow Groups**\n\n"
                    "No groups added.",
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
            [
                InlineKeyboardButton(
                    "⏸️ Stop" if monitoring else "▶️ Start",
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
        """Toggle"""
        await update.callback_query.answer()
        user_id = update.effective_user.id
        
        current = self.monitoring_active.get(user_id, True)
        new_status = not current
        
        await self.toggle_monitoring(user_id, new_status)
        
        text = f"{'✅ ON' if new_status else '⏸️ OFF'}"
        
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
