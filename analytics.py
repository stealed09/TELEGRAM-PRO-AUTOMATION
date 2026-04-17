from database import db
from datetime import datetime, timedelta

class Analytics:
    
    async def get_user_stats(self, user_id):
        """Get comprehensive user statistics"""
        stats = await db.get_user_analytics(user_id)
        
        # Add time-based stats
        accounts = await db.get_all_accounts(user_id)
        
        return {
            **stats,
            'total_accounts': len(accounts),
            'active_accounts': len([a for a in accounts if a['is_active']]),
        }
    
    async def get_recent_activity(self, user_id, days=7):
        """Get recent activity for user"""
        # This would query the analytics table
        # Implementation depends on specific needs
        pass

analytics = Analytics()
