import os

from pwdlib import PasswordHash

os.environ["JWT_SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"
os.environ["AUTH_USERNAME"] = "alice"
os.environ["AUTH_PASSWORD_HASH"] = PasswordHash.recommended().hash("wonderland")
