"""Telegram (MTProto) access for the buyer-voice stages: a user session and read-only calls with a disk cache.

Keys: TG_API_ID and TG_API_HASH of an application from https://my.telegram.org (API development tools).
Login: `nf setup telegram` shows a QR code; scan it in the Telegram app (Settings > Devices > Link Desktop Device). The
session is saved to <workspace>/.tg/nf.session. That file gives full access to the account: it stays in the workspace
(which is not under git) and is never copied anywhere. The QR login needs no login code; a code login is not offered
because Telegram often holds codes back from new third-party API applications.

Calls are read-only: contacts.search (public chats by keyword), channels.getFullChannel (a chat's description) and
messages.search inside a public chat. No chat is
joined, no message is sent, and no author name or id is kept: a message is reduced to its id, date, text and two flags
(a reply, a forward). Every answer is cached per run month in data/cache/telegram/, so a re-run in the same month makes
no request. Between live calls the client waits `pace` seconds; Telethon waits out a FloodWait of up to
`max_flood_wait` seconds by itself, a longer one stops the run (FloodStop) and a re-run resumes from the cache.
Needs the optional extra: pip install 'niche-finder[telegram]' (telethon; qrcode for the login).
"""
from __future__ import annotations

import getpass
import hashlib
import importlib.util
import json
import os
import tempfile
import time
from pathlib import Path

from nichefinder import keys
from nichefinder.workspace import Workspace

KEY_NAMES = ("TG_API_ID", "TG_API_HASH")
DEVICE = {"device_model": "nf-research", "app_version": "0.1"}


class FloodStop(Exception):
    """Telegram asked to wait longer than the run allows; the stage stops and a re-run resumes from the cache."""


class ChatUnavailable(Exception):
    """A chat cannot be read: private, renamed, deleted, or its history is closed to non-members."""


def session_base(ws: Workspace) -> Path:
    """Telethon adds .session to this path."""
    return ws.root / ".tg" / "nf"


def problem(ws: Workspace) -> str | None:
    """None when the Telegram stages can run, otherwise a one-line fix (used by tools.check)."""
    if importlib.util.find_spec("telethon") is None:
        return "telethon is not installed: pip install 'niche-finder[telegram]'"
    missing = [k for k in KEY_NAMES if not keys.get(k)]
    if missing:
        return f"needs {', '.join(missing)} from https://my.telegram.org (API development tools) in the workspace .env"
    if not session_base(ws).with_suffix(".session").is_file():
        return "no Telegram session: run `nf setup telegram` and scan the QR code in the Telegram app"
    return None


def _client(ws: Workspace, flood_threshold: int = 60):
    from telethon.sync import TelegramClient
    api_id, api_hash = keys.require(*KEY_NAMES, purpose="Telegram API calls")
    session_base(ws).parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(session_base(ws)), int(api_id), api_hash, timeout=20, connection_retries=3, **DEVICE)
    client.flood_sleep_threshold = flood_threshold
    return client


def login(ws: Workspace) -> None:
    """Interactive QR login (`nf setup telegram`): prints the QR in the terminal, also opens it as an SVG image, refreshes
    it every ~30 s, asks for the cloud password when two-step verification is on. The image holds a login token and is
    deleted at the end."""
    from telethon.errors import SessionPasswordNeededError
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        raise SystemExit("qrcode is not installed: pip install 'niche-finder[telegram]'") from None
    client = _client(ws)
    client.connect()
    if client.is_user_authorized():
        print("Already logged in:", session_base(ws).with_suffix(".session"))
        client.disconnect()
        return
    img = Path(tempfile.gettempdir()) / "nf_tg_login_qr.svg"

    def show(url: str) -> None:
        qr = qrcode.QRCode(border=2)
        qr.add_data(url)
        qr.print_ascii(invert=True)
        try:   # SVG needs no Pillow; the default browser shows it
            qrcode.make(url, image_factory=qrcode.image.svg.SvgFillImage, box_size=20).save(str(img))
            if hasattr(os, "startfile"):
                os.startfile(img)
        except Exception as e:  # noqa: BLE001 - the terminal QR is enough
            print(f"(image not shown: {e}; scan the QR above)")

    qr_login = client.qr_login()
    print("Scan the QR in the Telegram app: Settings > Devices > Link Desktop Device. It refreshes every ~30 s.", flush=True)
    try:
        for attempt in range(10):
            show(qr_login.url)
            try:
                client.loop.run_until_complete(qr_login.wait(timeout=28))   # QRLogin is not covered by telethon.sync
                break
            except TimeoutError:
                print(f"\nQR expired, a new one ({attempt + 2}/10) ...", flush=True)
                client.loop.run_until_complete(qr_login.recreate())
        else:
            raise SystemExit("not scanned; run `nf setup telegram` again")
    except SessionPasswordNeededError:
        client.sign_in(password=getpass.getpass("cloud password (two-step verification; input hidden): "))
    finally:
        if img.exists():
            img.unlink()
    me = client.get_me()
    print(f"Logged in (user id {me.id}). Session: {session_base(ws).with_suffix('.session')} - keep this file private.")
    client.disconnect()


