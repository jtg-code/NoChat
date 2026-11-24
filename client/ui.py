import getpass


def print_banner(own_pub_b64: str, profile_name: str | None = None) -> None:
    print("=" * 60)
    if profile_name:
        print(f"Aktive Identität: {profile_name}")
    print("Dein Public Key (diesen an deinen Chat-Partner senden):")
    print(own_pub_b64)
    print("=" * 60)


def print_info(message: str) -> None:
    print(message)


def print_error(message: str) -> None:
    print(f"[Fehler] {message}")


def print_async_event(prefix: str, message: str) -> None:
    """Gibt Hintergrund-Nachrichten aus, ohne den Eingabe-Prompt zu zerstören."""
    print(f"\n[{prefix}]: {message}\n> ", end="", flush=True)


def prompt_input(prompt: str = "> ") -> str:
    return input(prompt).strip()


def prompt_password(prompt: str = "Passwort: ") -> str:
    return getpass.getpass(prompt)