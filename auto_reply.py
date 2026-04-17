from database import db
from messaging import message_sender

class AutoReplyHandler:
    
    async def handle_incoming_message(self, event, user_id, account_id):
        """Handle incoming message and check for auto-reply rules"""
        try:
            # Get auto-reply rules
            rules = await db.get_auto_replies(user_id, account_id)
            
            if not rules:
                return
            
            message_text = event.text.lower() if event.text else ""
            
            # Check each rule
            for rule in rules:
                trigger = rule['trigger_text'].lower()
                
                if trigger in message_text:
                    # Send reply from user account
                    await event.respond(rule['reply_text'])
                    
                    # Log action
                    await db.log_action(
                        user_id,
                        'auto_reply_sent',
                        {
                            'rule_id': rule['id'],
                            'trigger': trigger,
                            'chat_id': event.chat_id
                        }
                    )
                    
                    break  # Only reply once
        
        except Exception as e:
            print(f"Auto-reply error: {e}")

auto_reply_handler = AutoReplyHandler()
