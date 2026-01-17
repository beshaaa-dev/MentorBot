import asyncio
from pathlib import Path
from typing import Optional, Dict, Tuple, Any
from telegram.ext import PicklePersistence, PersistenceInput, ContextTypes
from telegram.ext._utils.types import CDCData, UD, CD, BD, ConversationDict
from logger import setup_logger

logger = setup_logger(__name__)


class ThreadSafePicklePersistence(PicklePersistence[UD, CD, BD]):
    """
    Thread-safe version of PicklePersistence using asyncio.Lock.
    
    Extends PicklePersistence to add proper synchronization for concurrent_updates mode.
    All file I/O operations are protected by an async lock to prevent race conditions.
    """

    def __init__(
        self,
        filepath: str | Path,
        store_data: Optional[PersistenceInput] = None,
        single_file: bool = True,
        on_flush: bool = False,
        update_interval: float = 60,
        context_types: Optional[ContextTypes[Any, UD, CD, BD]] = None,
    ):
        super().__init__(
            filepath=filepath,
            store_data=store_data,
            single_file=single_file,
            on_flush=on_flush,
            update_interval=update_interval,
            context_types=context_types,
        )
        # Async lock for thread-safe operations
        self._lock = asyncio.Lock()
        logger.info(f"ThreadSafePicklePersistence initialized with filepath: {filepath}")

    async def get_user_data(self) -> Dict[int, UD]:
        """Thread-safe get_user_data."""
        async with self._lock:
            return await super().get_user_data()

    async def get_chat_data(self) -> Dict[int, CD]:
        """Thread-safe get_chat_data."""
        async with self._lock:
            return await super().get_chat_data()

    async def get_bot_data(self) -> BD:
        """Thread-safe get_bot_data."""
        async with self._lock:
            return await super().get_bot_data()

    async def get_callback_data(self) -> Optional[CDCData]:
        """Thread-safe get_callback_data."""
        async with self._lock:
            return await super().get_callback_data()

    async def get_conversations(self, name: str) -> ConversationDict:
        """Thread-safe get_conversations."""
        async with self._lock:
            return await super().get_conversations(name)

    async def update_user_data(self, user_id: int, data: UD) -> None:
        """Thread-safe update_user_data."""
        async with self._lock:
            await super().update_user_data(user_id, data)

    async def update_chat_data(self, chat_id: int, data: CD) -> None:
        """Thread-safe update_chat_data."""
        async with self._lock:
            await super().update_chat_data(chat_id, data)

    async def update_bot_data(self, data: BD) -> None:
        """Thread-safe update_bot_data."""
        async with self._lock:
            await super().update_bot_data(data)

    async def update_callback_data(self, data: CDCData) -> None:
        """Thread-safe update_callback_data."""
        async with self._lock:
            await super().update_callback_data(data)

    async def update_conversation(
        self, name: str, key: Tuple[int, ...], new_state: Optional[object]
    ) -> None:
        """Thread-safe update_conversation."""
        async with self._lock:
            await super().update_conversation(name, key, new_state)

    async def drop_user_data(self, user_id: int) -> None:
        """Thread-safe drop_user_data."""
        async with self._lock:
            await super().drop_user_data(user_id)

    async def drop_chat_data(self, chat_id: int) -> None:
        """Thread-safe drop_chat_data."""
        async with self._lock:
            await super().drop_chat_data(chat_id)

    async def flush(self) -> None:
        """Thread-safe flush."""
        async with self._lock:
            await super().flush()
            logger.info("Persistence data flushed to disk")
