from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from logger import setup_logger
from database.broadcast_service import (
    get_broadcast_by_id,
    get_incomplete_responses_without_reminder,
    get_incomplete_responses,
    get_all_broadcasts_with_responses,
    mark_reminder_sent,
)
from database.models import BroadcastType
from database.chat_service import get_chat_by_db_id
from timezone_utils import format_moscow

logger = setup_logger(__name__)


async def send_user_reminder_callback(context) -> None:
    """Callback wrapper for user reminder job."""
    broadcast_id = context.job.data.get("broadcast_id")
    if not broadcast_id:
        logger.error("Broadcast ID not found in job data")
        return
    await send_user_reminder(context, broadcast_id)


async def send_user_reminder(context, broadcast_id: int) -> None:
    """Send reminder to users who haven't completed survey (3 days after send)."""
    try:
        broadcast = get_broadcast_by_id(broadcast_id)
        if not broadcast or not broadcast.sent_at:
            logger.warning(f"Broadcast {broadcast_id} not found or not sent")
            return

        # Skip reminders for simple messages (only for surveys)
        if broadcast.broadcast_type == BroadcastType.MESSAGE:
            logger.info(f"Skipping reminder for broadcast {broadcast_id} (message type)")
            return

        # Get incomplete responses without reminders
        incomplete_responses = get_incomplete_responses_without_reminder(broadcast_id)

        sent_count = 0
        failed_count = 0

        for response in incomplete_responses:
            try:
                reminder_text = (
                    "Напоминание: у вас есть незавершенный опрос.\n\n"
                    "Пожалуйста, завершите его."
                )
                
                # Add button to continue survey
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "Продолжить опрос",
                        callback_data=f"start_survey_{response.id}"
                    )]
                ])

                await context.bot.send_message(
                    chat_id=response.user_tg_id,
                    text=reminder_text,
                    reply_markup=keyboard,
                )

                # Mark reminder as sent
                mark_reminder_sent(response.id)
                sent_count += 1

            except Exception as e:
                logger.warning(
                    f"Could not send reminder to user {response.user_tg_id}: {e}"
                )
                failed_count += 1

        logger.info(
            f"Reminders sent for broadcast {broadcast_id}: {sent_count} successful, {failed_count} failed"
        )

    except Exception as e:
        logger.error(f"Error sending user reminders for broadcast {broadcast_id}: {e}")


async def notify_curator_callback(context) -> None:
    """Callback wrapper for curator notification job."""
    broadcast_id = context.job.data.get("broadcast_id")
    if not broadcast_id:
        logger.error("Broadcast ID not found in job data")
        return
    await notify_curator(context, broadcast_id)


async def notify_curator(context, broadcast_id: int) -> None:
    """Notify curator about incomplete responses (3 days 2 hours after send)."""
    try:
        broadcast = get_broadcast_by_id(broadcast_id)
        if not broadcast or not broadcast.sent_at:
            logger.warning(f"Broadcast {broadcast_id} not found or not sent")
            return

        # Skip notifications for simple messages (only for surveys)
        if broadcast.broadcast_type == BroadcastType.MESSAGE:
            logger.info(f"Skipping curator notification for broadcast {broadcast_id} (message type)")
            return

        curator_tg_id = broadcast.curator_tg_id

        # Get incomplete responses
        incomplete_responses = get_incomplete_responses(broadcast_id)

        if not incomplete_responses:
            # All completed - send success message
            await context.bot.send_message(
                chat_id=curator_tg_id,
                text=f"✅ Все участники завершили опрос #{broadcast_id}.",
            )
            return

        # Build list of incomplete users
        from database.chat_service import get_active_chat_members
        
        incomplete_list = []
        for response in incomplete_responses:
            # Get chat and member info
            chat = get_chat_by_db_id(response.chat_id)
            if chat:
                # Get member info from active members
                members = get_active_chat_members(chat.chat_id, exclude_admins=False)
                member = next((m for m in members if m.user_tg_id == response.user_tg_id), None)

                if member:
                    username = member.username or f"ID: {member.user_tg_id}"
                    name = f"{member.first_name or ''} {member.last_name or ''}".strip()
                    display = f"@{username}" if member.username else f"ID {member.user_tg_id}"
                    if name:
                        display = f"{name} ({display})"
                    incomplete_list.append(display)
                else:
                    incomplete_list.append(f"ID: {response.user_tg_id}")

        # Build notification message
        notification = (
            f"📊 Статистика по опросу #{broadcast_id}\n\n"
            f"⏰ Отправлен: {format_moscow(broadcast.sent_at)}\n\n"
            f"❌ Не завершили опрос: {len(incomplete_responses)} чел.\n\n"
        )

        # Add user list (truncate if too long)
        if len(incomplete_list) <= 20:
            notification += "Список:\n"
            for user_info in incomplete_list:
                notification += f"• {user_info}\n"
        else:
            notification += f"Первые 20 из {len(incomplete_list)}:\n"
            for user_info in incomplete_list[:20]:
                notification += f"• {user_info}\n"
            notification += f"\n... и еще {len(incomplete_list) - 20} чел."

        await context.bot.send_message(
            chat_id=curator_tg_id,
            text=notification,
        )

        logger.info(
            f"Curator {curator_tg_id} notified about {len(incomplete_responses)} incomplete responses"
        )

    except Exception as e:
        logger.error(f"Error notifying curator for broadcast {broadcast_id}: {e}")


