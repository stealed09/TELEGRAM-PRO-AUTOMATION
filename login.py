from telethon.sessions import StringSession
from telethon import TelegramClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import ContextTypes, ConversationHandler
from database import db
from client_manager import client_manager
from config import BOT_TOKEN

# Conversation states
API_ID, API_HASH, PHONE, OTP, PASSWORD = range(5)

class LoginHandler:
    def __init__(self):
        self.temp_data = {}  # Temporary storage during login
    
    async def start_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start login process"""
        user_id = update.effective_user.id
        
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "🔐 **Account Login Process**\n\n"
            "Please enter your **API ID**:\n\n"
            "Get it from: https://my.telegram.org",
            parse_mode='Markdown'
        )
        
        self.temp_data[user_id] = {}
        return API_ID
    
    async def receive_api_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive API ID"""
        user_id = update.effective_user.id
        
        try:
            api_id = int(update.message.text.strip())
            self.temp_data[user_id]['api_id'] = api_id
            
            await update.message.reply_text(
                "✅ API ID received!\n\n"
                "Now send your **API HASH**:",
                parse_mode='Markdown'
            )
            return API_HASH
        except ValueError:
            await update.message.reply_text("❌ Invalid API ID. Please send numbers only.")
            return API_ID
    
    async def receive_api_hash(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive API Hash"""
        user_id = update.effective_user.id
        
        api_hash = update.message.text.strip()
        self.temp_data[user_id]['api_hash'] = api_hash
        
        await update.message.reply_text(
            "✅ API HASH received!\n\n"
            "Now send your **Phone Number** (with country code):\n"
            "Example: +1234567890",
            parse_mode='Markdown'
        )
        return PHONE
    
    async def receive_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive phone and send OTP"""
        user_id = update.effective_user.id
        phone = update.message.text.strip()
        
        self.temp_data[user_id]['phone'] = phone
        
        try:
            # Create temporary client to send OTP
            api_id = self.temp_data[user_id]['api_id']
            api_hash = self.temp_data[user_id]['api_hash']
            
            client = TelegramClient(StringSession(), api_id, api_hash)
            await client.connect()
            
            # Send OTP
            await client.send_code_request(phone)
            self.temp_data[user_id]['temp_client'] = client
            
            await update.message.reply_text(
                "📱 **OTP Sent!**\n\n"
                "Please enter the OTP code you received:",
                parse_mode='Markdown'
            )
            return OTP
            
        except Exception as e:
            await update.message.reply_text(
                f"❌ Error sending OTP: {str(e)}\n\n"
                "Please restart the login process."
            )
            return ConversationHandler.END
    
    async def receive_otp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive OTP and login"""
        user_id = update.effective_user.id
        otp = update.message.text.strip().replace('-', '')
        
        try:
            client = self.temp_data[user_id]['temp_client']
            phone = self.temp_data[user_id]['phone']
            
            try:
                # Try to sign in
                await client.sign_in(phone, otp)
                
                # Success - save session
                await self._save_session(user_id, client)
                return ConversationHandler.END
                
            except Exception as e:
                if "Two-steps verification" in str(e) or "password" in str(e).lower():
                    # 2FA required
                    await update.message.reply_text(
                        "🔐 **2FA Enabled**\n\n"
                        "Please enter your **2FA Password**:",
                        parse_mode='Markdown'
                    )
                    return PASSWORD
                else:
                    raise e
                    
        except Exception as e:
            await update.message.reply_text(
                f"❌ Login failed: {str(e)}\n\n"
                "Please restart the login process."
            )
            return ConversationHandler.END
    
    async def receive_password(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive 2FA password"""
        user_id = update.effective_user.id
        password = update.message.text.strip()
        
        try:
            client = self.temp_data[user_id]['temp_client']
            
            # Sign in with password
            await client.sign_in(password=password)
            
            # Success - save session
            await self._save_session(user_id, client)
            return ConversationHandler.END
            
        except Exception as e:
            await update.message.reply_text(
                f"❌ 2FA Password incorrect: {str(e)}\n\n"
                "Please restart the login process."
            )
            return ConversationHandler.END
    
    async def _save_session(self, user_id, client):
        """Save session to database"""
        try:
            # Get session string
            session_string = client.session.save()
            
            # Get account info
            me = await client.get_me()
            
            api_id = self.temp_data[user_id]['api_id']
            api_hash = self.temp_data[user_id]['api_hash']
            phone = self.temp_data[user_id]['phone']
            
            # Save to database
            account_id = await db.add_account(user_id, phone, api_id, api_hash, session_string)
            
            # Store in client manager
            await client_manager.create_client(user_id, account_id, api_id, api_hash, session_string)
            
            # Clean up temp data
            if user_id in self.temp_data:
                del self.temp_data[user_id]
            
            # Send success message using Bot instance
            bot = Bot(token=BOT_TOKEN)
            
            await bot.send_message(
                chat_id=user_id,
                text=f"✅ **Login Successful!**\n\n"
                     f"👤 Name: {me.first_name}\n"
                     f"📱 Phone: {phone}\n"
                     f"🆔 ID: {me.id}\n\n"
                     f"Your account is now active and ready to use!",
                parse_mode='Markdown'
            )
            
            # Log action
            await db.log_action(user_id, 'account_added', {'phone': phone})
            
        except Exception as e:
            print(f"Error saving session: {e}")
    
    async def cancel_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel login process"""
        user_id = update.effective_user.id
        
        if user_id in self.temp_data:
            if 'temp_client' in self.temp_data[user_id]:
                await self.temp_data[user_id]['temp_client'].disconnect()
            del self.temp_data[user_id]
        
        await update.message.reply_text("❌ Login cancelled.")
        return ConversationHandler.END

login_handler = LoginHandler()
