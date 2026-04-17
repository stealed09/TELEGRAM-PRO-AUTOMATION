from database import db
from client_manager import client_manager
from datetime import datetime, timedelta
import asyncio

class GroupMessageManager:
    def __init__(self):
        self.is_running = False
    
    async def check_and_send_group_messages(self):
        """Check and send group auto messages"""
        try:
            active_messages = await db.get_all_active_group_messages()
            
            for msg_config in active_messages:
                try:
                    # Check if it's time to send
                    if msg_config['last_sent']:
                        last_sent = datetime.fromisoformat(msg_config['last_sent'])
                        next_send = last_sent + timedelta(minutes=msg_config['interval_minutes'])
                        
                        if datetime.now() < next_send:
                            continue
                    
                    # Get client
                    client = await client_manager.get_client(
                        msg_config['user_id'], 
                        msg_config['account_id']
                    )
                    
                    if not client:
                        continue
                    
                    # Send message
                    await client.send_message(
                        int(msg_config['group_id']),
                        msg_config['message']
                    )
                    
                    # Update last sent
                    await db.update_group_message_last_sent(msg_config['id'])
                    
                    print(f"✅ Group auto message sent: {msg_config['group_name']}")
                    
                except Exception as e:
                    print(f"❌ Error sending group message: {e}")
        
        except Exception as e:
            print(f"❌ Group message check error: {e}")
    
    async def start_group_message_job(self):
        """Start group message job (runs every minute)"""
        self.is_running = True
        print("✅ Group message job started")
        
        while self.is_running:
            await self.check_and_send_group_messages()
            await asyncio.sleep(60)  # Check every minute

group_message_manager = GroupMessageManager()
