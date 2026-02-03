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
    
    async def get_access_token(self) -> str:
        # Быстрая проверка без блокировки
        try:
            token = self._token_manager._storage.get_access_token()
            if token and not self._token_manager._is_expire(token):
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
                    logger.debug("Token was refreshed by another coroutine")
                    return token
            except Exception as e:
                logger.warning(f"Failed to check token (locked path): {e}")
            
            # Обновляем токен (только одна корутина делает это)
            logger.info("Refreshing access token...")
            token = self._token_manager.get_access_token()
            logger.info("Access token refreshed successfully")
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
