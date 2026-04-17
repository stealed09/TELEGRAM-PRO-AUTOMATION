import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db
from client_manager import client_manager
from messaging import message_sender
from config import ADMIN_IDS
from telethon import events

class EscrowManager:
    def __init__(self):
        self.pending_forms = {}
        self.active_deals = {}
        self.monitoring_active = {}  # {user_id: bool}
    
    def parse_escrow_form(self, text):
        """Parse escrow form from message"""
        try:
            data = {}
            
            # Deal type
            match = re.search(r'ᴅᴇᴀʟ ᴏꜰ[:\-\s]+(.+)', text, re.IGNORECASE)
            if match:
                data['deal_type'] = match.group(1).strip()
            
            # Amount
            match = re.search(r'ᴛᴏᴛᴀʟ ᴀᴍᴏᴜɴᴛ[:\-\s]+(\d+(?:\.\d+)?)', text, re.IGNORECASE)
            if match:
                data['amount'] = float(match.group(1))
            
            # Maximum time
            match = re.search(r'ᴍᴀxɪᴍᴜᴍ ᴛɪᴍᴇ[:\-\s]+(.+)', text, re.IGNORECASE)
            if match:
                data['max_time'] = match.group(1).strip()
            
            # Terms
            match = re.search(r'ᴛᴇʀᴍꜱ & ᴄᴏɴᴅɪᴛɪᴏɴ[:\-\s]+(.+)', text, re.IGNORECASE)
            if match:
                data['terms'] = match.group(1).strip()
            
            # Seller
            match = re.search(r'𝑺𝒆𝒍𝒍𝒆𝒓[:\-\s]+(\+?\d+)', text)
            if match:
                data['seller_id'] = match.group(1).strip()
            
            # Buyer
            match = re.search(r'𝑩𝒖𝒚𝒆𝒓[:\-\s]+(\+?\d+)', text)
            if match:
                data['buyer_id'] = match.group(1).strip()
            
            # Buyer bank
            match = re.search(r'Buyer Bank Name[:\-\s]+(.+)', text, re.IGNORECASE)
            if match:
                data['buyer_bank'] = match.group(1).strip()
            
            # Validate required fields
            required = ['deal_type', 'amount', 'max_time', 'seller_id', 'buyer_id']
            if all(key in data for key in required):
                return data
            else:
                return None
                
        except Exception as e:
            print(f"Error parsing form: {e}")
            return None
    
    async def setup_group_monitoring(self, user_id, account_id):
        """Setup Telethon event handler for escrow form detection in groups"""
        try:
            client = await client_manager.get_client(user_id, account_id)
            if not client:
                return False
            
            # Get monitored groups
            escrow_groups = await db.get_escrow_groups(user_id)
            
            if not escrow_groups:
                return False
            
            @client.on(events.NewMessage())
            async def escrow_form_detector(event):
                # Check if monitoring is active
                if not self.monitoring_active.get(user_id, True):
                    return
                
                # Check if message is from monitored group
                chat_id = event.chat_id
                is_monitored = any(str(chat_id) == str(g['group_id']) for g in escrow_groups)
                
                if not is_monitored:
                    return
                
                # Check if message contains escrow form
                if not event.text:
                    return
                
                deal_data = self.parse_escrow_form(event.text)
                
                if deal_data:
                    # INSTANTLY send confirmation from USER ACCOUNT
                    await self.process_detected_form(
                        user_id, account_id, chat_id, deal_data, event.message.id
                    )
            
            self.monitoring_active[user_id] = True
            print(f"✅ Escrow monitoring active for user {user_id}")
            return True
            
        except Exception as e:
            print(f"Error setting up monitoring: {e}")
            return False
    
    async def process_detected_form(self, user_id, account_id, chat_id, deal_data, original_msg_id):
        """Process automatically detected escrow form"""
        try:
            # Create escrow deal in database
            deal_id = await db.create_escrow_deal(
                user_id, account_id, chat_id, deal_data
            )
            
            # Send INSTANT confirmation message from USER ACCOUNT
            confirmation_msg = (
                f"🤝 **ESCROW DEAL INITIATED** (Auto-Detected)\n\n"
                f"📌 Deal ID: #{deal_id}\n"
                f"💰 Amount: {deal_data['amount']}\n"
                f"⏰ Time Limit: {deal_data['max_time']}\n\n"
                f"👥 **Parties Involved:**\n"
                f"• Seller: {deal_data['seller_id']}\n"
                f"• Buyer: {deal_data['buyer_id']}\n\n"
                f"📝 **Terms:** {deal_data.get('terms', 'N/A')}\n\n"
                f"⚠️ **Both parties, please reply 'AGREE' to this message.**"
            )
            
            # Send from user account (INSTANT, NO DELAY)
            result = await message_sender.send_message(
                user_id, chat_id, confirmation_msg, account_id
            )
            
            if result['success']:
                self.active_deals[deal_id] = {
                    'message_id': result['message_id'],
                    'chat_id': chat_id,
                    'user_id': user_id,
                    'account_id': account_id,
                    'deal_data': deal_data
                }
                
                await db.log_action(user_id, 'escrow_auto_detected', {'deal_id': deal_id})
                print(f"✅ Escrow deal #{deal_id} auto-created and sent")
        
        except Exception as e:
            print(f"Error processing detected form: {e}")
    
    async def toggle_monitoring(self, user_id, enable=True):
        """Start/Stop escrow monitoring"""
        self.monitoring_active[user_id] = enable
        status = "started" if enable else "stopped"
        await db.set_user_setting(user_id, 'escrow_monitoring', enable)
        return status
    
    async def handle_escrow_reply(self, event):
        """Handle replies to escrow messages (from Telethon)"""
        try:
            if not event.is_reply:
                return
            
            reply_to_msg = await event.get_reply_message()
            
            deal_id = None
            for did, deal_info in self.active_deals.items():
                if reply_to_msg.id == deal_info['message_id']:
                    deal_id = did
                    break
            
            if not deal_id:
                return
            
            deal = await db.get_escrow_deal(deal_id)
            
            if not deal or deal['status'] != 'pending':
                return
            
            sender_id = str(event.sender_id)
            message_text = event.text.upper().strip()
            
            if 'AGREE' not in message_text:
                return
            
            # Update agreement status
            if sender_id == deal['seller_id'] or f"+{sender_id}" == deal['seller_id']:
                await db.update_escrow_agreement(deal_id, 'seller')
                deal['seller_agreed'] = True
            elif sender_id == deal['buyer_id'] or f"+{sender_id}" == deal['buyer_id']:
                await db.update_escrow_agreement(deal_id, 'buyer')
                deal['buyer_agreed'] = True
            else:
                return
            
            deal = await db.get_escrow_deal(deal_id)
            
            if deal['buyer_agreed'] and deal['seller_agreed']:
                await db.update_escrow_status(deal_id, 'waiting_admin')
                
                confirmation_msg = (
                    f"✅ **BOTH PARTIES AGREED**\n\n"
                    f"Deal ID: #{deal_id}\n"
                    f"Status: Waiting for admin approval\n\n"
                    f"An admin will review and approve this deal shortly."
                )
                
                deal_info = self.active_deals[deal_id]
                await message_sender.send_message(
                    deal_info['user_id'],
                    deal_info['chat_id'],
                    confirmation_msg,
                    deal_info['account_id']
                )
                
                await self.notify_admin_for_approval(deal_id, deal)
        
        except Exception as e:
            print(f"Error handling escrow reply: {e}")
    
    async def add_escrow_group_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add group for escrow monitoring"""
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "➕ **Add Escrow Group**\n\n"
            "Send the group ID or username to monitor:\n\n"
            "Format:\n"
            "`/addescrowgroup <group_id_or_username>`\n\n"
            "Example:\n"
            "`/addescrowgroup @mygroup`\n"
            "`/addescrowgroup -1001234567890`",
            parse_mode='Markdown',
            reply_markup=menu_ui.back_button()
        )
    
    async def view_escrow_groups_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View monitored escrow groups"""
        await update.callback_query.answer()
        user_id = update.effective_user.id
        
        groups = await db.get_escrow_groups(user_id)
        
        if not groups:
            await update.callback_query.edit_message_text(
                "📋 **Escrow Groups**\n\n"
                "No groups added yet.\n\n"
                "Use `/addescrowgroup <group>` to add one.",
                parse_mode='Markdown',
                reply_markup=menu_ui.escrow_menu()
            )
            return
        
        text = "📋 **Monitored Escrow Groups**\n\n"
        
        for group in groups:
            status = "🟢 Active" if group['is_active'] else "🔴 Inactive"
            text += f"{status} - {group['group_name']}\n"
            text += f"   ID: `{group['group_id']}`\n\n"
        
        monitoring_status = self.monitoring_active.get(user_id, True)
        text += f"\n📡 Monitoring: {'✅ ON' if monitoring_status else '⏸️ OFF'}"
        
        keyboard = [
            [
                InlineKeyboardButton(
                    "⏸️ Stop Monitoring" if monitoring_status else "▶️ Start Monitoring",
                    callback_data="toggle_escrow_monitoring"
                )
            ],
            [InlineKeyboardButton("« Back", callback_data="escrow")]
        ]
        
        await update.callback_query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def toggle_monitoring_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Toggle escrow monitoring on/off"""
        await update.callback_query.answer()
        user_id = update.effective_user.id
        
        current_status = self.monitoring_active.get(user_id, True)
        new_status = not current_status
        
        status = await self.toggle_monitoring(user_id, new_status)
        
        await update.callback_query.edit_message_text(
            f"{'✅' if new_status else '⏸️'} Escrow monitoring {status}!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="view_escrow_groups")
            ]])
        )
    
    async def notify_admin_for_approval(self, deal_id, deal):
        """Notify admin for deal approval"""
        try:
            from telegram import Bot
            from config import BOT_TOKEN
            
            bot = Bot(token=BOT_TOKEN)
            
            admin_msg = (
                f"🔔 **NEW ESCROW DEAL PENDING APPROVAL**\n\n"
                f"Deal ID: #{deal_id}\n"
                f"Amount: {deal['amount']}\n"
                f"Time Limit: {deal['max_time']}\n"
                f"Deal Type: {deal['deal_type']}\n\n"
                f"Seller: {deal['seller_id']} ✅\n"
                f"Buyer: {deal['buyer_id']} ✅\n\n"
                f"Terms: {deal['terms']}\n"
                f"Buyer Bank: {deal['buyer_bank']}"
            )
            
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"escrow_approve_{deal_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"escrow_reject_{deal_id}")
                ]
            ])
            
            for admin_id in ADMIN_IDS:
                await bot.send_message(
                    chat_id=admin_id,
                    text=admin_msg,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
        
        except Exception as e:
            print(f"Error notifying admin: {e}")
    
    async def approve_escrow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin approves escrow deal"""
        query = update.callback_query
        await query.answer()
        
        deal_id = int(query.data.split('_')[-1])
        deal = await db.get_escrow_deal(deal_id)
        
        if not deal:
            await query.edit_message_text("❌ Deal not found.")
            return
        
        await db.update_escrow_status(deal_id, 'approved', admin_approved=True)
        
        approval_msg = (
            f"✅ **DEAL APPROVED BY ADMIN**\n\n"
            f"Deal ID: #{deal_id}\n"
            f"Amount: {deal['amount']}\n\n"
            f"The escrow deal has been approved. Proceed with the transaction.\n\n"
            f"⚠️ Follow the agreed terms and timeline."
        )
        
        deal_info = self.active_deals.get(deal_id)
        if deal_info:
            await message_sender.send_message(
                deal_info['user_id'],
                deal_info['chat_id'],
                approval_msg,
                deal_info['account_id']
            )
        
        await query.edit_message_text(
            f"✅ Deal #{deal_id} approved successfully!",
            parse_mode='Markdown'
        )
        
        await db.log_action(deal['user_id'], 'escrow_approved', {'deal_id': deal_id})
    
    async def reject_escrow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin rejects escrow deal"""
        query = update.callback_query
        await query.answer()
        
        deal_id = int(query.data.split('_')[-1])
        deal = await db.get_escrow_deal(deal_id)
        
        if not deal:
            await query.edit_message_text("❌ Deal not found.")
            return
        
        await db.update_escrow_status(deal_id, 'rejected', admin_approved=False)
        
        rejection_msg = (
            f"❌ **DEAL REJECTED BY ADMIN**\n\n"
            f"Deal ID: #{deal_id}\n\n"
            f"The escrow deal has been rejected by the admin.\n"
            f"Please contact support for more information."
        )
        
        deal_info = self.active_deals.get(deal_id)
        if deal_info:
            await message_sender.send_message(
                deal_info['user_id'],
                deal_info['chat_id'],
                rejection_msg,
                deal_info['account_id']
            )
        
        await query.edit_message_text(
            f"❌ Deal #{deal_id} rejected.",
            parse_mode='Markdown'
        )
        
        await db.log_action(deal['user_id'], 'escrow_rejected', {'deal_id': deal_id})

escrow_manager = EscrowManager()
