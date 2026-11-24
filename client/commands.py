from collections.abc import Callable
from dataclasses import dataclass

from network import SocketClient
from state import ChatSession
import ui

CommandFunc = Callable[[str, ChatSession, SocketClient], None]


@dataclass(frozen=True)
class Command:
    name: str
    usage: str
    description: str
    handler: CommandFunc


_COMMANDS: dict[str, Command] = {}


def register_command(name: str, usage: str, description: str) -> Callable[[CommandFunc], CommandFunc]:
    """Decorator zum Registrieren neuer CLI-Befehle."""
    def decorator(func: CommandFunc) -> CommandFunc:
        _COMMANDS[name] = Command(name=name, usage=usage, description=description, handler=func)
        return func
    return decorator


def execute_command(raw_input: str, session: ChatSession, client: SocketClient) -> bool:
    """Prüft, ob die Eingabe ein Befehl ist, und führt ihn aus. Gibt True zurück, wenn verarbeitet."""
    if not raw_input.startswith("/"):
        return False

    parts = raw_input.split(" ", 1)
    cmd_name = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    command = _COMMANDS.get(cmd_name)
    if not command:
        ui.print_error(f"Unbekannter Befehl '{cmd_name}'. Nutze /help für eine Übersicht.")
        return True

    command.handler(arg, session, client)
    return True


@register_command("/help", "/help", "Zeigt alle verfügbaren Befehle an")
def cmd_help(arg: str, session: ChatSession, client: SocketClient) -> None:
    lines = ["Verfügbare Befehle:"]
    for cmd in _COMMANDS.values():
        lines.append(f"  {cmd.usage:<22} - {cmd.description}")
    ui.print_info("\n".join(lines))


@register_command("/key", "/key <NAME|PUBLIC_KEY>", "Setzt oder wechselt den Empfänger")
def cmd_key(arg: str, session: ChatSession, client: SocketClient) -> None:
    if not arg:
        ui.print_error("Bitte einen Kontaktnamen oder Public Key angeben: /key <NAME|PUBLIC_KEY>")
        return
    try:
        contact_name = session.set_recipient(arg)
        if contact_name:
            ui.print_info(f"Empfänger aktualisiert: {contact_name}")
        else:
            ui.print_info("Empfänger aktualisiert.")
    except Exception as exc:
        ui.print_error(f"Ungültiger Empfänger: {exc}")


@register_command("/me", "/me", "Zeigt Profil und eigenen Public Key an")
def cmd_me(arg: str, session: ChatSession, client: SocketClient) -> None:
    ui.print_info(f"Identität: {session.profile.name}")
    ui.print_info(f"Dein Public Key: {session.keypair.public_b64}")
    if session.has_recipient and session.recipient_b64:
        contact = session.profile.contact_name_for_key(session.recipient_b64)
        label = f"{contact} ({session.recipient_b64})" if contact else session.recipient_b64
        ui.print_info(f"Aktueller Empfänger: {label}")


@register_command("/contacts", "/contacts", "Zeigt alle gespeicherten Kontakte des Profils")
def cmd_contacts(arg: str, session: ChatSession, client: SocketClient) -> None:
    if not session.profile.contacts:
        ui.print_info("Keine Kontakte gespeichert. Hinzufügen mit: /add <Name> <PUBLIC_KEY>")
        return
    lines = ["Gespeicherte Kontakte:"]
    for name, pub_b64 in sorted(session.profile.contacts.items(), key=lambda item: item[0].lower()):
        lines.append(f"  {name}: {pub_b64}")
    ui.print_info("\n".join(lines))


@register_command("/add", "/add <Name> <PUBLIC_KEY>", "Speichert einen Kontakt im Profil")
def cmd_add_contact(arg: str, session: ChatSession, client: SocketClient) -> None:
    parts = arg.split(" ", 1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        ui.print_error("Verwendung: /add <Name> <PUBLIC_KEY>")
        return
    contact_name, pub_b64 = parts[0].strip(), parts[1].strip()
    try:
        session.profile.add_contact(contact_name, pub_b64)
        ui.print_info(f"Kontakt '{contact_name}' gespeichert.")
    except Exception as exc:
        ui.print_error(f"Kontakt konnte nicht gespeichert werden: {exc}")


@register_command("/del", "/del <Name>", "Löscht einen Kontakt aus dem Profil")
def cmd_delete_contact(arg: str, session: ChatSession, client: SocketClient) -> None:
    if not arg:
        ui.print_error("Verwendung: /del <Name>")
        return
    if session.profile.remove_contact(arg):
        ui.print_info(f"Kontakt '{arg}' gelöscht.")
    else:
        ui.print_error(f"Kontakt '{arg}' nicht gefunden.")


@register_command("/profile", "/profile", "Zeigt Details zum geladenen Profil")
def cmd_profile(arg: str, session: ChatSession, client: SocketClient) -> None:
    ui.print_info(
        f"Profil: {session.profile.name}\n"
        f"Datei: {session.profile.file_path}\n"
        f"Kontakte: {len(session.profile.contacts)}\n"
        f"Public Key: {session.keypair.public_b64}"
    )


@register_command("/quit", "/quit", "Beendet den Chat")
def cmd_quit(arg: str, session: ChatSession, client: SocketClient) -> None:
    session.running = False