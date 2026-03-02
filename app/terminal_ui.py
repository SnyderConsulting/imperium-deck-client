from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Static
from websockets.client import connect


class StatusBar(Static):
    connected = reactive(False)
    events = reactive(0)

    def render(self) -> str:
        state = "CONNECTED" if self.connected else "DISCONNECTED"
        return f"WebSocket: {state} | Events: {self.events}"


class InputMonitorApp(App):
    CSS = """
    Screen {
      layout: vertical;
    }
    #body {
      height: 1fr;
    }
    #events, #state {
      width: 1fr;
      height: 1fr;
      border: round #3b7ea1;
    }
    #status {
      height: 3;
      border: round #3b7ea1;
      padding: 0 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    def __init__(self, ws_url: str) -> None:
        super().__init__()
        self.ws_url = ws_url
        self.recent: deque[dict] = deque(maxlen=250)
        self.state: dict[str, dict[str, int]] = {}
        self.status_widget = StatusBar(id="status")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="body"):
            with Horizontal():
                yield DataTable(id="events")
                yield DataTable(id="state")
        yield self.status_widget
        yield Footer()

    def on_mount(self) -> None:
        events = self.query_one("#events", DataTable)
        events.add_columns("time", "device", "type", "code", "value")

        state = self.query_one("#state", DataTable)
        state.add_columns("device", "active_buttons", "active_axes")

        self.run_worker(self.stream_events(), exclusive=True)

    async def stream_events(self) -> None:
        while True:
            try:
                async with connect(self.ws_url) as ws:
                    self.status_widget.connected = True
                    await ws.send("ping")
                    async for raw in ws:
                        payload = json.loads(raw)
                        self.recent.append(payload)
                        self.status_widget.events += 1
                        self.apply_event_to_state(payload)
                        self.refresh_tables()
            except Exception:
                self.status_widget.connected = False
                await asyncio.sleep(1)

    def apply_event_to_state(self, event: dict) -> None:
        device = event.get("device_path", "unknown")
        event_type = event.get("event_type_name")
        code_name = str(event.get("code_name"))
        value = int(event.get("value", 0))

        entry = self.state.setdefault(device, {"buttons": {}, "axes": {}})
        if event_type == "EV_KEY":
            entry["buttons"][code_name] = value
        elif event_type == "EV_ABS":
            entry["axes"][code_name] = value

    def refresh_tables(self) -> None:
        events_table = self.query_one("#events", DataTable)
        events_table.clear(columns=False)
        for row in list(self.recent)[-100:][::-1]:
            ts = datetime.fromtimestamp(row.get("timestamp", 0)).strftime("%H:%M:%S")
            events_table.add_row(
                ts,
                str(row.get("device_name", ""))[:24],
                str(row.get("event_type_name", "")),
                str(row.get("code_name", row.get("code", ""))),
                str(row.get("value", "")),
            )

        state_table = self.query_one("#state", DataTable)
        state_table.clear(columns=False)
        for device, values in self.state.items():
            buttons = " ".join(
                f"{k}:{v}" for k, v in values["buttons"].items() if v != 0
            ) or "-"
            axes = " ".join(
                f"{k}:{v}" for k, v in values["axes"].items() if v != 0
            ) or "-"
            state_table.add_row(device, buttons, axes)


def main() -> None:
    app = InputMonitorApp("ws://127.0.0.1:8765/ws/events")
    app.run()


if __name__ == "__main__":
    main()
