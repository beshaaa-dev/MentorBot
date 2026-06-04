import asyncio
from typing import Optional
from amocrm.v2 import tokens
from logger import setup_logger

logger = setup_logger(__name__)


class ThreadSafeTokenManager:
    """
    Thread-safe синглтон обертка для amocrm TokenManager.
    """
    
    _instance: Optional['ThreadSafeTokenManager'] = None
    
    def __new__(cls, token_manager: Optional[tokens.TokenManager] = None):
        """
        Create or return singleton instance.
        
        Thread-safe thanks to Python's GIL protecting __new__ execution.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, token_manager: Optional[tokens.TokenManager] = None):
        """
        Initialize singleton instance (only runs once).
        
        The _initialized flag prevents re-initialization even if __init__ 
        is called multiple times on the same instance.
        """
        # Быстрая проверка - уже инициализирован?
        if hasattr(self, '_initialized'):
            return
        
        if token_manager is None:
            raise ValueError("token_manager required for first initialization")
        
        self._token_manager = token_manager
        self._lock = asyncio.Lock()
        self._initialized = True
    
    @staticmethod
    def _mask_token(token: str | None) -> str:
        if not token:
            return "(empty)"
        if len(token) <= 12:
            return token[:4] + "***"
        return f"{token[:8]}...{token[-4:]}"

    def _force_refresh_token(self) -> str:
        """
        Принудительно обновляет access token через refresh token.

        Returns:
            Новый access token

        Raises:
            Exception: Если обновление не удалось
        """
        logger.info("Force refreshing access token...")

        # Получаем новые токены (access_token, refresh_token)
        access_token, refresh_token = self._token_manager._get_new_tokens()

        # Сохраняем новые токены
        self._token_manager._storage.save_tokens(access_token, refresh_token)

        logger.info(
            f"Access token force refreshed: {self._mask_token(access_token)}"
        )
        return access_token

    async def get_access_token(self) -> str:
        # Быстрая проверка без блокировки
        try:
            token = self._token_manager._storage.get_access_token()
            if token and not self._token_manager._is_expire(token):
                logger.debug(f"Token valid (fast path): {self._mask_token(token)}")
                return token
        except Exception as e:
            logger.warning(f"Failed to check token (fast path): {e}")

        # Токен истёк или отсутствует - нужна блокировка
        async with self._lock:
            # Двойная проверка после получения блокировки
            # (другая корутина могла уже обновить токен)
            try:
                token = self._token_manager._storage.get_access_token()
                if token and not self._token_manager._is_expire(token):
                    logger.debug(
                        f"Token was refreshed by another coroutine: {self._mask_token(token)}"
                    )
                    return token
            except Exception as e:
                logger.warning(f"Failed to check token (locked path): {e}")

            # Обновляем токен (только одна корутина делает это)
            logger.info("Refreshing access token...")
            token = self._token_manager.get_access_token()
            logger.info(f"Access token refreshed: {self._mask_token(token)}")
            return token

    async def force_refresh_access_token(self) -> str:
        """Принудительно обновляет access token, даже если текущий токен ещё не истёк."""
        async with self._lock:
            try:
                return self._force_refresh_token()
            except Exception as e:
                logger.error(f"Force refresh failed: {e}, falling back to standard refresh")
                # Если принудительное обновление не удалось, используем стандартный метод
                token = self._token_manager.get_access_token()
                logger.info(
                    f"Access token refreshed (fallback): {self._mask_token(token)}"
                )
                return token
    
    def init(self, code: str, skip_error: bool = False):
        return self._token_manager.init(code=code, skip_error=skip_error)
    
    @property
    def subdomain(self) -> Optional[str]:
        return self._token_manager.subdomain
    
    @classmethod
    def get_instance(cls) -> 'ThreadSafeTokenManager':
        if cls._instance is None:
            raise RuntimeError(
                "ThreadSafeTokenManager not initialized. "
                "Call ThreadSafeTokenManager(token_manager) first."
            )
        return cls._instance
