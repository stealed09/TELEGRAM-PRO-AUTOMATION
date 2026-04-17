import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db
from client_manager import client_manager
from messaging import message_sender
from config import ADMIN_IDS

class EscrowManager:
    def __init__(self):
        self.pending_forms = {}  # {user_id: form_data}
        self.active_deals = {}   # {deal_id: deal_info}
    
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
    
    async def start_escrow_process(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start escrow process"""
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "📋 **Escrow Deal Creator**\n\n"
            "Please send the escrow deal form in this format:\n\n"
            "```\n"
            "● ᴅᴇᴀʟ ᴏꜰ:- PRIVATE\n"
            "● ᴛᴏᴛᴀʟ ᴀᴍᴏᴜɴᴛ:- 99\n"
            "● ᴍᴀxɪᴍᴜᴍ ᴛɪᴍᴇ:- 30MIN\n"
            "● ᴛᴇʀᴍꜱ & ᴄᴏɴᴅɪᴛɪᴏɴ:- NOTHING\n"
            " • 𝑺𝒆𝒍𝒍𝒆𝒓 : 8373559969\n"
            " • 𝑩𝒖𝒚𝒆𝒓 : 7695370162\n"
            "● Buyer Bank Name:- hsidvi\n"
            "```\n\n"
            "Or paste your own form.",
            parse_mode='Markdown'
        )
        
        context.user_data['awaiting_escrow_form'] = True
    
    async def process_escrow_form(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process submitted escrow form"""
        user_id = update.effective_user.id
        text = update.message.text
        
        # Parse form
        deal_data = self.parse_escrow_form(text)
        
        if not deal_data:
            await update.message.reply_text(
                "❌ Invalid form format. Please check and try again."
            )
            return
        
        # Get active account
        account = await db.get_active_account(user_id)
        if not account:
            await update.message.reply_text(
                "❌ No active account found. Please login first."
            )
            return
        
        # Get current chat ID
        chat_id = update.effective_chat.id
        
        # Create escrow deal in database
        deal_id = await db.create_escrow_deal(
            user_id, account['id'], chat_id, deal_data
        )
        
        # Send confirmation message from USER ACCOUNT
        confirmation_msg = (
            f"🤝 **ESCROW DEAL INITIATED**\n\n"
            f"📌 Deal ID: #{deal_id}\n"
            f"💰 Amount: {deal_data['amount']}\n"
            f"⏰ Time Limit: {deal_data['max_time']}\n\n"
            f"👥 **Parties Involved:**\n"
            f"• Seller: {deal_data['seller_id']}\n"
            f"• Buyer: {deal_data['buyer_id']}\n\n"
            f"📝 **Terms:** {deal_data.get('terms', 'N/A')}\n\n"
            f"⚠️ **Both parties, please confirm agreement by replying 'AGREE' to this message.**"
        )
        
        # Send from user account
        result = await message_sender.send_message(
            user_id, chat_id, confirmation_msg, account['id']
        )
        
        if result['success']:
            # Store message ID to track replies
            self.active_deals[deal_id] = {
                'message_id': result['message_id'],
                'chat_id': chat_id,
                'user_id': user_id,
                'account_id': account['id'],
                'deal_data': deal_data
            }
            
            await update.message.reply_text(
                f"✅ Escrow deal created successfully!\n"
                f"Deal ID: #{deal_id}\n\n"
                f"Waiting for both parties to confirm..."
            )
            
            # Log action
            await db.log_action(user_id, 'escrow_created', {'deal_id': deal_id})
        else:
            await update.message.reply_text(
                f"❌ Failed to send escrow message: {result['error']}"
            )
        
        context.user_data['awaiting_escrow_form'] = False
    
    async def handle_escrow_reply(self, event):
        """Handle replies to escrow messages (from Telethon)"""
        try:
            # Check if this is a reply
            if not event.is_reply:
                return
            
            # Get original message
            reply_to_msg = await event.get_reply_message()
            
            # Check if it's an escrow message
            deal_id = None
            for did, deal_info in self.active_deals.items():
                if reply_to_msg.id == deal_info['message_id']:
                    deal_id = did
                    break
            
            if not deal_id:
                return
            
            # Get deal from database
            deal = await db.get_escrow_deal(deal_id)
            
            if not deal or deal['status'] != 'pending':
                return
            
            # Check if sender is buyer or seller
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
                return  # Not a party to the deal
            
            # Reload deal
            deal = await db.get_escrow_deal(deal_id)
            
            # Check if both agreed
            if deal['buyer_agreed'] and deal['seller_agreed']:
                # Update status
                await db.update_escrow_status(deal_id, 'waiting_admin')
                
                # Send confirmation message from user account
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
                
                # Notify admin
                await self.notify_admin_for_approval(deal_id, deal)
        
        except Exception as e:
            print(f"Error handling escrow reply: {e}")
    
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
        
        # Extract deal ID
        deal_id = int(query.data.split('_')[-1])
        
        # Get deal
        deal = await db.get_escrow_deal(deal_id)
        
        if not deal:
            await query.edit_message_text("❌ Deal not found.")
            return
        
        # Update status
        await db.update_escrow_status(deal_id, 'approved', admin_approved=True)
        
        # Send approval message from user account
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
        
        # Log action
        await db.log_action(deal['user_id'], 'escrow_approved', {'deal_id': deal_id})
    
    async def reject_escrow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin rejects escrow deal"""
        query = update.callback_query
        await query.answer()
        
        # Extract deal ID
        deal_id = int(query.data.split('_')[-1])
        
        # Get deal
        deal = await db.get_escrow_deal(deal_id)
        
        if not deal:
            await query.edit_message_text("❌ Deal not found.")
            return
        
        # Update status
        await db.update_escrow_status(deal_id, 'rejected', admin_approved=False)
        
        # Send rejection message from user account
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
        
        # Log action
        await db.log_action(deal['user_id'], 'escrow_rejected', {'deal_id': deal_id})

escrow_manager = EscrowManager()
