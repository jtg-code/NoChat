from collections.abc import Callable

from crypto import EncryptedPackage, decrypt_message
from state import ChatSession
import ui

PacketHandler = Callable[[dict, ChatSession], None]
_HANDLERS: dict[str, PacketHandler] = {}


def register_handler(msg_type: str) -> Callable[[PacketHandler], PacketHandler]:
    """Decorator zum Registrieren von Handlern für eingehende Server-Nachrichten."""
    def decorator(func: PacketHandler) -> PacketHandler:
        _HANDLERS[msg_type] = func
        return func
    return decorator


def dispatch_packet(packet: dict, session: ChatSession) -> None:
    msg_type = packet.get("type", "")
    handler = _HANDLERS.get(msg_type)
    if handler:
        handler(packet, session)


@register_handler("message")
def handle_encrypted_message(packet: dict, session: ChatSession) -> None:
    try:
        package = EncryptedPackage.from_b64_dict(packet)
        plaintext = decrypt_message(session.keypair.private_key, package)
        sender_key = packet["sender_public_key"]
        sender_name = session.profile.contact_name_for_key(sender_key)
        sender_label = f"{sender_name} ({sender_key[:12]}...)" if sender_name else sender_key
        ui.print_async_event(f"Von {sender_label}", plaintext)
    except Exception as exc:
        ui.print_async_event("Fehler beim Entschlüsseln", str(exc))


@register_handler("error")
def handle_server_error(packet: dict, session: ChatSession) -> None:
    ui.print_async_event("Server", str(packet.get("message", "Unbekannter Fehler")))