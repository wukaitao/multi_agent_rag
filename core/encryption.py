from cryptography.fernet import Fernet
import base64
import os

class SecretManager:
    def __init__(self, key: str = None):
        self.key = key or os.getenv("ENCRYPTION_KEY")
        if not self.key:
            self.key = base64.urlsafe_b64encode(os.urandom(32)).decode()
        self.cipher = Fernet(self.key.encode())

    def encrypt(self, data: str) -> str:
        """加密敏感数据"""
        return self.cipher.encrypt(data.encode()).decode()
    
    def decrypt(self, encrypted: str) -> str:
        """解密敏感数据"""
        return self.cipher.decrypt(encrypted.encode()).decode()
    
# 使用示例
secret_mgr = SecretManager()
db_password_encrypted = secret_mgr.encrypt("my_database_password")
print(f"db_password_encrypted: {db_password_encrypted}")