from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re

from cryptography.exceptions import InvalidTag

from config import PROFILES_DIR, SALT_LENGTH
from crypto import (
    KeyPair,
    b64_decode,
    b64_encode,
    decrypt_bytes,
    derive_key_from_password,
    encrypt_bytes,
    generate_keypair,
    keypair_from_private_b64,
    parse_public_key_b64,
    serialize_private_key,
)

PROFILE_VERSION = 1


@dataclass(frozen=True)
class ProfileSummary:
    name: str
    path: Path


@dataclass
class Profile:
    name: str
    keypair: KeyPair
    file_path: Path
    salt: bytes
    storage_key: bytes
    contacts: dict[str, str] = field(default_factory=dict)
    last_recipient_b64: str | None = None

    def add_contact(self, contact_name: str, public_key_b64: str) -> str:
        """Validiert den Public Key und speichert den Kontakt im Profil."""
        clean_name = contact_name.strip()
        if not clean_name:
            raise ValueError("Kontaktname darf nicht leer sein.")
        parse_public_key_b64(public_key_b64)
        clean_key = public_key_b64.strip()
        self.contacts[clean_name] = clean_key
        save_profile(self)
        return clean_key

    def remove_contact(self, contact_name: str) -> bool:
        """Entfernt einen Kontakt anhand seines Namens."""
        matched = self._find_contact_key_name(contact_name)
        if matched is None:
            return False
        del self.contacts[matched]
        save_profile(self)
        return True

    def contact_name_for_key(self, public_key_b64: str) -> str | None:
        """Sucht den Kontaktnamen zu einem Public Key."""
        clean_key = public_key_b64.strip()
        for name, stored_key in self.contacts.items():
            if stored_key == clean_key:
                return name
        return None

    def resolve_recipient(self, name_or_key: str) -> tuple[str, str | None]:
        """Löst einen Kontaktnamen oder Public Key auf und gibt (key_b64, contact_name) zurück."""
        query = name_or_key.strip()
        matched_name = self._find_contact_key_name(query)
        if matched_name is not None:
            return self.contacts[matched_name], matched_name

        parse_public_key_b64(query)
        return query, self.contact_name_for_key(query)

    def set_last_recipient(self, recipient_b64: str | None) -> None:
        """Speichert den zuletzt verwendeten Empfänger im Profil."""
        self.last_recipient_b64 = recipient_b64
        save_profile(self)

    def _find_contact_key_name(self, query: str) -> str | None:
        clean = query.strip()
        if clean in self.contacts:
            return clean
        lowered = clean.lower()
        for name in self.contacts:
            if name.lower() == lowered:
                return name
        return None


def sanitize_profile_filename(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip()).strip("_")
    return slug or "profile"


def list_profiles(profiles_dir: Path = PROFILES_DIR) -> list[ProfileSummary]:
    """Listet alle gespeicherten Profile im Profil-Verzeichnis auf."""
    if not profiles_dir.exists():
        return []

    summaries: list[ProfileSummary] = []
    for path in sorted(profiles_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("version") == PROFILE_VERSION and isinstance(data.get("name"), str):
                summaries.append(ProfileSummary(name=data["name"], path=path))
        except (OSError, json.JSONDecodeError):
            continue
    return summaries


def create_profile(name: str, password: str, profiles_dir: Path = PROFILES_DIR) -> Profile:
    """Erstellt eine neue verschlüsselte Identität mit frischem Schlüsselpaar."""
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Profilname darf nicht leer sein.")
    if not password:
        raise ValueError("Passwort darf nicht leer sein.")

    existing = list_profiles(profiles_dir)
    if any(p.name.lower() == clean_name.lower() for p in existing):
        raise ValueError(f"Ein Profil mit dem Namen '{clean_name}' existiert bereits.")

    profiles_dir.mkdir(parents=True, exist_ok=True)
    slug = sanitize_profile_filename(clean_name)
    file_path = profiles_dir / f"{slug}.json"
    counter = 2
    while file_path.exists():
        file_path = profiles_dir / f"{slug}_{counter}.json"
        counter += 1

    salt = os.urandom(SALT_LENGTH)
    storage_key = derive_key_from_password(password, salt)
    profile = Profile(
        name=clean_name,
        keypair=generate_keypair(),
        file_path=file_path,
        salt=salt,
        storage_key=storage_key,
    )
    save_profile(profile)
    return profile


def load_profile(path: Path, password: str) -> Profile:
    """Entschlüsselt und lädt ein gespeichertes Profil."""
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Profildatei konnte nicht gelesen werden: {exc}") from exc

    if envelope.get("version") != PROFILE_VERSION:
        raise ValueError("Nicht unterstützte Profil-Version.")

    name = envelope.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("Ungültiger Profilname in der Datei.")

    try:
        salt = b64_decode(envelope["salt"])
        nonce = b64_decode(envelope["nonce"])
        ciphertext = b64_decode(envelope["ciphertext"])
    except (KeyError, ValueError) as exc:
        raise ValueError("Beschädigte Profil-Metadaten.") from exc

    storage_key = derive_key_from_password(password, salt)
    try:
        plaintext = decrypt_bytes(storage_key, nonce, ciphertext, associated_data=name.encode("utf-8"))
    except InvalidTag as exc:
        raise ValueError("Falsches Passwort oder beschädigtes Profil.") from exc

    try:
        payload = json.loads(plaintext.decode("utf-8"))
        keypair = keypair_from_private_b64(payload["private_key_b64"])
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise ValueError(f"Profildaten ungültig: {exc}") from exc

    raw_contacts = payload.get("contacts", {})
    contacts: dict[str, str] = {}
    if isinstance(raw_contacts, dict):
        for contact_name, pub_b64 in raw_contacts.items():
            if isinstance(contact_name, str) and isinstance(pub_b64, str):
                contacts[contact_name] = pub_b64

    last_recipient = payload.get("last_recipient_b64")
    if not isinstance(last_recipient, str) or not last_recipient.strip():
        last_recipient = None

    return Profile(
        name=name,
        keypair=keypair,
        file_path=path,
        salt=salt,
        storage_key=storage_key,
        contacts=contacts,
        last_recipient_b64=last_recipient,
    )


def save_profile(profile: Profile) -> None:
    """Verschlüsselt das Profil und speichert es atomar auf der Festplatte."""
    profile.file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "private_key_b64": b64_encode(serialize_private_key(profile.keypair.private_key)),
        "contacts": profile.contacts,
        "last_recipient_b64": profile.last_recipient_b64,
    }
    plaintext = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    nonce, ciphertext = encrypt_bytes(
        profile.storage_key,
        plaintext,
        associated_data=profile.name.encode("utf-8"),
    )

    envelope = {
        "version": PROFILE_VERSION,
        "name": profile.name,
        "kdf": "pbkdf2-sha256",
        "salt": b64_encode(profile.salt),
        "nonce": b64_encode(nonce),
        "ciphertext": b64_encode(ciphertext),
    }

    tmp_path = profile.file_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, profile.file_path)

