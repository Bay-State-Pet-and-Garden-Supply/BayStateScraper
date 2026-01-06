from __future__ import annotations

import base64
import logging
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

class EncryptionManager:
    """
    Manages encryption and decryption of sensitive data using Fernet (symmetric encryption).
    Uses a master key from environment variables to derive the encryption key.
    """

    def __init__(self, master_key: str | None = None):
        """
        Initialize with a master key.
        If not provided, tries to load SETTINGS_ENCRYPTION_KEY from env.
        """
        self._key = master_key or os.getenv("SETTINGS_ENCRYPTION_KEY")
        self._fernet: Fernet | None = None
        
        if self._key:
            try:
                # Ensure key is valid base64 url-safe, or derive one if it's a raw passphrase
                # For simplicity, we assume the user provides a valid 32 url-safe base64 key
                # OR we derive it if it doesn't look like one.
                # Common issue: User provides a simple string password.
                
                # Try initializing Fernet directly to see if it's already a valid key
                try:
                    self._fernet = Fernet(self._key)
                except Exception:
                    # If it fails, treat it as a passphrase and derive a key
                    # NOTE: We need a salt. ideally stored. 
                    # For simple single-deployment setup without salt storage, 
                    # we might use a static salt or hash the key itself. 
                    # Ideally, we ask the user to generate a proper key.
                    # Let's fallback to generating a key from the passphrase with a static salt
                    # to ensure determinism across restarts (since we don't store salt yet).
                    # WARNING: Static salt reduces security against rainbow tables but allows stateless restart.
                    salt = b"bayes_state_tools_static_salt" 
                    kdf = PBKDF2HMAC(
                        algorithm=hashes.SHA256(),
                        length=32,
                        salt=salt,
                        iterations=480000,
                    )
                    key = base64.urlsafe_b64encode(kdf.derive(self._key.encode()))
                    self._fernet = Fernet(key)
                    
                logger.info("EncryptionManager initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize EncryptionManager: {e}")
                self._fernet = None
        else:
            logger.warning("No encryption key provided. Encryption will be disabled.")

    def encrypt(self, plain_text: str) -> str | None:
        """Encrypt a string value."""
        if not self._fernet:
            logger.error("Cannot encrypt: Encryption not initialized.")
            return None
        
        try:
            return self._fernet.encrypt(plain_text.encode()).decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            return None

    def decrypt(self, date_text: str) -> str | None:
        """Decrypt a string value."""
        if not self._fernet:
            logger.error("Cannot decrypt: Encryption not initialized.")
            return None
            
        try:
            return self._fernet.decrypt(date_text.encode()).decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return None

# Global instance
encryption_manager = EncryptionManager()
