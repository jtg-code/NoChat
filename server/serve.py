import json
import socket
import threading

HOST = "127.0.0.1"
PORT = 5555

clients: dict[str, socket.socket] = {}
clients_lock = threading.Lock()


def send_json(conn: socket.socket, payload: dict) -> None:
    data = (json.dumps(payload) + "\n").encode("utf-8")
    conn.sendall(data)


def handle_client(conn: socket.socket, addr: tuple[str, int]) -> None:
    registered_pub_key: str | None = None
    buffer = b""

    try:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buffer += chunk

            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue

                try:
                    msg = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    send_json(conn, {"type": "error", "message": "Ungültiges JSON-Format."})
                    continue

                msg_type = msg.get("type")

                if msg_type == "register":
                    pub_key = msg.get("public_key", "").strip()
                    if not pub_key:
                        send_json(conn, {"type": "error", "message": "Kein Public Key angegeben."})
                        continue

                    with clients_lock:
                        registered_pub_key = pub_key
                        clients[registered_pub_key] = conn
                    print(f"[+] Client registriert ({addr[0]}:{addr[1]}): {registered_pub_key}")

                elif msg_type == "message":
                    recipient_key = msg.get("recipient_public_key", "").strip()
                    with clients_lock:
                        target_conn = clients.get(recipient_key)

                    if target_conn is None:
                        send_json(
                            conn,
                            {
                                "type": "error",
                                "message": "Empfänger ist nicht verbunden oder Public Key unbekannt.",
                            },
                        )
                        continue

                    try:
                        send_json(target_conn, msg)
                    except OSError:
                        send_json(
                            conn,
                            {"type": "error", "message": "Zustellung an Empfänger fehlgeschlagen."},
                        )

    except OSError:
        pass
    finally:
        if registered_pub_key:
            with clients_lock:
                if clients.get(registered_pub_key) is conn:
                    del clients[registered_pub_key]
            print(f"[-] Client getrennt: {registered_pub_key}")
        conn.close()


def main() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen()
        print(f"E2EE-Relay-Server läuft auf {HOST}:{PORT} ...")

        while True:
            conn, addr = server.accept()
            thread = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            thread.start()


if __name__ == "__main__":
    main()