def schedule_reminders(broadcast_id: int, sent_at: datetime, job_queue) -> None:
    """Schedule reminder jobs for a broadcast."""
    try:
        # Schedule user reminder: 3 days after send
        user_reminder_time = sent_at + timedelta(days=3)
        job_queue.run_once(
            callback=send_user_reminder_callback,
            when=user_reminder_time,
            data={"broadcast_id": broadcast_id},
            name=f"broadcast_reminder_{broadcast_id}",
        )

        # Schedule curator notification: 3 days 2 hours after send
        curator_notification_time = sent_at + timedelta(days=3, hours=2)
        job_queue.run_once(
            callback=notify_curator_callback,
            when=curator_notification_time,
            data={"broadcast_id": broadcast_id},
            name=f"broadcast_curator_notify_{broadcast_id}",
        )

        logger.info(
            f"Reminders scheduled for broadcast {broadcast_id}: "
            f"users at {user_reminder_time}, curator at {curator_notification_time}"
        )

    except Exception as e:
        logger.error(f"Error scheduling reminders for broadcast {broadcast_id}: {e}")


async def restore_reminder_jobs(context) -> None:
    """Restore reminder jobs for sent broadcasts after bot restart."""
    try:
        # Get all broadcasts that have been sent
        broadcasts = get_all_broadcasts_with_responses()
        
        if not broadcasts:
            logger.info("No broadcasts to restore reminders for")
            return
        
        restored_user_reminders = 0
        restored_curator_notifications = 0
        skipped_count = 0
        
        now = datetime.utcnow()
        
        for broadcast in broadcasts:
            # Skip if not sent or no sent_at timestamp
            if not broadcast.sent_at:
                continue
            
            # Skip if not a survey (only surveys get reminders)
            if broadcast.broadcast_type != BroadcastType.SURVEY:
                continue

            # Skip if all responses are already completed
            if not get_incomplete_responses(broadcast.id):
                continue

            # Calculate reminder times
            user_reminder_time = broadcast.sent_at + timedelta(days=3)
            curator_notification_time = broadcast.sent_at + timedelta(days=3, hours=2)
            
            # Restore user reminder if it's in the future
            if user_reminder_time > now:
                try:
                    context.application.job_queue.run_once(
                        callback=send_user_reminder_callback,
                        when=user_reminder_time,
                        data={"broadcast_id": broadcast.id},
                        name=f"broadcast_reminder_{broadcast.id}",
                    )
                    restored_user_reminders += 1
                    logger.info(
                        f"Restored user reminder for broadcast {broadcast.id} at {user_reminder_time}"
                    )
                except Exception as e:
                    logger.error(f"Error restoring user reminder for broadcast {broadcast.id}: {e}")
                    skipped_count += 1
            
            # Restore curator notification if it's in the future
            if curator_notification_time > now:
                try:
                    context.application.job_queue.run_once(
                        callback=notify_curator_callback,
                        when=curator_notification_time,
                        data={"broadcast_id": broadcast.id},
                        name=f"broadcast_curator_notify_{broadcast.id}",
                    )
                    restored_curator_notifications += 1
                    logger.info(
                        f"Restored curator notification for broadcast {broadcast.id} at {curator_notification_time}"
                    )
                except Exception as e:
                    logger.error(f"Error restoring curator notification for broadcast {broadcast.id}: {e}")
                    skipped_count += 1
        
        logger.info(
            f"Reminder restoration complete: {restored_user_reminders} user reminders, "
            f"{restored_curator_notifications} curator notifications restored, {skipped_count} skipped"
        )
        
    except Exception as e:
        logger.error(f"Error during reminder restoration: {e}")
