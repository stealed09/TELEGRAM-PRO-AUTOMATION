from database import db
from client_manager import client_manager
from datetime import datetime, timedelta
import asyncio


class GroupMessageManager:
    def __init__(self):
        self.is_running = False

    async def check_and_send_group_messages(self):
        """Check all active group messages and send those that are due"""
        try:
            active_messages = await db.get_all_active_group_messages()

            for msg_config in active_messages:
                try:
                    # Check if enough time has passed since last send
                    if msg_config['last_sent']:
                        last_sent = datetime.fromisoformat(msg_config['last_sent'])
                        interval = int(msg_config['interval_minutes'])
                        next_send = last_sent + timedelta(minutes=interval)

                        if datetime.now() < next_send:
                            continue  # Not time yet for this group

                    # Get the Telethon client for this user/account
                    client = await client_manager.get_client(
                        msg_config['user_id'],
                        msg_config['account_id']
                    )

                    if not client:
                        continue

                    # Send message to the group
                    await client.send_message(
                        int(msg_config['group_id']),
                        msg_config['message']
                    )

                    # Update last_sent timestamp
                    await db.update_group_message_last_sent(msg_config['id'])

                    print(
                        f"✅ Group auto message sent to '{msg_config['group_name']}' "
                        f"(interval: {msg_config['interval_minutes']}min)"
                    )

                except Exception as e:
                    print(f"❌ Error sending group message to {msg_config.get('group_name')}: {e}")

        except Exception as e:
            print(f"❌ Group message check error: {e}")

    async def start_group_message_job(self):
        """
        Background loop — checks every 60 seconds.
        Each group has its OWN interval_minutes setting so they are independent.
        """
        self.is_running = True
        print("✅ Group auto-message job started (checking every 60s, per-group intervals)")

        while self.is_running:
            await self.check_and_send_group_messages()
            await asyncio.sleep(60)  # Poll every 1 minute


group_message_manager = GroupMessageManager()