class Gateway:
    """Cached read-only Telegram calls. The connection opens on the first call that misses the cache, so a run fully in
    the cache needs no network. `live` counts the calls that went to Telegram."""

    def __init__(self, ws: Workspace, pace: float = 1.5, max_flood_wait: int = 120):
        self.ws, self.pace, self.max_flood_wait = ws, float(pace), int(max_flood_wait)
        self.cache = ws.cache("telegram")
        self.month = f"{ws.today:%Y-%m}"
        self.client = None
        self.live = 0
        self.offline = False   # set after a FloodStop: cache hits still work, a miss raises FloodStop at once

    def _path(self, key: str) -> Path:
        return self.cache / (hashlib.sha1(f"{key}|{self.month}".encode("utf-8")).hexdigest() + ".json")

    def _connect(self):
        if self.client is None:
            self.client = _client(self.ws, self.max_flood_wait)
            self.client.connect()
            if not self.client.is_user_authorized():
                self.client.disconnect()
                raise SystemExit("the Telegram session is not logged in: run `nf setup telegram`")
        return self.client

    def _cached(self, key: str, fetch):
        path = self._path(key)
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        if self.offline:
            raise FloodStop("not in the cache, and live calls stopped after a FloodWait")
        try:
            from telethon.errors import FloodWaitError
        except ImportError:   # _connect() then says what to install
            FloodWaitError = type("FloodWaitError", (Exception,), {})
        client = self._connect()
        try:
            data = fetch(client)
        except FloodWaitError as e:
            raise FloodStop(f"Telegram asks to wait {e.seconds} s (over {self.max_flood_wait} s); re-run later, the cache keeps "
                            "what was read") from None
        self.live += 1
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        time.sleep(self.pace)
        return data

    def search_chats(self, q: str, limit: int = 50) -> list[dict]:
        """Public channels and groups found by Telegram's global search: id, username, title, members, megagroup,
        broadcast, forum. Chats without a public username are left out (they cannot be read without joining)."""
        def fetch(client):
            from telethon import functions, types
            res = client(functions.contacts.SearchRequest(q=q, limit=limit))
            out = []
            for c in res.chats:
                if not isinstance(c, types.Channel):
                    continue
                username = c.username or next((u.username for u in (getattr(c, "usernames", None) or []) if u.active), "")
                if not username:
                    continue
                out.append({"id": c.id, "username": username, "title": c.title or "", "members": c.participants_count or 0,
                            "megagroup": int(bool(c.megagroup)), "broadcast": int(bool(c.broadcast)), "forum": int(bool(getattr(c, "forum", False)))})
            return out
        return self._cached(f"chats|{q}|{limit}", fetch)

    def chat_about(self, username: str) -> dict:
        """The chat's own description and member count (channels.getFullChannel). Raises ChatUnavailable."""
        def fetch(client):
            from telethon import functions
            from telethon.errors import FloodWaitError, RPCError
            try:
                full = client(functions.channels.GetFullChannelRequest(username))
            except (ValueError, RPCError) as e:
                if isinstance(e, FloodWaitError):
                    raise
                return {"_unavailable": f"{type(e).__name__}: {e}"[:200]}
            return {"about": full.full_chat.about or "", "members": full.full_chat.participants_count or 0}
        data = self._cached(f"about|{username}", fetch)
        if data.get("_unavailable"):
            raise ChatUnavailable(data["_unavailable"])
        return data

    def search_messages(self, username: str, term: str, since: str, limit: int = 100) -> list[dict]:
        """Messages of a public chat that Telegram's search finds for `term` (its own word matching), newest first,
        published on or after `since` (YYYY-MM-DD), at most `limit`. Raises ChatUnavailable when the chat cannot be read."""
        def fetch(client):
            from telethon.errors import RPCError
            out = []
            try:
                for m in client.iter_messages(username, search=term, limit=limit):
                    day = f"{m.date:%Y-%m-%d}"
                    if day < since:
                        break
                    text = (m.message or "").strip()
                    if text:
                        out.append({"id": m.id, "date": day, "text": text[:2000], "reply": int(bool(m.reply_to)),
                                    "fwd": int(bool(m.fwd_from))})
            except (ValueError, RPCError) as e:
                from telethon.errors import FloodWaitError
                if isinstance(e, FloodWaitError):
                    raise
                return {"_unavailable": f"{type(e).__name__}: {e}"[:200]}
            return out
        data = self._cached(f"msgs|{username}|{term}|{since}|{limit}", fetch)
        if isinstance(data, dict) and data.get("_unavailable"):
            raise ChatUnavailable(data["_unavailable"])
        return data

    def close(self) -> None:
        if self.client is not None:
            self.client.disconnect()
            self.client = None
