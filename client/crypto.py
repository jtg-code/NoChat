import base64
import os
from dataclasses import dataclass
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from config import HKDF_INFO, KEY_LENGTH, NONCE_LENGTH, PBKDF2_ITERATIONS


@dataclass(frozen=True)
class KeyPair:
    private_key: x25519.X25519PrivateKey
    public_key: x25519.X25519PublicKey

    @property
    def public_b64(self) -> str:
        return b64_encode(serialize_public_key(self.public_key))


@dataclass(frozen=True)
class EncryptedPackage:
    sender_public_key: bytes
    nonce: bytes
    ciphertext: bytes

    def to_b64_dict(self) -> dict[str, str]:
        return {
            "sender_public_key": b64_encode(self.sender_public_key),
            "nonce": b64_encode(self.nonce),
            "ciphertext": b64_encode(self.ciphertext),
        }

    @classmethod
    def from_b64_dict(cls, data: dict[str, str]) -> "EncryptedPackage":
        return cls(
            sender_public_key=b64_decode(data["sender_public_key"]),
            nonce=b64_decode(data["nonce"]),
            ciphertext=b64_decode(data["ciphertext"]),
        )


def b64_encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64_decode(text: str) -> bytes:
    return base64.b64decode(text.strip(), validate=True)


def generate_keypair() -> KeyPair:
    private_key = x25519.X25519PrivateKey.generate()
    return KeyPair(private_key=private_key, public_key=private_key.public_key())


def serialize_public_key(public_key: x25519.X25519PublicKey) -> bytes:
    return public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def deserialize_public_key(data: bytes) -> x25519.X25519PublicKey:
    return x25519.X25519PublicKey.from_public_bytes(data)


def serialize_private_key(private_key: x25519.X25519PrivateKey) -> bytes:
    return private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )


def keypair_from_private_b64(private_b64: str) -> KeyPair:
    raw = b64_decode(private_b64)
    if len(raw) != KEY_LENGTH:
        raise ValueError(f"Ein X25519 Private Key muss genau {KEY_LENGTH} Bytes lang sein.")
    private_key = x25519.X25519PrivateKey.from_private_bytes(raw)
    return KeyPair(private_key=private_key, public_key=private_key.public_key())


def derive_key_from_password(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt_bytes(key: bytes, plaintext: bytes, associated_data: bytes | None = None) -> tuple[bytes, bytes]:
    nonce = os.urandom(NONCE_LENGTH)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data)
    return nonce, ciphertext


def decrypt_bytes(
    key: bytes,
    nonce: bytes,
    ciphertext: bytes,
    associated_data: bytes | None = None,
) -> bytes:
    return AESGCM(key).decrypt(nonce, ciphertext, associated_data)


def parse_public_key_b64(key_b64: str) -> x25519.X25519PublicKey:
    raw = b64_decode(key_b64)
    if len(raw) != KEY_LENGTH:
        raise ValueError(f"Ein X25519 Public Key muss genau {KEY_LENGTH} Bytes lang sein.")
    return deserialize_public_key(raw)


def derive_shared_aes_key(
    own_private_key: x25519.X25519PrivateKey,
    peer_public_key: x25519.X25519PublicKey,
) -> bytes:
    shared_secret = own_private_key.exchange(peer_public_key)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=None,
        info=HKDF_INFO,
    ).derive(shared_secret)


def encrypt_message(
    sender_private_key: x25519.X25519PrivateKey,
    recipient_public_key: x25519.X25519PublicKey,
    plaintext: str,
) -> EncryptedPackage:
    aes_key = derive_shared_aes_key(sender_private_key, recipient_public_key)
    nonce = os.urandom(NONCE_LENGTH)
    ciphertext = AESGCM(aes_key).encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)

    return EncryptedPackage(
        sender_public_key=serialize_public_key(sender_private_key.public_key()),
        nonce=nonce,
        ciphertext=ciphertext,
    )


def decrypt_message(
    recipient_private_key: x25519.X25519PrivateKey,
    package: EncryptedPackage,
) -> str:
    sender_public_key = deserialize_public_key(package.sender_public_key)
    aes_key = derive_shared_aes_key(recipient_private_key, sender_public_key)
    plaintext_bytes = AESGCM(aes_key).decrypt(
        package.nonce,
        package.ciphertext,
        associated_data=None,
    )
    return plaintext_bytes.decode("utf-8")