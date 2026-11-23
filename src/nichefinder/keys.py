"""API keys: read from the environment or the workspace .env file. Never stored in code or configs."""
from __future__ import annotations

import os
from pathlib import Path

# What each key group unlocks and where to get it. Shown by `nf doctor` and in skip messages.
GROUPS: dict[str, dict] = {
    "dataforseo": {
        "keys": ("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD"),
        "what": "Google Ads search volume, CPC and 48-month history (S3). Paid, about $0.09 per 1,000 keywords per location.",
        "where": "https://app.dataforseo.com/api-access",
    },
    "llm": {
        "keys": ("LLM_API_KEY",),
        "what": "Classifying Reddit posts and comments (S10). Any OpenAI-compatible endpoint; set LLM_BASE_URL and LLM_MODEL.",
        "where": "https://platform.deepseek.com/api_keys (default) or your provider",
    },
    "yandex": {
        "keys": ("YANDEX_API_KEY",),
        "what": "Yandex Wordstat search volume and dynamics (Russian market module).",
        "where": "https://yandex.cloud/en/docs/search-api/",
    },
    "producthunt": {
        "keys": ("PRODUCTHUNT_TOKEN",),
        "what": "Product Hunt GraphQL API v2: the top featured launches of the last 12 months (s0_producthunt). Free; "
                "the web pages are behind an anti-bot challenge.",
        "where": "https://www.producthunt.com/v2/oauth/applications (create an application, copy its developer token)",
    },
    "youtube": {
        "keys": ("YOUTUBE_API_KEY",),
        "what": "YouTube Data API v3: short-video search and statistics for info topics (info_youtube). Free quota of "
                "10,000 units per day.",
        "where": "https://console.cloud.google.com/apis/library/youtube.googleapis.com (create an API key under Credentials)",
    },
    "trustmrr": {
        "keys": ("TRUSTMRR_API_KEY",),
        "what": "Optional: the full TrustMRR list of startups with payment-verified revenue (s0_trustmrr --mode api); without it "
                "the stage reads a public snapshot of ~1,000 top earners. Free with an account.",
        "where": "https://trustmrr.com (account settings, API key)",
    },
    "yandex_direct": {
        "keys": ("YANDEX_DIRECT_TOKEN",),
        "what": "Yandex Direct API Live 4 budget forecast: click prices for each niche's Russian queries (s8_direct_forecast, "
                "evidence). Free; needs an OAuth app with direct:api and an approved access request in Direct Pro (Tools > API).",
        "where": "https://oauth.yandex.ru (app), then https://oauth.yandex.ru/authorize?response_type=token&client_id=<ClientID>",
    },
    "vk": {
        "keys": ("VK_SERVICE_TOKEN", "VK_USER_TOKEN"),
        "what": "VK API: community sizes around each niche's topic (s8_vk_audience, evidence). The service key of a VK mini app "
                "never expires; the user token (only for groups.search) lives about a day - see sources/vk.py for the link.",
        "where": "https://dev.vk.com (new panel: create a mini app, Development > Access keys)",
    },
    "telegram": {
        "keys": ("TG_API_ID", "TG_API_HASH"),
        "what": "Telegram API: public group chats of each niche's users for the Russian buyer voice (s10_tg_*). Free; then log in "
                "once with `nf setup telegram` (QR code). Read-only: no chat is joined.",
        "where": "https://my.telegram.org (API development tools)",
    },
    "github": {
        "keys": ("GITHUB_TOKEN",),
        "what": "Optional: raises the GitHub search limit for s5_oss from 10 to 30 requests a minute. A token with no scopes is enough.",
        "where": "https://github.com/settings/tokens",
    },
}


class MissingKey(Exception):
    def __init__(self, names: tuple[str, ...] | list[str], purpose: str = ""):
        self.names = tuple(names)
        self.purpose = purpose
        hint = ""
        for g in GROUPS.values():
            if set(self.names) & set(g["keys"]):
                hint = f" {g['what']} Get it at {g['where']}."
                break
        super().__init__(f"missing {', '.join(self.names)}{(' for ' + purpose) if purpose else ''}. "
                         f"Add it to the workspace .env or the environment.{hint}")


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ without overriding variables that are already set."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and not os.environ.get(k):
            os.environ[k] = v


def get(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v else default


def require(*names: str, purpose: str = "") -> tuple[str, ...]:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise MissingKey(missing, purpose)
    return tuple(os.environ[n] for n in names)


def have(*names: str) -> bool:
    return all(os.environ.get(n) for n in names)
