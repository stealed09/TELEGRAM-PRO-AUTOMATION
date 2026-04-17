from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta
from database import db
from messaging import message_sender
import pytz

class SchedulerManager:
    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=pytz.UTC)
        self.scheduler.start()
    
    async def check_and_send_scheduled(self):
        """Check for due scheduled messages and send them"""
        try:
            due_schedules = await db.get_due_schedules()
            
            for schedule in due_schedules:
                # Send message
                result = await message_sender.send_message(
                    schedule['user_id'],
                    schedule['target'],
                    schedule['message'],
                    schedule['account_id']
                )
                
                if result['success']:
                    # Mark as sent if not recurring
                    if not schedule['is_recurring']:
                        await db.mark_schedule_sent(schedule['id'])
                    else:
                        # Update next schedule time based on pattern
                        # TODO: Implement recurring logic
                        pass
                    
                    # Log action
                    await db.log_action(
                        schedule['user_id'],
                        'scheduled_message_sent',
                        {'target': schedule['target'], 'schedule_id': schedule['id']}
                    )
        
        except Exception as e:
            print(f"Scheduler error: {e}")
    
    def start_scheduler_job(self):
        """Start the scheduler check job (runs every minute)"""
        self.scheduler.add_job(
            self.check_and_send_scheduled,
            'interval',
            minutes=1,
            id='check_schedules'
        )
    
    async def add_one_time_schedule(self, user_id, account_id, target, message, schedule_time):
        """Add one-time scheduled message"""
        schedule_id = await db.add_scheduled_message(
            user_id, account_id, target, message, schedule_time, False, None
        )
        return schedule_id
    
    async def add_recurring_schedule(self, user_id, account_id, target, message, pattern):
        """Add recurring scheduled message"""
        # Pattern examples: "daily:14:30", "hourly", "weekly:monday:10:00"
        # Calculate first run time
        first_run = self._calculate_next_run(pattern)
        
        schedule_id = await db.add_scheduled_message(
            user_id, account_id, target, message, first_run, True, pattern
        )
        return schedule_id
    
    def _calculate_next_run(self, pattern):
        """Calculate next run time based on pattern"""
        now = datetime.now(pytz.UTC)
        
        if pattern.startswith("hourly"):
            return now + timedelta(hours=1)
        elif pattern.startswith("daily"):
            parts = pattern.split(":")
            if len(parts) == 3:
                hour = int(parts[1])
                minute = int(parts[2])
                next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)
                return next_run
        
        return now + timedelta(hours=1)  # Default

scheduler_manager = SchedulerManager()
