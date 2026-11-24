import json
import threading
from typing import Any

from config import HOST, PORT
from crypto import EncryptedPackage, decrypt_message, encrypt_message, parse_public_key_b64
from network import SocketClient
from profile import Profile, create_profile, list_profiles, load_profile


class NoChatApi:
    """Python-API für die pywebview-Oberfläche."""

    def __init__(self) -> None:
        self._window: Any = None
        self._profile: Profile | None = None
        self._client: SocketClient | None = None
        self._connected: bool = False
        self._online_peers: dict[str, bool] = {}
        self._lock = threading.RLock()

    def attach_window(self, window: Any) -> None:
        self._window = window

    def shutdown(self) -> None:
        with self._lock:
            self._disconnect_locked()
            self._profile = None

    def list_profiles(self) -> list[dict[str, str]]:
        return [{"name": item.name, "path": str(item.path)} for item in list_profiles()]

    def create_profile(self, name: str, password: str) -> dict[str, Any]:
        try:
            profile = create_profile(name, password)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return self._activate_profile(profile)

    def unlock_profile(self, path: str, password: str) -> dict[str, Any]:
        from pathlib import Path

        try:
            profile = load_profile(Path(path), password)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return self._activate_profile(profile)

    def logout(self) -> dict[str, Any]:
        with self._lock:
            self._disconnect_locked()
            self._profile = None
        return {"ok": True}

    def reconnect(self) -> dict[str, Any]:
        with self._lock:
            if self._profile is None:
                return {"ok": False, "error": "Kein Profil geladen."}
            self._connect_locked(self._profile)
            return {"ok": True, "connected": self._connected, "state": self._build_state_locked()}

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            if self._profile is None:
                return {"ok": False, "error": "Kein Profil geladen."}
            return {"ok": True, "state": self._build_state_locked()}

    def start_chat(self, public_key_b64: str, alias: str = "") -> dict[str, Any]:
        with self._lock:
            if self._profile is None:
                return {"ok": False, "error": "Kein Profil geladen."}
            try:
                clean_key = self._profile.ensure_chat(public_key_b64)
                if alias.strip():
                    self._profile.add_contact(alias.strip(), clean_key)
                self._profile.set_last_recipient(clean_key)
                self._query_presence_locked([clean_key])
            except Exception as exc:
                return {"ok": False, "error": f"Ungültiger Public Key: {exc}"}
            return {"ok": True, "peer_key": clean_key, "state": self._build_state_locked()}

    def select_chat(self, peer_key: str) -> dict[str, Any]:
        with self._lock:
            if self._profile is None:
                return {"ok": False, "error": "Kein Profil geladen."}
            try:
                clean_key = self._profile.ensure_chat(peer_key)
                self._profile.set_last_recipient(clean_key)
                self._query_presence_locked([clean_key])
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "peer_key": clean_key}

    def update_profile_settings(self, avatar: str, bio: str, show_online_status: bool) -> dict[str, Any]:
        with self._lock:
            if self._profile is None:
                return {"ok": False, "error": "Kein Profil geladen."}
            self._profile.update_settings(avatar, bio, show_online_status)
            if self._connected and self._client is not None:
                try:
                    self._client.send_json(
                        {
                            "type": "presence_update",
                            "show_online_status": self._profile.show_online_status,
                        }
                    )
                except OSError:
                    self._connected = False
                    self._emit("onConnectionStatus", {"connected": False})
            return {"ok": True, "state": self._build_state_locked()}

    def save_contact(self, name: str, peer_key: str) -> dict[str, Any]:
        with self._lock:
            if self._profile is None:
                return {"ok": False, "error": "Kein Profil geladen."}
            try:
                self._profile.add_contact(name, peer_key)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "state": self._build_state_locked()}

    def send_message(self, peer_key: str, text: str) -> dict[str, Any]:
        clean_text = text.strip()
        if not clean_text:
            return {"ok": False, "error": "Nachricht darf nicht leer sein."}

        with self._lock:
            if self._profile is None:
                return {"ok": False, "error": "Kein Profil geladen."}
            if not self._connected or self._client is None:
                return {"ok": False, "error": "Nicht mit dem Server verbunden."}

            try:
                recipient_pub = parse_public_key_b64(peer_key)
                clean_key = peer_key.strip()
                inner_payload = json.dumps(
                    {
                        "v": 2,
                        "text": clean_text,
                        "profile": self._profile.export_public_profile(),
                    },
                    ensure_ascii=False,
                )
                package = encrypt_message(self._profile.keypair.private_key, recipient_pub, inner_payload)
                payload = {
                    "type": "message",
                    "recipient_public_key": clean_key,
                    **package.to_b64_dict(),
                }
                self._client.send_json(payload)
                entry = self._profile.append_message(clean_key, "me", clean_text)
                self._profile.set_last_recipient(clean_key)
                return {"ok": True, "message": entry, "peer_key": clean_key}
            except OSError as exc:
                self._connected = False
                self._emit("onConnectionStatus", {"connected": False})
                return {"ok": False, "error": f"Senden fehlgeschlagen: {exc}"}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

    def _activate_profile(self, profile: Profile) -> dict[str, Any]:
        with self._lock:
            self._disconnect_locked()
            self._profile = profile
            self._connect_locked(profile)
            return {"ok": True, "state": self._build_state_locked()}

    def _connect_locked(self, profile: Profile) -> None:
        self._disconnect_locked()
        client = SocketClient(
            host=HOST,
            port=PORT,
            on_packet=self._on_packet,
            on_disconnect=self._on_disconnect,
        )
        try:
            client.connect()
            client.send_json(
                {
                    "type": "register",
                    "public_key": profile.keypair.public_b64,
                    "show_online_status": profile.show_online_status,
                }
            )
            client.start_listening()
            self._client = client
            self._connected = True
            if profile.chats:
                self._query_presence_locked(list(profile.chats.keys()))
        except OSError:
            client.close()
            self._client = None
            self._connected = False

    def _query_presence_locked(self, public_keys: list[str]) -> None:
        if not self._connected or self._client is None or not public_keys:
            return
        try:
            self._client.send_json({"type": "presence_query", "public_keys": public_keys})
        except OSError:
            pass

    def _disconnect_locked(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        self._connected = False
        self._online_peers.clear()

    def _is_peer_online_locked(self, peer_key: str) -> bool:
        assert self._profile is not None
        peer_info = self._profile.peer_profiles.get(peer_key, {})
        if not peer_info.get("show_online_status", True):
            return False
        return bool(self._online_peers.get(peer_key, False))

    def _build_state_locked(self) -> dict[str, Any]:
        assert self._profile is not None
        profile = self._profile
        chat_items: list[dict[str, Any]] = []
        for peer_key, messages in profile.chats.items():
            last_msg = messages[-1] if messages else None
            peer_info = profile.peer_profiles.get(peer_key, {})
            chat_items.append(
                {
                    "peer_key": peer_key,
                    "label": profile.contact_name_for_key(peer_key) or "",
                    "avatar": peer_info.get("avatar", ""),
                    "bio": peer_info.get("bio", ""),
                    "show_online_status": peer_info.get("show_online_status", True),
                    "online": self._is_peer_online_locked(peer_key),
                    "last_text": last_msg["text"] if last_msg else "",
                    "last_timestamp": last_msg["timestamp"] if last_msg else "",
                    "messages": list(messages),
                }
            )
        chat_items.sort(key=lambda item: item["last_timestamp"], reverse=True)

        return {
            "profile_name": profile.name,
            "public_key": profile.keypair.public_b64,
            "avatar": profile.avatar,
            "bio": profile.bio,
            "show_online_status": profile.show_online_status,
            "connected": self._connected,
            "host": HOST,
            "port": PORT,
            "active_peer": profile.last_recipient_b64,
            "chats": chat_items,
            "contacts": dict(profile.contacts),
        }

    @staticmethod
    def _unpack_message_payload(raw_plaintext: str) -> tuple[str, dict[str, Any] | None]:
        try:
            data = json.loads(raw_plaintext)
            if isinstance(data, dict) and data.get("v") == 2 and isinstance(data.get("text"), str):
                profile_info = data.get("profile")
                return data["text"], profile_info if isinstance(profile_info, dict) else None
        except (json.JSONDecodeError, TypeError):
            pass
        return raw_plaintext, None

    def _on_packet(self, packet: dict[str, Any]) -> None:
        msg_type = packet.get("type", "")
        if msg_type == "message":
            with self._lock:
                if self._profile is None:
                    return
                try:
                    package = EncryptedPackage.from_b64_dict(packet)
                    raw_plaintext = decrypt_message(self._profile.keypair.private_key, package)
                    text, profile_info = self._unpack_message_payload(raw_plaintext)
                    sender_key = packet["sender_public_key"].strip()
                    entry = self._profile.append_message(sender_key, "peer", text)
                    if profile_info is not None:
                        peer_info = self._profile.update_peer_profile(sender_key, profile_info)
                    else:
                        peer_info = self._profile.peer_profiles.get(sender_key, {})
                    label = self._profile.contact_name_for_key(sender_key) or ""
                    online = self._is_peer_online_locked(sender_key)
                except Exception as exc:
                    self._emit("onServerError", {"message": f"Entschlüsselungsfehler: {exc}"})
                    return
            self._emit(
                "onIncomingMessage",
                {
                    "peer_key": sender_key,
                    "label": label,
                    "message": entry,
                    "avatar": peer_info.get("avatar", ""),
                    "bio": peer_info.get("bio", ""),
                    "show_online_status": peer_info.get("show_online_status", True),
                    "online": online,
                },
            )
        elif msg_type == "presence":
            statuses = packet.get("statuses", {})
            if not isinstance(statuses, dict):
                return
            with self._lock:
                if self._profile is None:
                    return
                resolved: dict[str, bool] = {}
                for key, is_online in statuses.items():
                    if isinstance(key, str):
                        clean_key = key.strip()
                        self._online_peers[clean_key] = bool(is_online)
                        resolved[clean_key] = self._is_peer_online_locked(clean_key)
            self._emit("onPresenceUpdate", {"statuses": resolved})
        elif msg_type == "error":
            self._emit("onServerError", {"message": str(packet.get("message", "Unbekannter Fehler"))})

    def _on_disconnect(self) -> None:
        with self._lock:
            self._connected = False
            self._client = None
        self._emit("onConnectionStatus", {"connected": False})

    def _emit(self, func_name: str, payload: dict[str, Any]) -> None:
        if self._window is None:
            return
        try:
            self._window.evaluate_js(f"window.{func_name} && window.{func_name}({json.dumps(payload)})")
        except Exception:
            pass

