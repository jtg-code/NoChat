import os
import sys

from commands import execute_command
from config import HOST, PORT
from crypto import encrypt_message
from handlers import dispatch_packet
from network import SocketClient
from profile import Profile, create_profile, list_profiles, load_profile
from state import ChatSession
import ui


def prompt_create_profile() -> Profile:
    while True:
        name = ui.prompt_input("Name der neuen Identität: ")
        if not name:
            ui.print_error("Name darf nicht leer sein.")
            continue
        password = ui.prompt_password("Passwort für das Profil: ")
        if not password:
            ui.print_error("Passwort darf nicht leer sein.")
            continue
        confirm = ui.prompt_password("Passwort bestätigen: ")
        if password != confirm:
            ui.print_error("Passwörter stimmen nicht überein.")
            continue
        try:
            profile = create_profile(name, password)
            ui.print_info(f"Identität '{profile.name}' erstellt und verschlüsselt gespeichert.")
            return profile
        except ValueError as exc:
            ui.print_error(str(exc))


def select_or_create_profile() -> Profile:
    while True:
        profiles = list_profiles()
        if not profiles:
            ui.print_info("Keine gespeicherten Identitäten gefunden. Erstelle ein neues Profil.")
            return prompt_create_profile()

        ui.print_info("\nVerfügbare Identitäten:")
        for idx, summary in enumerate(profiles, start=1):
            ui.print_info(f"  {idx}) {summary.name}")
        ui.print_info("  N) Neue Identität erstellen")

        choice = ui.prompt_input("Identität wählen (Nummer, Name oder N): ")
        if not choice:
            continue
        if choice.lower() in {"n", "neu", "new"}:
            return prompt_create_profile()

        selected = None
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(profiles):
                selected = profiles[index]
        else:
            for summary in profiles:
                if summary.name.lower() == choice.lower():
                    selected = summary
                    break

        if selected is None:
            ui.print_error("Ungültige Auswahl.")
            continue

        while True:
            password = ui.prompt_password(f"Passwort für '{selected.name}' (leer = zurück): ")
            if not password:
                break
            try:
                return load_profile(selected.path, password)
            except ValueError as exc:
                ui.print_error(str(exc))


def setup_initial_recipient(session: ChatSession) -> None:
    if session.has_recipient and session.recipient_b64:
        contact = session.profile.contact_name_for_key(session.recipient_b64)
        label = f"{contact} ({session.recipient_b64})" if contact else session.recipient_b64
        ui.print_info(f"Letzter Empfänger geladen: {label}")
        initial_key = ui.prompt_input(
            "Anderen Empfänger (Name/Public Key) eingeben (oder Enter zum Behalten): "
        )
    else:
        initial_key = ui.prompt_input(
            "Empfänger (Name oder Public Key) eingeben (oder Enter zum Überspringen): "
        )

    if not initial_key:
        return
    try:
        contact_name = session.set_recipient(initial_key)
        if contact_name:
            ui.print_info(f"Empfänger gesetzt: {contact_name}")
        else:
            ui.print_info("Empfänger gesetzt.")
    except Exception as exc:
        ui.print_error(f"Ungültiger Empfänger ({exc}). Später mit /key <NAME|PUBLIC_KEY> setzen.")


def send_chat_message(text: str, session: ChatSession, client: SocketClient) -> None:
    if not session.has_recipient or session.recipient_key is None or session.recipient_b64 is None:
        ui.print_info("Kein Empfänger gesetzt. Nutze: /key <NAME|PUBLIC_KEY>")
        return

    package = encrypt_message(session.keypair.private_key, session.recipient_key, text)
    payload = {
        "type": "message",
        "recipient_public_key": session.recipient_b64,
        **package.to_b64_dict(),
    }
    client.send_json(payload)


def on_server_disconnect() -> None:
    ui.print_info("\n[System] Verbindung zum Server getrennt.")
    os._exit(0)


def main() -> None:
    try:
        profile = select_or_create_profile()
    except (KeyboardInterrupt, EOFError):
        ui.print_info("\nAbgebrochen.")
        return

    session = ChatSession(profile=profile)
    ui.print_banner(session.keypair.public_b64, profile_name=session.profile.name)

    client = SocketClient(
        host=HOST,
        port=PORT,
        on_packet=lambda packet: dispatch_packet(packet, session),
        on_disconnect=on_server_disconnect,
    )

    try:
        client.connect()
    except OSError as exc:
        ui.print_error(f"Verbindung zu {HOST}:{PORT} fehlgeschlagen: {exc}")
        sys.exit(1)

    client.send_json({"type": "register", "public_key": session.keypair.public_b64})
    client.start_listening()

    setup_initial_recipient(session)
    ui.print_info("\nNutze /help für alle Befehle.\n")

    try:
        while session.running:
            text = ui.prompt_input("> ")
            if not text:
                continue
            if execute_command(text, session, client):
                continue
            send_chat_message(text, session, client)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        client.close()


if __name__ == "__main__":
    main()