from pathlib import Path
import webview

from gui_bridge import NoChatApi


def main() -> None:
    api = NoChatApi()
    gui_index = Path(__file__).resolve().parent / "gui" / "index.html"

    window = webview.create_window(
        title="NoChat — E2EE Messenger",
        url=gui_index.as_uri(),
        js_api=api,
        width=1060,
        height=700,
        min_size=(760, 520),
        background_color="#0f1117",
    )
    api.attach_window(window)
    window.events.closed += api.shutdown
    webview.start()


if __name__ == "__main__":
    main()
