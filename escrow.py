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
            
            # Normalize text - remove extra spaces and special bullets
            normalized_text = text.replace('●', '•').replace('○', '•')
            
            # Deal type - REQUIRED
            patterns = [
                r'[•●]\s*ᴅᴇᴀʟ\s+ᴏꜰ\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
                r'DEAL\s+OF\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
                r'Deal\s+of\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
            ]
            for pattern in patterns:
                match = re.search(pattern, normalized_text, re.IGNORECASE | re.MULTILINE)
                if match:
                    data['deal_type'] = match.group(1).strip()
                    break
            
            if 'deal_type' not in data:
                print("❌ Deal type not found")
                return None
            
            # Amount - REQUIRED
            patterns = [
                r'[•●]\s*ᴛᴏᴛᴀʟ\s+ᴀᴍᴏᴜɴᴛ\s*[:\-]+\s*(\d+(?:\.\d+)?)',
                r'TOTAL\s+AMOUNT\s*[:\-]+\s*(\d+(?:\.\d+)?)',
                r'Amount\s*[:\-]+\s*(\d+(?:\.\d+)?)',
            ]
            for pattern in patterns:
                match = re.search(pattern, normalized_text, re.IGNORECASE)
                if match:
                    data['amount'] = float(match.group(1))
                    break
            
            if 'amount' not in data:
                print("❌ Amount not found")
                return None
            
            # Maximum time - REQUIRED
            patterns = [
                r'[•●]\s*ᴍᴀxɪᴍᴜᴍ\s+ᴛɪᴍᴇ\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
                r'MAXIMUM\s+TIME\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
                r'Time\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
            ]
            for pattern in patterns:
                match = re.search(pattern, normalized_text, re.IGNORECASE | re.MULTILINE)
                if match:
                    data['max_time'] = match.group(1).strip()
                    break
            
            if 'max_time' not in data:
                print("❌ Maximum time not found")
                return None
            
            # Terms - REQUIRED
            patterns = [
                r'[•●]\s*ᴛᴇʀᴍꜱ\s*&\s*ᴄᴏɴᴅɪᴛɪᴏɴ\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
                r'TERMS\s*&\s*CONDITION\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
                r'Terms\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
            ]
            for pattern in patterns:
                match = re.search(pattern, normalized_text, re.IGNORECASE | re.MULTILINE)
                if match:
                    data['terms'] = match.group(1).strip()
                    break
            
            if 'terms' not in data:
                print("❌ Terms not found")
                return None
            
            # Seller - REQUIRED (handles special characters: 𝑺𝒆𝒍𝒍𝒆𝒓)
            patterns = [
                r'[•●]\s*[𝑺𝒔Ss]𝒆𝒍𝒍𝒆𝒓\s*[:\-\s]+(\+?\d+)',
                r'[•●]\s*Seller\s*[:\-\s]+(\+?\d+)',
                r'SELLER\s*[:\-\s]+(\+?\d+)',
                r'Seller\s*[:\-\s]+(\+?\d+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    data['seller_id'] = match.group(1).strip()
                    break
            
            if 'seller_id' not in data:
                print("❌ Seller not found")
                return None
            
            # Buyer - REQUIRED (handles special characters: 𝑩𝒖𝒚𝒆𝒓)
            patterns = [
                r'[•●]\s*[𝑩𝒃Bb]𝒖𝒚𝒆𝒓\s*[:\-\s]+(\+?\d+)',
                r'[•●]\s*Buyer\s*[:\-\s]+(\+?\d+)',
                r'BUYER\s*[:\-\s]+(\+?\d+)',
                r'Buyer\s*[:\-\s]+(\+?\d+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    data['buyer_id'] = match.group(1).strip()
                    break
            
            if 'buyer_id' not in data:
                print("❌ Buyer not found")
                return None
            
            # Buyer bank - OPTIONAL
            patterns = [
                r'[•●]\s*Buyer\s+Bank\s+Name\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
                r'BUYER\s+BANK\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
                r'Bank\s+Name\s*[:\-]+\s*(.+?)(?=\n|●|•|$)',
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
                print(f"✅ Escrow form parsed successfully:")
                print(f"   Deal: {data['deal_type']}")
                print(f"   Amount: {data['amount']}")
                print(f"   Time: {data['max_time']}")
                print(f"   Seller: {data['seller_id']}")
                print(f"   Buyer: {data['buyer_id']}")
                print(f"   Bank: {data['buyer_bank']}")
                return data
            else:
                missing = [k for k in required if k not in data or not data[k]]
                print(f"❌ Missing required fields: {missing}")
                return None
                
        except Exception as e:
            print(f"❌ Error parsing escrow form: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def setup_group_monitoring(self, user_id, account_id):
        """Setup Telethon event handler for escrow form detection in groups"""
        try:
            client = await client_manager.get_client(user_id, account_id)
            if not client:
                print(f"❌ No client found for user {user_id}")
                return False
            
            # Get monitored groups
            escrow_groups = await db.get_escrow_groups(user_id)
            
            if not escrow_groups:
                print(f"ℹ️ No escrow groups configured for user {user_id}")
                return False
            
            group_ids = [g['group_id'] for g in escrow_groups]
            print(f"📡 Setting up escrow monitoring for user {user_id}")
            print(f"   Groups: {group_ids}")
            
            @client.on(events.NewMessage())
            async def escrow_form_detector(event):
                try:
                    # Check if monitoring is active
                    if not self.monitoring_active.get(user_id, True):
                        return
                    
                    # Check if message is from monitored group
                    chat_id = str(event.chat_id)
                    
                    # Match with or without -100 prefix
                    is_monitored = any(
                        chat_id == str(g['group_id']) or 
                        chat_id == str(g['group_id']).replace('-100', '') or
                        f"-100{chat_id}" == str(g['group_id']) or
                        chat_id.replace('-100', '') == str(g['group_id']).replace('-100', '')
                        for g in escrow_groups
                    )
                    
                    if not is_monitored:
                        return
                    
                    # Check if message contains text
                    if not event.text:
                        return
                    
                    # Parse the form
                    deal_data = self.parse_escrow_form(event.text)
                    
                    if deal_data:
                        print(f"🎯 ESCROW FORM DETECTED in chat {chat_id}")
                        # INSTANTLY send confirmation from USER ACCOUNT
                        await self.process_detected_form(
                            user_id, account_id, event.chat_id, deal_data, event.message.id
                        )
                
                except Exception as e:
                    print(f"❌ Error in escrow form detector: {e}")
                    import traceback
                    traceback.print_exc()
            
            self.monitoring_active[user_id] = True
            print(f"✅ Escrow monitoring ACTIVE for user {user_id}")
            return True
            
        except Exception as e:
            print(f"❌ Error setting up monitoring: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def process_detected_form(self, user_id, account_id, chat_id, deal_data, original_msg_id):
        """Process automatically detected escrow form"""
        try:
            print(f"📝 Creating escrow deal in database...")
            
            # Create escrow deal in database
            deal_id = await db.create_escrow_deal(
                user_id, account_id, chat_id, deal_data
            )
            
            print(f"✅ Escrow deal #{deal_id} created in database")
            
            # Send INSTANT confirmation message from USER ACCOUNT
            confirmation_msg = (
                f"🤝 **ESCROW DEAL INITIATED**\n\n"
                f"📌 Deal ID: #{deal_id}\n"
                f"💰 Amount: {deal_data['amount']}\n"
                f"⏰ Time Limit: {deal_data['max_time']}\n"
                f"📝 Type: {deal_data['deal_type']}\n\n"
                f"👥 **Parties:**\n"
                f"• Seller: {deal_data['seller_id']}\n"
                f"• Buyer: {deal_data['buyer_id']}\n\n"
                f"📋 **Terms:** {deal_data.get('terms', 'N/A')}\n"
                f"🏦 **Bank:** {deal_data.get('buyer_bank', 'N/A')}\n\n"
                f"⚠️ **Both parties, please reply 'AGREE' to this message to confirm.**"
            )
            
            print(f"📤 Sending confirmation message from user account...")
            
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
                print(f"✅ Escrow deal #{deal_id} confirmation sent successfully!")
                print(f"   Message ID: {result['message_id']}")
                print(f"   Chat ID: {chat_id}")
            else:
                print(f"❌ Failed to send escrow confirmation: {result['error']}")
        
        except Exception as e:
            print(f"❌ Error processing detected form: {e}")
            import traceback
            traceback.print_exc()
    
    async def toggle_monitoring(self, user_id, enable=True):
        """Start/Stop escrow monitoring"""
        self.monitoring_active[user_id] = enable
        status = "started" if enable else "stopped"
        await db.set_user_setting(user_id, 'escrow_monitoring', enable)
        print(f"{'✅' if enable else '⏸️'} Escrow monitoring {status} for user {user_id}")
        return status
    
    async def handle_escrow_reply(self, event):
        """Handle replies to escrow messages (from Telethon)"""
        try:
            if not event.is_reply:
                return
            
            reply_to_msg = await event.get_reply_message()
            
            # Find the deal this reply is for
            deal_id = None
            for did, deal_info in self.active_deals.items():
                if reply_to_msg.id == deal_info['message_id']:
                    deal_id = did
                    break
            
            if not deal_id:
                return
            
            print(f"📩 Reply detected for escrow deal #{deal_id}")
            
            # Get deal from database
            deal = await db.get_escrow_deal(deal_id)
            
            if not deal or deal['status'] != 'pending':
                print(f"ℹ️ Deal #{deal_id} is not in pending status (current: {deal['status'] if deal else 'not found'})")
                return
            
            # Check if sender is buyer or seller
            sender_id = str(event.sender_id)
            message_text = event.text.upper().strip() if event.text else ""
            
            if 'AGREE' not in message_text:
                print(f"ℹ️ Reply from {sender_id} doesn't contain 'AGREE'")
                return
            
            # Normalize phone numbers for comparison
            seller_normalized = deal['seller_id'].replace('+', '').strip()
            buyer_normalized = deal['buyer_id'].replace('+', '').strip()
            
            print(f"🔍 Checking sender {sender_id}")
            print(f"   Seller: {deal['seller_id']} (normalized: {seller_normalized})")
            print(f"   Buyer: {deal['buyer_id']} (normalized: {buyer_normalized})")
            
            # Update agreement status
            if sender_id == seller_normalized or sender_id == deal['seller_id'] or f"+{sender_id}" == deal['seller_id']:
                await db.update_escrow_agreement(deal_id, 'seller')
                print(f"✅ Seller {sender_id} agreed to deal #{deal_id}")
            elif sender_id == buyer_normalized or sender_id == deal['buyer_id'] or f"+{sender_id}" == deal['buyer_id']:
                await db.update_escrow_agreement(deal_id, 'buyer')
                print(f"✅ Buyer {sender_id} agreed to deal #{deal_id}")
            else:
                print(f"ℹ️ Reply from non-party member {sender_id} for deal #{deal_id}")
                return
            
            # Reload deal to check if both agreed
            deal = await db.get_escrow_deal(deal_id)
            
            print(f"📊 Deal #{deal_id} status: Buyer agreed: {deal['buyer_agreed']}, Seller agreed: {deal['seller_agreed']}")
            
            # Check if both parties agreed
            if deal['buyer_agreed'] and deal['seller_agreed']:
                print(f"🎉 Both parties agreed to deal #{deal_id}!")
                
                await db.update_escrow_status(deal_id, 'waiting_admin')
                
                confirmation_msg = (
                    f"✅ **BOTH PARTIES AGREED**\n\n"
                    f"Deal ID: #{deal_id}\n"
                    f"💰 Amount: {deal['amount']}\n\n"
                    f"Status: ⏳ Waiting for admin approval\n\n"
                    f"An admin will review and approve this deal shortly."
                )
                
                deal_info = self.active_deals[deal_id]
                
                print(f"📤 Sending both-parties-agreed confirmation...")
                
                result = await message_sender.send_message(
                    deal_info['user_id'],
                    deal_info['chat_id'],
                    confirmation_msg,
                    deal_info['account_id']
                )
                
                if result['success']:
                    print(f"✅ Confirmation sent successfully")
                else:
                    print(f"❌ Failed to send confirmation: {result['error']}")
                
                print(f"📧 Notifying admin for approval...")
                await self.notify_admin_for_approval(deal_id, deal)
        
        except Exception as e:
            print(f"❌ Error handling escrow reply: {e}")
            import traceback
            traceback.print_exc()
    
    async def add_escrow_group_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add group for escrow monitoring"""
        from menu import menu_ui  # Import here to avoid circular import
        
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                "➕ **Add Escrow Group**\n\n"
                "Send the group ID or username:\n\n"
                "Format:\n"
                "`/addescrowgroup <group_id_or_username>`\n\n"
                "Examples:\n"
                "`/addescrowgroup @mygroup`\n"
                "`/addescrowgroup -1001234567890`",
                parse_mode='Markdown',
                reply_markup=menu_ui.back_button()
            )
        except BadRequest:
            pass
    
    async def view_escrow_groups_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View monitored escrow groups"""
        from menu import menu_ui  # Import here to avoid circular import
        
        await update.callback_query.answer()
        user_id = update.effective_user.id
        
        groups = await db.get_escrow_groups(user_id)
        
        if not groups:
            try:
                await update.callback_query.edit_message_text(
                    "📋 **Escrow Groups**\n\n"
                    "No groups added yet.\n\n"
                    "Use `/addescrowgroup <group>` to add one.\n\n"
                    "Example:\n"
                    "`/addescrowgroup @yourgroup`",
                    parse_mode='Markdown',
                    reply_markup=menu_ui.escrow_menu()
                )
            except BadRequest:
                pass
            return
        
        text = "📋 **Monitored Escrow Groups**\n\n"
        
        for group in groups:
            status = "🟢 Active" if group['is_active'] else "🔴 Inactive"
            text += f"{status} - {group['group_name']}\n"
            text += f"   ID: `{group['group_id']}`\n\n"
        
        monitoring_status = self.monitoring_active.get(user_id, True)
        text += f"\n📡 Monitoring: {'✅ ON' if monitoring_status else '⏸️ OFF'}\n\n"
        text += "When monitoring is ON, I'll automatically detect\n"
        text += "escrow forms and reply instantly from your account!"
        
        keyboard = [
            [
                InlineKeyboardButton(
                    "⏸️ Stop Monitoring" if monitoring_status else "▶️ Start Monitoring",
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
        """Toggle escrow monitoring on/off"""
        await update.callback_query.answer()
        user_id = update.effective_user.id
        
        current_status = self.monitoring_active.get(user_id, True)
        new_status = not current_status
        
        status = await self.toggle_monitoring(user_id, new_status)
        
        status_emoji = "✅" if new_status else "⏸️"
        status_text = "ON" if new_status else "OFF"
        
        message_text = (
            f"{status_emoji} **Escrow monitoring is now {status_text}!**\n\n"
        )
        
        if new_status:
            message_text += (
                "I'm now watching your groups for escrow forms.\n"
                "When someone posts a form, I'll:\n"
                "1. Detect it instantly\n"
                "2. Reply from your account\n"
                "3. Track both parties' agreements\n"
                "4. Notify admin for approval"
            )
        else:
            message_text += "Escrow form detection is paused."
        
        try:
            await update.callback_query.edit_message_text(
                message_text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Back", callback_data="view_escrow_groups")
                ]])
            )
        except BadRequest:
            pass
    async def notify_admin_for_approval(self, deal_id, deal):
        """Notify admin for deal approval"""
        try:
            bot = Bot(token=BOT_TOKEN)
            
            admin_msg = (
                f"🔔 **NEW ESCROW DEAL PENDING APPROVAL**\n\n"
                f"Deal ID: #{deal_id}\n"
                f"💰 Amount: {deal['amount']}\n"
                f"⏰ Time: {deal['max_time']}\n"
                f"📝 Type: {deal['deal_type']}\n\n"
                f"👥 **Parties:**\n"
                f"• Seller: {deal['seller_id']} ✅\n"
                f"• Buyer: {deal['buyer_id']} ✅\n\n"
                f"📋 Terms: {deal['terms']}\n"
                f"🏦 Bank: {deal['buyer_bank']}\n\n"
                f"Both parties have agreed. Approve or reject below:"
            )
            
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"escrow_approve_{deal_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"escrow_reject_{deal_id}")
                ]
            ])
            
            sent_count = 0
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=admin_msg,
                        reply_markup=keyboard,
                        parse_mode='Markdown'
                    )
                    sent_count += 1
                    print(f"✅ Admin notification sent to {admin_id} for deal #{deal_id}")
                except Exception as e:
                    print(f"❌ Failed to send to admin {admin_id}: {e}")
            
            if sent_count > 0:
                print(f"✅ Admin notifications sent ({sent_count}/{len(ADMIN_IDS)})")
            else:
                print(f"❌ No admin notifications sent!")
        
        except Exception as e:
            print(f"❌ Error notifying admin: {e}")
            import traceback
            traceback.print_exc()
    async def approve_escrow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin approves escrow deal"""
        query = update.callback_query
        await query.answer()
        
        deal_id = int(query.data.split('_')[-1])
        
        print(f"✅ Admin approving deal #{deal_id}")
        
        deal = await db.get_escrow_deal(deal_id)
        
        if not deal:
            await query.edit_message_text("❌ Deal not found.")
            return
        
        await db.update_escrow_status(deal_id, 'approved', admin_approved=True)
        
        approval_msg = (
            f"✅ **DEAL APPROVED BY ADMIN**\n\n"
            f"Deal ID: #{deal_id}\n"
            f"💰 Amount: {deal['amount']}\n\n"
            f"The escrow deal has been officially approved.\n"
            f"You may proceed with the transaction.\n\n"
            f"⚠️ Please follow the agreed terms and timeline:\n"
            f"Time Limit: {deal['max_time']}\n"
            f"Terms: {deal['terms']}"
        )
        
        deal_info = self.active_deals.get(deal_id)
        if deal_info:
            result = await message_sender.send_message(
                deal_info['user_id'],
                deal_info['chat_id'],
                approval_msg,
                deal_info['account_id']
            )
            
            if result['success']:
                print(f"✅ Approval message sent to chat")
            else:
                print(f"❌ Failed to send approval message: {result['error']}")
        
        try:
            await query.edit_message_text(
                f"✅ **Deal #{deal_id} approved successfully!**\n\n"
                f"Approval message has been sent to the group.",
                parse_mode='Markdown'
            )
        except BadRequest:
            pass
        
        await db.log_action(deal['user_id'], 'escrow_approved', {'deal_id': deal_id})
        print(f"✅ Deal #{deal_id} approved by admin and logged")
    async def reject_escrow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin rejects escrow deal"""
        query = update.callback_query
        await query.answer()
        
        deal_id = int(query.data.split('_')[-1])
        
        print(f"❌ Admin rejecting deal #{deal_id}")
        
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
            result = await message_sender.send_message(
                deal_info['user_id'],
                deal_info['chat_id'],
                rejection_msg,
                deal_info['account_id']
            )
            
            if result['success']:
                print(f"✅ Rejection message sent to chat")
            else:
                print(f"❌ Failed to send rejection message: {result['error']}")
        
        try:
            await query.edit_message_text(
                f"❌ **Deal #{deal_id} rejected.**\n\n"
                f"Rejection message has been sent to the group.",
                parse_mode='Markdown'
            )
        except BadRequest:
            pass
        
        await db.log_action(deal['user_id'], 'escrow_rejected', {'deal_id': deal_id})
        print(f"❌ Deal #{deal_id} rejected by admin and logged")

escrow_manager = EscrowManager()
        
