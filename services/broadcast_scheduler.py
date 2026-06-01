from datetime import datetime, timedelta
from logger import setup_logger
from database.broadcast_service import (
    get_broadcast_by_id,
    update_broadcast_status,
    get_scheduled_broadcasts,
    update_broadcast_scheduled_time,
)
from database.models import BroadcastStatus
from services.broadcast_sender import send_broadcast_to_chats
from timezone_utils import MOSCOW_TZ
from pytz import UTC

logger = setup_logger(__name__)


def moscow_to_utc(moscow_dt: datetime) -> datetime:
    """Convert Moscow time to UTC for job queue."""
    if moscow_dt.tzinfo is None:
        moscow_dt = moscow_dt.replace(tzinfo=MOSCOW_TZ)
    return moscow_dt.astimezone(UTC).replace(tzinfo=None)


async def send_scheduled_broadcast_callback(context) -> None:
    """Callback for scheduled broadcast job."""
    broadcast_id = context.job.data.get("broadcast_id")
    if not broadcast_id:
        logger.error("Broadcast ID not found in job data")
        return

    try:
        broadcast = get_broadcast_by_id(broadcast_id)
        if not broadcast:
            logger.error(f"Broadcast {broadcast_id} not found")
            return

        if broadcast.status != BroadcastStatus.SCHEDULED:
            logger.warning(f"Broadcast {broadcast_id} is not in SCHEDULED status")
            return

        # Send broadcast
        await send_broadcast_to_chats(broadcast_id, context)

    except Exception as e:
        logger.error(f"Error sending scheduled broadcast {broadcast_id}: {e}")


def schedule_broadcast(broadcast_id: int, scheduled_time: datetime, job_queue) -> None:
    """Schedule a broadcast to be sent at a specific time.
    
    Args:
        scheduled_time: Naive datetime in UTC (already converted from Moscow time)
    """
    try:
        broadcast = get_broadcast_by_id(broadcast_id)
        if not broadcast:
            logger.error(f"Broadcast {broadcast_id} not found")
            return

        # scheduled_time is already UTC, use it directly
        # Schedule job
        job_queue.run_once(
            callback=send_scheduled_broadcast_callback,
            when=scheduled_time,
            data={"broadcast_id": broadcast_id},
            name=f"broadcast_{broadcast_id}",
        )

        logger.info(f"Broadcast {broadcast_id} scheduled for {scheduled_time} UTC")

    except Exception as e:
        logger.error(f"Error scheduling broadcast {broadcast_id}: {e}")
        raise


def cancel_scheduled_broadcast(broadcast_id: int, job_queue) -> bool:
    """Cancel a scheduled broadcast."""
    try:
        jobs = job_queue.get_jobs_by_name(f"broadcast_{broadcast_id}")
        if jobs:
            for job in jobs:
                job.schedule_removal()
            update_broadcast_status(broadcast_id, BroadcastStatus.CANCELLED)
            logger.info(f"Broadcast {broadcast_id} cancelled")
            return True
        else:
            logger.warning(f"No scheduled job found for broadcast {broadcast_id}")
            return False
    except Exception as e:
        logger.error(f"Error cancelling broadcast {broadcast_id}: {e}")
        return False


def reschedule_broadcast(
    broadcast_id: int, new_scheduled_time: datetime, job_queue
) -> bool:
    """Reschedule a broadcast."""
    try:
        # Cancel existing job
        cancel_scheduled_broadcast(broadcast_id, job_queue)

        # Create new schedule
        schedule_broadcast(broadcast_id, new_scheduled_time, job_queue)

        # Update broadcast scheduled_time
        update_broadcast_scheduled_time(broadcast_id, new_scheduled_time)

        logger.info(f"Broadcast {broadcast_id} rescheduled to {new_scheduled_time}")
        return True

    except Exception as e:
        logger.error(f"Error rescheduling broadcast {broadcast_id}: {e}")
        return False


async def restore_scheduled_jobs(context) -> None:
    """Restore scheduled broadcast jobs after bot restart."""
    try:
        from datetime import datetime
        
        scheduled_broadcasts = get_scheduled_broadcasts()
        
        if not scheduled_broadcasts:
            logger.info("No scheduled broadcasts to restore")
            return
        
        restored_count = 0
        skipped_count = 0
        
        for broadcast in scheduled_broadcasts:
            if not broadcast.scheduled_time:
                logger.warning(f"Broadcast {broadcast.id} has no scheduled_time, skipping")
                skipped_count += 1
                continue
            
            # Check if scheduled time is in the future
            # scheduled_time is naive UTC, so compare with UTC time
            now_utc = datetime.utcnow()
            if broadcast.scheduled_time <= now_utc:
                logger.warning(
                    f"Broadcast {broadcast.id} scheduled time {broadcast.scheduled_time} is in the past, "
                    f"sending immediately"
                )
                try:
                    await send_broadcast_to_chats(broadcast.id, context)
                    restored_count += 1
                except Exception as e:
                    logger.error(f"Error sending past-due broadcast {broadcast.id}: {e}")
                    skipped_count += 1
                continue
            
            # Restore the job
            try:
                schedule_broadcast(
                    broadcast.id, 
                    broadcast.scheduled_time, 
                    context.application.job_queue
                )
                restored_count += 1
                logger.info(
                    f"Restored scheduled broadcast {broadcast.id} for {broadcast.scheduled_time}"
                )
            except Exception as e:
                logger.error(f"Error restoring broadcast {broadcast.id}: {e}")
                skipped_count += 1
        
        logger.info(
            f"Job restoration complete: {restored_count} restored, {skipped_count} skipped"
        )
        
    except Exception as e:
        logger.error(f"Error during job restoration: {e}")
