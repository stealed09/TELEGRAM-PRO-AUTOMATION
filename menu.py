from telegram import InlineKeyboardButton, InlineKeyboardMarkup

class MenuUI:
    
    @staticmethod
    def main_menu():
        """Main menu with all features"""
        keyboard = [
            [
                InlineKeyboardButton("💬 Send Message", callback_data="send_message"),
                InlineKeyboardButton("🤖 Auto Reply", callback_data="auto_reply")
            ],
            [
                InlineKeyboardButton("⏰ Schedule", callback_data="schedule"),
                InlineKeyboardButton("📅 My Schedules", callback_data="my_schedules")
            ],
            [
                InlineKeyboardButton("👥 Multi-Account", callback_data="multi_account"),
                InlineKeyboardButton("📊 Analytics", callback_data="analytics")
            ],
            [
                InlineKeyboardButton("🔍 Scraper", callback_data="scraper"),
                InlineKeyboardButton("💼 Escrow", callback_data="escrow")
            ],
            [
                InlineKeyboardButton("📨 Sent Messages", callback_data="sent_messages"),
                InlineKeyboardButton("📈 Status", callback_data="status")
            ],
            [
                InlineKeyboardButton("🚪 Logout", callback_data="logout")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def multi_account_menu():
        """Multi-account management menu"""
        keyboard = [
            [
                InlineKeyboardButton("➕ Add Account", callback_data="add_account"),
                InlineKeyboardButton("📋 View Accounts", callback_data="view_accounts")
            ],
            [
                InlineKeyboardButton("🔄 Switch Account", callback_data="switch_account"),
            ],
            [
                InlineKeyboardButton("« Back", callback_data="main_menu")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def scraper_menu():
        """Scraper options menu"""
        keyboard = [
            [
                InlineKeyboardButton("👥 Scrape Group Members", callback_data="scrape_members"),
            ],
            [
                InlineKeyboardButton("💬 Scrape Message Replies", callback_data="scrape_replies"),
            ],
            [
                InlineKeyboardButton("« Back", callback_data="main_menu")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def schedule_menu():
        """Schedule options menu"""
        keyboard = [
            [
                InlineKeyboardButton("⚡ Instant Send", callback_data="schedule_instant"),
            ],
            [
                InlineKeyboardButton("⏱️ Time Schedule (HH:MM:SS)", callback_data="schedule_time"),
            ],
            [
                InlineKeyboardButton("🔁 Recurring Schedule", callback_data="schedule_recurring")
            ],
            [
                InlineKeyboardButton("« Back", callback_data="main_menu")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def auto_reply_menu():
        """Auto-reply management menu"""
        keyboard = [
            [
                InlineKeyboardButton("➕ Add Rule", callback_data="add_auto_reply"),
                InlineKeyboardButton("📋 View Rules", callback_data="view_auto_replies")
            ],
            [
                InlineKeyboardButton("🗑️ Delete Rule", callback_data="delete_auto_reply"),
            ],
            [
                InlineKeyboardButton("« Back", callback_data="main_menu")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def escrow_menu():
        """Escrow management menu"""
        keyboard = [
            [
                InlineKeyboardButton("➕ Add Group", callback_data="add_escrow_group"),
                InlineKeyboardButton("📋 View Groups", callback_data="view_escrow_groups")
            ],
            [
                InlineKeyboardButton("⏸️ Toggle Monitoring", callback_data="toggle_escrow_monitoring"),
            ],
            [
                InlineKeyboardButton("« Back", callback_data="main_menu")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def back_button():
        """Simple back button"""
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("« Back to Menu", callback_data="main_menu")
        ]])

menu_ui = MenuUI()
