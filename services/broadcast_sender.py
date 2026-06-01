import asyncio
from datetime import datetime
from logger import setup_logger
from database.broadcast_service import (
    get_broadcast_by_id,
    get_broadcast_chats,
    update_broadcast_status,
    create_survey_response,
)
from database.chat_service import (
    get_chat_by_telegram_id,
    get_active_chat_members,
    deactivate_chat_member,
    update_chat_member_admin_status,
    get_all_chat_members,
    get_chat_by_db_id,
)
from database.models import BroadcastStatus, BroadcastType
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest
from messages import SURVEY_INTRODUCTION

logger = setup_logger(__name__)


async def refresh_admin_status_for_chat(chat_id: int, context) -> None:
    """Refresh admin status for all members in a chat."""
    try:
        administrators = await context.bot.get_chat_administrators(chat_id)
        admin_ids = {admin.user.id for admin in administrators}

        # Update all members' admin status
        chat = get_chat_by_telegram_id(chat_id)
        if not chat:
            return

        members = get_all_chat_members(chat.id)
        for member in members:
            is_admin = member.user_tg_id in admin_ids
            if member.is_admin != is_admin:
                update_chat_member_admin_status(chat_id, member.user_tg_id, is_admin)

    except Exception as e:
        logger.warning(f"Error refreshing admin status for chat {chat_id}: {e}")


async def reconcile_chat_members(telegram_chat_id: int, context) -> None:
    """Call getChatMember for every active DB member and deactivate any who have left."""
    members = get_active_chat_members(telegram_chat_id, exclude_admins=False)

    for member in members:
        try:
            result = await context.bot.get_chat_member(telegram_chat_id, member.user_tg_id)
            status = result.status

            if status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
                deactivate_chat_member(telegram_chat_id, member.user_tg_id)
                logger.info(
                    f"Reconciled: deactivated member {member.user_tg_id} in chat {telegram_chat_id}"
                )
            else:
                is_admin = status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
                if member.is_admin != is_admin:
                    update_chat_member_admin_status(telegram_chat_id, member.user_tg_id, is_admin)

        except BadRequest as e:
            msg = str(e).lower()
            if "user not found" in msg or "participant not found" in msg or "member not found" in msg:
                deactivate_chat_member(telegram_chat_id, member.user_tg_id)
                logger.info(
                    f"Reconciled: deactivated missing member {member.user_tg_id} in chat {telegram_chat_id}"
                )
            else:
                logger.warning(
                    f"Could not reconcile member {member.user_tg_id} in chat {telegram_chat_id}: {e}"
                )
        except Exception as e:
            logger.warning(
                f"Could not reconcile member {member.user_tg_id} in chat {telegram_chat_id}: {e}"
            )

        await asyncio.sleep(0.05)


async def send_broadcast_to_chats(broadcast_id: int, context) -> dict[str, int]:
    """Send broadcast to all members of target chats."""
    broadcast = get_broadcast_by_id(broadcast_id)
    if not broadcast:
        logger.error(f"Broadcast {broadcast_id} not found")
        return {"sent": 0, "failed": 0}

    # Update status to SENDING
    update_broadcast_status(broadcast_id, BroadcastStatus.SENDING)

    broadcast_chats = get_broadcast_chats(broadcast_id)
    stats = {"sent": 0, "failed": 0}

    for broadcast_chat in broadcast_chats:
        chat_db_id = broadcast_chat.chat_id  # This is the database chat.id

        chat = get_chat_by_db_id(chat_db_id)
        if not chat:
            logger.warning(f"Chat {chat_db_id} not found")
            continue

        telegram_chat_id = chat.chat_id

        try:
            # Refresh admin status before sending
            await refresh_admin_status_for_chat(telegram_chat_id, context)

            # Verify each member is still in the chat
            await reconcile_chat_members(telegram_chat_id, context)

            # Get active non-admin members
            members = get_active_chat_members(telegram_chat_id, exclude_admins=True)

            for member in members:
                try:
                    # Check broadcast type and send appropriate content
                    if broadcast.broadcast_type == BroadcastType.MESSAGE:
                        # Send simple message (no response tracking)
                        try:
                            await context.bot.send_message(
                                chat_id=member.user_tg_id,
                                text=broadcast.message_content,
                            )
                            stats["sent"] += 1

                        except Exception as e:
                            logger.warning(
                                f"Could not send message to user {member.user_tg_id}: {e}"
                            )
                            stats["failed"] += 1

                    else:  # BroadcastType.SURVEY
                        # Create survey response record first
                        response = create_survey_response(
                            broadcast_id, chat_db_id, member.user_tg_id
                        )

                        # Send DM with survey start button
                        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                        keyboard = InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "Начать опрос",
                                        callback_data=f"start_survey_{response.id}",
                                    )
                                ]
                            ]
                        )

                        try:
                            await context.bot.send_message(
                                chat_id=member.user_tg_id,
                                text=SURVEY_INTRODUCTION,
                                reply_markup=keyboard,
                            )
                            stats["sent"] += 1

                        except Exception as e:
                            logger.warning(
                                f"Could not send survey to user {member.user_tg_id}: {e}"
                            )
                            stats["failed"] += 1

                except Exception as e:
                    logger.error(
                        f"Error processing member {member.user_tg_id} for broadcast {broadcast_id}: {e}"
                    )
                    stats["failed"] += 1

        except Exception as e:
            logger.error(f"Error sending broadcast to chat {telegram_chat_id}: {e}")
            stats["failed"] += 1

    # Update status to SENT
    broadcast = update_broadcast_status(broadcast_id, BroadcastStatus.SENT)

    # Schedule reminders (only for surveys, not for simple messages)
    if (
        broadcast
        and broadcast.sent_at
        and broadcast.broadcast_type == BroadcastType.SURVEY
    ):
        from services.broadcast_reminders import schedule_reminders

        schedule_reminders(
            broadcast_id, broadcast.sent_at, context.application.job_queue
        )

    logger.info(
        f"Broadcast {broadcast_id} sent: {stats['sent']} successful, {stats['failed']} failed"
    )

    return stats
