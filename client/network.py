import json
import socket
import threading
from collections.abc import Callable

from config import BUFFER_SIZE


class SocketClient:
    def __init__(
        self,
        host: str,
        port: int,
        on_packet: Callable[[dict], None],
        on_disconnect: Callable[[], None],
    ) -> None:
        self.host = host
        self.port = port
        self.on_packet = on_packet
        self.on_disconnect = on_disconnect
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def connect(self) -> None:
        self._sock.connect((self.host, self.port))

    def send_json(self, payload: dict) -> None:
        raw = (json.dumps(payload) + "\n").encode("utf-8")
        self._sock.sendall(raw)

    def start_listening(self) -> None:
        thread = threading.Thread(target=self._receive_loop, daemon=True)
        thread.start()

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def _receive_loop(self) -> None:
        buffer = b""
        try:
            while True:
                chunk = self._sock.recv(BUFFER_SIZE)
                if not chunk:
                    self.on_disconnect()
                    return
                buffer += chunk

                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    packet = json.loads(line.decode("utf-8"))
                    self.on_packet(packet)
        except OSError:
            pass