from dataclasses import dataclass
from cryptography.hazmat.primitives.asymmetric import x25519

from crypto import KeyPair, parse_public_key_b64
from profile import Profile


@dataclass
class ChatSession:
    profile: Profile
    recipient_b64: str | None = None
    recipient_key: x25519.X25519PublicKey | None = None
    running: bool = True

    def __post_init__(self) -> None:
        if self.profile.last_recipient_b64:
            try:
                self.recipient_key = parse_public_key_b64(self.profile.last_recipient_b64)
                self.recipient_b64 = self.profile.last_recipient_b64
            except Exception:
                self.profile.set_last_recipient(None)

    @property
    def keypair(self) -> KeyPair:
        return self.profile.keypair

    def set_recipient(self, name_or_key: str, persist: bool = True) -> str | None:
        key_b64, contact_name = self.profile.resolve_recipient(name_or_key)
        self.recipient_key = parse_public_key_b64(key_b64)
        self.recipient_b64 = key_b64
        if persist:
            self.profile.set_last_recipient(key_b64)
        return contact_name

    @property
    def has_recipient(self) -> bool:
        return self.recipient_key is not None and self.recipient_b64 is not None