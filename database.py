import aiosqlite
import json
from datetime import datetime
from config import DB_NAME

class Database:
    def __init__(self):
        self.db_name = DB_NAME
    
    async def init_db(self):
        async with aiosqlite.connect(self.db_name) as db:
            # Users table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Accounts table (multi-account support)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    phone TEXT,
                    api_id INTEGER,
                    api_hash TEXT,
                    session_string TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Scheduled messages
            await db.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    account_id INTEGER,
                    target TEXT,
                    message TEXT,
                    schedule_time TIMESTAMP,
                    is_recurring BOOLEAN DEFAULT 0,
                    recurring_pattern TEXT,
                    is_sent BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Auto reply rules
            await db.execute('''
                CREATE TABLE IF NOT EXISTS auto_reply_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    account_id INTEGER,
                    trigger_text TEXT,
                    reply_text TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Escrow deals
            await db.execute('''
                CREATE TABLE IF NOT EXISTS escrow_deals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    account_id INTEGER,
                    chat_id INTEGER,
                    deal_type TEXT,
                    amount REAL,
                    max_time TEXT,
                    terms TEXT,
                    seller_id TEXT,
                    buyer_id TEXT,
                    buyer_bank TEXT,
                    status TEXT DEFAULT 'pending',
                    buyer_agreed BOOLEAN DEFAULT 0,
                    seller_agreed BOOLEAN DEFAULT 0,
                    admin_approved BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Sent messages log
            await db.execute('''
                CREATE TABLE IF NOT EXISTS sent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    account_id INTEGER,
                    target TEXT,
                    message TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Analytics
            await db.execute('''
                CREATE TABLE IF NOT EXISTS analytics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action_type TEXT,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            await db.commit()
    
    # User operations
    async def add_user(self, user_id, username=None):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)',
                (user_id, username)
            )
            await db.commit()
    
    # Account operations
    async def add_account(self, user_id, phone, api_id, api_hash, session_string):
        async with aiosqlite.connect(self.db_name) as db:
            # Deactivate other accounts
            await db.execute(
                'UPDATE accounts SET is_active = 0 WHERE user_id = ?',
                (user_id,)
            )
            
            cursor = await db.execute(
                '''INSERT INTO accounts (user_id, phone, api_id, api_hash, session_string, is_active)
                   VALUES (?, ?, ?, ?, ?, 1)''',
                (user_id, phone, api_id, api_hash, session_string)
            )
            await db.commit()
            return cursor.lastrowid
    
    async def get_active_account(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM accounts WHERE user_id = ? AND is_active = 1',
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def get_all_accounts(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM accounts WHERE user_id = ? ORDER BY created_at DESC',
                (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def set_active_account(self, user_id, account_id):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'UPDATE accounts SET is_active = 0 WHERE user_id = ?',
                (user_id,)
            )
            await db.execute(
                'UPDATE accounts SET is_active = 1 WHERE id = ? AND user_id = ?',
                (account_id, user_id)
            )
            await db.commit()
    
    async def delete_account(self, account_id, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'DELETE FROM accounts WHERE id = ? AND user_id = ?',
                (account_id, user_id)
            )
            await db.commit()
    
    # Scheduled messages
    async def add_scheduled_message(self, user_id, account_id, target, message, schedule_time, is_recurring=False, recurring_pattern=None):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                '''INSERT INTO scheduled_messages 
                   (user_id, account_id, target, message, schedule_time, is_recurring, recurring_pattern)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (user_id, account_id, target, message, schedule_time, is_recurring, recurring_pattern)
            )
            await db.commit()
            return cursor.lastrowid
    
    async def get_pending_schedules(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                '''SELECT * FROM scheduled_messages 
                   WHERE user_id = ? AND is_sent = 0 
                   ORDER BY schedule_time''',
                (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_due_schedules(self):
        async with aiosqlite.connect(self.db_name) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                '''SELECT * FROM scheduled_messages 
                   WHERE is_sent = 0 AND schedule_time <= datetime('now')'''
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def mark_schedule_sent(self, schedule_id):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'UPDATE scheduled_messages SET is_sent = 1 WHERE id = ?',
                (schedule_id,)
            )
            await db.commit()
    
    async def delete_schedule(self, schedule_id, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'DELETE FROM scheduled_messages WHERE id = ? AND user_id = ?',
                (schedule_id, user_id)
            )
            await db.commit()
    
    # Auto reply rules
    async def add_auto_reply(self, user_id, account_id, trigger_text, reply_text):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                '''INSERT INTO auto_reply_rules (user_id, account_id, trigger_text, reply_text)
                   VALUES (?, ?, ?, ?)''',
                (user_id, account_id, trigger_text, reply_text)
            )
            await db.commit()
            return cursor.lastrowid
    
    async def get_auto_replies(self, user_id, account_id):
        async with aiosqlite.connect(self.db_name) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM auto_reply_rules WHERE user_id = ? AND account_id = ? AND is_active = 1',
                (user_id, account_id)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def delete_auto_reply(self, rule_id, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'DELETE FROM auto_reply_rules WHERE id = ? AND user_id = ?',
                (rule_id, user_id)
            )
            await db.commit()
    
    # Escrow operations
    async def create_escrow_deal(self, user_id, account_id, chat_id, deal_data):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                '''INSERT INTO escrow_deals 
                   (user_id, account_id, chat_id, deal_type, amount, max_time, terms, seller_id, buyer_id, buyer_bank)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (user_id, account_id, chat_id, deal_data['deal_type'], deal_data['amount'],
                 deal_data['max_time'], deal_data['terms'], deal_data['seller_id'],
                 deal_data['buyer_id'], deal_data['buyer_bank'])
            )
            await db.commit()
            return cursor.lastrowid
    
    async def get_escrow_deal(self, deal_id):
        async with aiosqlite.connect(self.db_name) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM escrow_deals WHERE id = ?',
                (deal_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def update_escrow_agreement(self, deal_id, party_type):
        async with aiosqlite.connect(self.db_name) as db:
            if party_type == 'buyer':
                await db.execute(
                    'UPDATE escrow_deals SET buyer_agreed = 1 WHERE id = ?',
                    (deal_id,)
                )
            else:
                await db.execute(
                    'UPDATE escrow_deals SET seller_agreed = 1 WHERE id = ?',
                    (deal_id,)
                )
            await db.commit()
    
    async def update_escrow_status(self, deal_id, status, admin_approved=None):
        async with aiosqlite.connect(self.db_name) as db:
            if admin_approved is not None:
                await db.execute(
                    'UPDATE escrow_deals SET status = ?, admin_approved = ? WHERE id = ?',
                    (status, admin_approved, deal_id)
                )
            else:
                await db.execute(
                    'UPDATE escrow_deals SET status = ? WHERE id = ?',
                    (status, deal_id)
                )
            await db.commit()
    
    async def get_pending_escrow_deals(self):
        async with aiosqlite.connect(self.db_name) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                '''SELECT * FROM escrow_deals 
                   WHERE status = 'waiting_admin' AND admin_approved = 0'''
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    # Sent messages log
    async def log_sent_message(self, user_id, account_id, target, message):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'INSERT INTO sent_messages (user_id, account_id, target, message) VALUES (?, ?, ?, ?)',
                (user_id, account_id, target, message)
            )
            await db.commit()
    
    async def get_sent_messages(self, user_id, limit=50):
        async with aiosqlite.connect(self.db_name) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM sent_messages WHERE user_id = ? ORDER BY sent_at DESC LIMIT ?',
                (user_id, limit)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    # Analytics
    async def log_action(self, user_id, action_type, details=None):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                'INSERT INTO analytics (user_id, action_type, details) VALUES (?, ?, ?)',
                (user_id, action_type, json.dumps(details) if details else None)
            )
            await db.commit()
    
    async def get_user_analytics(self, user_id):
        async with aiosqlite.connect(self.db_name) as db:
            # Total sent messages
            async with db.execute(
                'SELECT COUNT(*) as count FROM sent_messages WHERE user_id = ?',
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                total_sent = row[0]
            
            # Active schedules
            async with db.execute(
                'SELECT COUNT(*) as count FROM scheduled_messages WHERE user_id = ? AND is_sent = 0',
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                active_schedules = row[0]
            
            # Active auto replies
            async with db.execute(
                'SELECT COUNT(*) as count FROM auto_reply_rules WHERE user_id = ? AND is_active = 1',
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                active_replies = row[0]
            
            # Escrow deals
            async with db.execute(
                'SELECT COUNT(*) as count FROM escrow_deals WHERE user_id = ?',
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                total_deals = row[0]
            
            return {
                'total_sent': total_sent,
                'active_schedules': active_schedules,
                'active_auto_replies': active_replies,
                'total_escrow_deals': total_deals
            }

db = Database()
