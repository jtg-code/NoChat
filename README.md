# NoChat — Ende-zu-Ende-verschlüsselter Messenger

NoChat ist ein Ende-zu-Ende-verschlüsselter (E2EE) Desktop-Messenger mit einem **Python/`pywebview`-Client** und einem **TCP-Relay-Server in Rust**.

Der Relay-Server sieht zu keinem Zeitpunkt Klartextnachrichten, Profilbilder oder Beschreibungen: Er kennt ausschließlich die öffentlichen Schlüssel (`public_key`) der verbundenen Clients, leitet verschlüsselte Pakete weiter und verwaltet den optionalen Online-Status (Presence).

---

## Inhaltsverzeichnis

- [Features](#features)
- [Projektstruktur](#projektstruktur)
- [Kryptografie & Datenspeicherung](#kryptografie--datenspeicherung)
- [Relay-Protokoll](#relay-protokoll)
- [Installation & Start](#installation--start)
  - [Voraussetzungen](#voraussetzungen)
  - [1. Server bauen & starten](#1-server-bauen--starten)
  - [2. Client einrichten & starten](#2-client-einrichten--starten)
- [Konfiguration](#konfiguration)
- [GitHub Actions Release-Workflow](#github-actions-release-workflow)

---

## Features

- **Ende-zu-Ende-Verschlüsselung (E2EE)**: Nachrichten und Profil-Metadaten (Avatar, Beschreibung) werden clientseitig mit X25519 + HKDF-SHA256 + AES-GCM verschlüsselt.
- **Passwortgeschützte lokale Profile**: Private Keys, Kontakte, Chat-Verläufe und Einstellungen werden lokal verschlüsselt gespeichert.
- **Desktop-Oberfläche**: Moderne GUI auf Basis von `pywebview` (HTML/CSS/JS über eine Python-Bridge).
- **Online-Status (Presence) mit Datenschutz**:
  - Nutzer können festlegen, ob ihr Online-Status für andere sichtbar sein soll (`show_online_status`).
  - Bei deaktiviertem Online-Status liefert der Server anderen Clients konsequent `false` zurück, während Nachrichten weiterhin zugestellt werden.
- **Performanter Rust-Relay-Server**: Multi-threaded TCP-Server mit thread-sicherer Client-Verwaltung und sauberem Disconnect-Handling.

---

## Projektstruktur

```text
NoChat/
├── .github/
│   └── workflows/
│       └── release-server.yml   # Manueller GitHub-Workflow für Server-Releases (Windows & Linux)
├── client/
│   ├── gui/
│   │   ├── index.html           # GUI-Layout
│   │   ├── app.js               # Frontend-Logik
│   │   └── style.css            # Styling
│   ├── profiles/                # Lokal gespeicherte, verschlüsselte Profile (*.json, git-ignored)
│   ├── app.py                   # Einstiegspunkt der pywebview-Desktop-App
│   ├── config.py                # Client-Konfiguration (Host, Port, Krypto-Parameter)
│   ├── crypto.py                # X25519, HKDF-SHA256, PBKDF2-HMAC-SHA256, AES-GCM
│   ├── gui_bridge.py            # Python-API-Bridge (`NoChatApi`) für das Webview-Frontend
│   ├── network.py               # TCP-Socket-Client (`SocketClient`, zeilenbasiertes JSON)
│   ├── profile.py               # Profilverwaltung, Kontaktauflösung, verschlüsselte Persistenz
│   ├── commands.py              # CLI-Befehlsregistrierung (/help, /key, /me, /contacts, ...)
│   ├── handlers.py              # Paket-Handler-Registry (`message`, `error`)
│   ├── state.py                 # Session-Zustand
│   └── ui.py                    # Terminal-Ausgabehelfer
├── server/
│   ├── src/
│   │   └── main.rs              # Rust-Relay-Server (TCP + Presence + Message-Routing)
│   ├── Cargo.toml               # Rust-Paketkonfiguration (`nochat-server`, `serde_json`)
│   ├── Cargo.lock               # Fixierte Dependency-Versionen
│   └── serve.py                 # Ursprüngliche Python-Referenzimplementierung des Servers
├── requirements.txt             # Python-Abhängigkeiten des Clients
├── start_client.bat             # Windows-Startskript für den Client
└── start_server.bat             # Windows-Startskript für den Rust-Server
```

---

## Kryptografie & Datenspeicherung

Alle kryptografischen Operationen sind in [`client/crypto.py`](client/crypto.py) und [`client/config.py`](client/config.py) definiert:

1. **Schlüsselaustausch & Nachrichtenverschlüsselung**:
   - **Schlüsselpaar**: X25519 (`32` Bytes Raw, Base64-kodiert).
   - **Key Derivation**: X25519-Diffie-Hellman + `HKDF-SHA256` (`info = b"e2ee-message-encryption"`, Schlüssellänge `32` Bytes).
   - **Verschlüsselung**: `AES-GCM` mit zufälligem `12`-Byte-Nonce pro Nachricht.
2. **Lokale Profilverschlüsselung** ([`client/profile.py`](client/profile.py)):
   - Profile werden unter `client/profiles/<profilname>.json` gespeichert.
   - Der Speicherschlüssel wird aus dem Benutzerpasswort mittels `PBKDF2-HMAC-SHA256` (`600.000` Iterationen, `16`-Byte-Salt) abgeleitet.
   - Der gesamte sensible Inhalt (Private Key, Kontakte, Chat-Verläufe, Avatar, Bio, `show_online_status`, `peer_profiles`) wird mit `AES-GCM` verschlüsselt abgelegt.

---

## Relay-Protokoll

Client und Server kommunizieren über TCP (`127.0.0.1:5555`) mittels **zeilengetrenntem JSON** (ein UTF-8-kodiertes JSON-Objekt pro Zeile, abgeschlossen durch `\n`).

### Client → Server

- **`register`**: Registriert den Client anhand seines öffentlichen Schlüssels. `show_online_status` ist optional (Standard: `true`).
  ```json
  {
    "type": "register",
    "public_key": "<PUBLIC_KEY_B64>",
    "show_online_status": true
  }
  ```
- **`presence_update`**: Aktualisiert die Sichtbarkeit des eigenen Online-Status und benachrichtigt verbundene Clients.
  ```json
  {
    "type": "presence_update",
    "show_online_status": false
  }
  ```
- **`presence_query`**: Fragt den effektiven Online-Status einer Liste von Public Keys ab.
  ```json
  {
    "type": "presence_query",
    "public_keys": ["<KEY_1>", "<KEY_2>"]
  }
  ```
  > **Datenschutzregel**: Ist ein Key zwar verbunden, hat aber `show_online_status: false` gesetzt, antwortet der Server mit `false`.
- **`message`**: Leitet ein verschlüsseltes Paket unverändert an den Empfänger (`recipient_public_key`) weiter.
  ```json
  {
    "type": "message",
    "recipient_public_key": "<RECIPIENT_KEY_B64>",
    "sender_public_key": "<SENDER_KEY_B64>",
    "nonce": "<NONCE_B64>",
    "ciphertext": "<CIPHERTEXT_B64>"
  }
  ```

### Server → Client

- **`presence`**: Status-Update oder Antwort auf `presence_query`.
  ```json
  {
    "type": "presence",
    "statuses": {
      "<KEY_1>": true,
      "<KEY_2>": false
    }
  }
  ```
- **`error`**: Fehlermeldung bei ungültigem JSON, unbekanntem Pakettyp, fehlender Registrierung oder nicht verbundenem Empfänger.
  ```json
  {
    "type": "error",
    "message": "Empfänger ist nicht verbunden oder Public Key unbekannt."
  }
  ```

Beim Trennen einer Verbindung entfernt der Server den Key thread-sicher (nur falls die gespeicherte Connection-ID noch übereinstimmt) und sendet ein `presence`-Update mit `false` an die übrigen verbundenen Clients.

---

## Installation & Start

### Voraussetzungen

- **Rust & Cargo** (für den Server)
- **Python 3** (für den Client)

### 1. Server bauen & starten

Release-Binary bauen:

```bash
cargo build --release --manifest-path server/Cargo.toml
```

Server starten:

- **Windows**: `start_server.bat` ausführen (startet `server\target\release\nochat-server.exe` oder fällt auf `cargo run --release` zurück).
- **Manuell / Linux**:
  ```bash
  cargo run --release --manifest-path server/Cargo.toml
  ```

### 2. Client einrichten & starten

Virtuelle Umgebung (optional, empfohlen) und Abhängigkeiten installieren:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
```

Client starten:

- **Windows**: `start_client.bat` ausführen.
- **Manuell**:
  ```bash
  python client/app.py
  ```

---

## Konfiguration

- **Server-Port**: Standardmäßig `5555` auf `127.0.0.1`. Kann beim Start des Rust-Servers über die Umgebungsvariable `NOCHAT_PORT` überschrieben werden:
  ```bash
  NOCHAT_PORT=6000 cargo run --release --manifest-path server/Cargo.toml
  ```
- **Client-Verbindung**: Host (`HOST = "127.0.0.1"`) und Port (`PORT = 5555`) lassen sich in [`client/config.py`](client/config.py) anpassen.

---

## GitHub Actions Release-Workflow

Im Repository ist unter [`.github/workflows/release-server.yml`](.github/workflows/release-server.yml) ein manueller Release-Workflow (`workflow_dispatch`) eingerichtet:

1. In GitHub auf **Actions → Release Server → Run workflow** klicken.
2. Ein Release-Tag angeben (z. B. `v0.1.0`) und optional auswählen, ob es sich um ein Pre-Release handelt.
3. Der Workflow baut automatisch Release-Binaries für **Windows** (`nochat-server-windows-x86_64.exe`) und **Linux** (`nochat-server-linux-x86_64`) und veröffentlicht sie mit generierten Release-Notes als neues GitHub Release.

