from pathlib import Path

HOST = "127.0.0.1"
PORT = 5555
BUFFER_SIZE = 4096

HKDF_INFO = b"e2ee-message-encryption"
KEY_LENGTH = 32
NONCE_LENGTH = 12

PROFILES_DIR = Path(__file__).resolve().parent / "profiles"
SALT_LENGTH = 16
PBKDF2_ITERATIONS = 600_000