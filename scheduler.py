from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
from database import db
from messaging import message_sender
import pytz

class SchedulerManager:
    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=pytz.UTC)
        self.scheduler.start()
        self.is_running = False
    
    async def check_and_send_scheduled(self):
        """Check for due scheduled messages and send INSTANTLY"""
        try:
            due_schedules = await db.get_due_schedules()
            
            for schedule in due_schedules:
                # Send message INSTANTLY (no delay)
                result = await message_sender.send_message(
                    schedule['user_id'],
                    schedule['target'],
                    schedule['message'],
                    schedule['account_id']
                )
                
                if result['success']:
                    if not schedule['is_recurring']:
                        await db.mark_schedule_sent(schedule['id'])
                    else:
                        # Reschedule for next occurrence
                        next_time = self._calculate_next_run(schedule['recurring_pattern'])
                        await db.execute(
                            'UPDATE scheduled_messages SET schedule_time = ? WHERE id = ?',
                            (next_time, schedule['id'])
                        )
                    
                    await db.log_action(
                        schedule['user_id'],
                        'scheduled_message_sent',
                        {'target': schedule['target'], 'schedule_id': schedule['id']}
                    )
        
        except Exception as e:
            print(f"Scheduler error: {e}")
    
    def start_scheduler_job(self):
        """Start the scheduler check job (runs every SECOND for instant execution)"""
        if not self.is_running:
            self.scheduler.add_job(
                self.check_and_send_scheduled,
                'interval',
                seconds=1,  # Check every second for INSTANT execution
                id='check_schedules',
                replace_existing=True
            )
            self.is_running = True
            print("✅ Scheduler started - checking every second")
    
    def stop_scheduler_job(self):
        """Stop scheduler"""
        if self.is_running:
            self.scheduler.remove_job('check_schedules')
            self.is_running = False
            print("⏸️ Scheduler stopped")
    
    async def add_time_schedule(self, user_id, account_id, target, message, time_str):
        """
        Add schedule with HH:MM:SS format (executes TODAY or TOMORROW)
        
        Args:
            time_str: Format "HH:MM:SS" or "HH:MM" (seconds default to 00)
        """
        try:
            # Parse time
            time_parts = time_str.split(':')
            hour = int(time_parts[0])
            minute = int(time_parts[1])
            second = int(time_parts[2]) if len(time_parts) > 2 else 0
            
            # Get current time
            now = datetime.now(pytz.UTC)
            
            # Create schedule time for today
            schedule_time = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
            
            # If time has passed today, schedule for tomorrow
            if schedule_time <= now:
                schedule_time += timedelta(days=1)
            
            schedule_id = await db.add_scheduled_message(
                user_id, account_id, target, message, schedule_time, False, None
            )
            
            return {
                'success': True,
                'schedule_id': schedule_id,
                'scheduled_for': schedule_time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def add_instant_schedule(self, user_id, account_id, target, message, delay_seconds=0):
        """
        Add INSTANT schedule (executes in X seconds, default 0 = NOW)
        """
        now = datetime.now(pytz.UTC)
        schedule_time = now + timedelta(seconds=delay_seconds)
        
        schedule_id = await db.add_scheduled_message(
            user_id, account_id, target, message, schedule_time, False, None
        )
        
        return {
            'success': True,
            'schedule_id': schedule_id,
            'scheduled_for': schedule_time.strftime('%Y-%m-%d %H:%M:%S'),
            'executes_in': f'{delay_seconds} seconds'
        }
    
    async def add_recurring_schedule(self, user_id, account_id, target, message, pattern):
        """
        Add recurring schedule
        Patterns: "hourly", "daily:HH:MM", "every:X:minutes"
        """
        first_run = self._calculate_next_run(pattern)
        
        schedule_id = await db.add_scheduled_message(
            user_id, account_id, target, message, first_run, True, pattern
        )
        
        return {
            'success': True,
            'schedule_id': schedule_id,
            'first_run': first_run.strftime('%Y-%m-%d %H:%M:%S'),
            'pattern': pattern
        }
    
    def _calculate_next_run(self, pattern):
        """Calculate next run time based on pattern"""
        now = datetime.now(pytz.UTC)
        
        if pattern == "hourly":
            return now + timedelta(hours=1)
        
        elif pattern.startswith("daily:"):
            time_part = pattern.split(":", 1)[1]
            time_parts = time_part.split(":")
            hour = int(time_parts[0])
            minute = int(time_parts[1])
            
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            return next_run
        
        elif pattern.startswith("every:"):
            parts = pattern.split(":")
            interval = int(parts[1])
            unit = parts[2]  # minutes, hours, etc.
            
            if unit == "minutes":
                return now + timedelta(minutes=interval)
            elif unit == "hours":
                return now + timedelta(hours=interval)
        
        return now + timedelta(hours=1)  # Default

scheduler_manager = SchedulerManager()
