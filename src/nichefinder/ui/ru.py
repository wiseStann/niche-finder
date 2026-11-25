"""Russian text of the console: group titles, stage summaries and the translation of the CLI's skip reasons.

The CLI and the stages speak English; the page `nf ui` serves is Russian. Everything the server sends to the page in
words goes through this module: `GROUP_TITLES`, `SUMMARY` (a stage missing here shows its English SUMMARY, so a new
stage works before it gets a translation) and `why()`, which turns the known one-line reasons of cli._readiness,
tools.check, keys.MissingKey and profiles.normalize into Russian and passes any other text through unchanged.
"""
from __future__ import annotations

import re
from typing import Callable

GROUP_TITLES = {
    "s0": "Вселенная продуктов", "s1": "Ниши", "s2": "Запросы", "s3": "Поисковый спрос", "exp": "Платные эксперименты",
    "s4": "Глубина тренда", "s5": "Глубина предложения", "s9": "Предложение во времени", "s6": "Балл и паспорта",
    "s8": "Спрос вне поиска", "s10": "Голос покупателя", "s7": "Лидерборд", "info": "Инфопродукты (свой балл)",
    "ru": "Российский B2B-модуль",
}

SUMMARY = {
    "s0_yc": "Свежие батчи Y Combinator (API yc-oss)",
    "s0_appstore_top": "Самые кассовые приложения App Store по жанрам (iTunes RSS)",
    "s0_producthunt": "Запуски Product Hunt: лучшие featured-посты за 12 месяцев (официальный API)",
    "s0_empireflippers": "Лоты Empire Flippers с подтверждённым P&L (прибыль, цена, статус)",
    "s0_tinyseed": "Портфель TinySeed (tinyseed.com/portfolio)",
    "s0_gplay_top": "Топ-чарты Google Play по категориям (US/RU)",
    "s0_wordpress": "Популярные плагины WordPress (официальный API)",
    "s0_shopify": "Приложения Shopify App Store по категориям",
    "s0_betalist": "Стартапы BetaList до запуска, сначала новые (betalist.com/startups)",
    "s0_productradar": "Product Radar: русскоязычные запуски по месяцам (productradar.ru)",
    "s0_kickstarter": "Проекты Kickstarter и статистика категорий из ежемесячного дампа Web Robots (~120 МБ)",
    "s0_trustmrr": "TrustMRR: стартапы с выручкой, подтверждённой платёжным провайдером (API с ключом, без него — "
                   "ограниченный публичный срез)",
    "s0_regulation": "Новые правила США и РФ, которые ставят малому бизнесу задачу комплаенса (разведка, LLM)",
    "s0_merge": "Сводит сырые источники в data/out/universe.csv",
    "s1_niches": "Проверяет niches.yaml и пишет обзор ниш",
    "s1_coverage": "Покрытие вселенной нишами и непокрытые кластеры",
    "s2_suggest": "Подсказки Google и Яндекса для якорных и категорийных запросов",
    "s2_wordstat": "Спрос в Яндекс Wordstat по всем русским запросам",
    "s3_dataforseo": "Объём поиска Google Ads, CPC и история за 48 месяцев из DataForSEO (США, мир, Россия)",
    "s3_metrics": "Метрики быстрого фильтра по нишам: спрос, CPC, тренд, концентрация брендов, гейты, балл",
    "s3_report": "Отчёт быстрого фильтра (reports/S3-quick-filter.md) и автоматический шорт-лист",
    "s3_switch_intent": "Намерение сменить продукт: объём запросов «<бренд> alternative» и «аналог <бренд>»",
    "s3_ai_volume": "Эксперимент: AI search volume DataForSEO против объёма Google Ads (США); вручную, в балл не идёт",
    "s4_trends": "Google Trends: средние по годам и вердикт для якорей шорт-листа, широких якорей и брендов",
    "s4_wordstat_dynamics": "Динамика Яндекс Wordstat за 36 месяцев по русским якорям",
    "s5_appstore": "Игроки App Store по нишам (iTunes Search API, релевантность по позиции и ручные исключения)",
    "s5_appstore_metrics": "Концентрация, доля новых и бесплатных приложений App Store по нишам",
    "s5_capterra": "Размеры категорий Capterra и концентрация отзывов (HTML через curl)",
    "s5_shopify_metrics": "Концентрация в Shopify App Store по подкатегориям ниш",
    "s5_pricing_b2b": "Цены B2B-продуктов из топа Capterra: данные страниц Capterra, затем карточки GetApp",
    "s5_pricing_b2c": "Цены встроенных покупок в топовых приложениях App Store (страницы apps.apple.com)",
    "s5_deals": "Сигналы сделок и запусков по нишам: Product Hunt, YC, TinySeed, кассовые приложения, BetaList, "
                "Product Radar, Kickstarter, Empire Flippers, TrustMRR",
    "s5_ai_substitute": "Проба ИИ-замены: заменяет ли продукт бесплатный ответ чат-бота (довод для G3, не гейт)",
    "s5_serp": "Кто владеет выдачей Google и сложность ключей по категорийным запросам (DataForSEO Labs)",
    "s5_ecosystems": "Предложение в Chrome Web Store и Atlassian Marketplace по нишам (справочно)",
    "s5_oss": "Open-source замены на GitHub по нишам (справочно)",
    "s5_merge": "Сводит сигналы S3–S5 по нишам шорт-листа в supply_deep.csv с гейтом S5",
    "s9_entrants": "Выживаемость новых приложений App Store (флаги E:churn / E:traction)",
    "s6_score": "Полный балл, гейты и автоматический вердикт для ниш шорт-листа",
    "s8_youtube_trends": "Интерес к теме ниши в поиске YouTube (Google Trends, gprop=youtube)",
    "s8_subreddit_stats": "Размеры сабреддитов по нишам (subredditstats.com)",
    "s8_appstore_velocity": "Скорость набора оценок в App Store и доля новичков",
    "s8_gplay_search": "Выдача Google Play по категорийным запросам",
    "s8_gplay_filter": "Отбор релевантных приложений Google Play по нишам (кандидаты по regex и LLM-проверка продукта)",
    "s8_gplay_details": "Карточки приложений Google Play: установки, оценки, дата выхода, цена",
    "s8_gplay_metrics": "Установки, игроки и концентрация в Google Play по нишам",
    "s8_hh": "Вакансии hh.ru с брендами ниш (косвенный признак внедрения в России)",
    "s8_hn_mentions": "Hacker News по нишам: запуски Show HN и вопросы Ask HN с трендом (API Algolia)",
    "s8_hn_hiring": "Объявления Hacker News «Who is hiring?» по нишам (API Algolia)",
    "ru_msp_counts": "Реестр МСП (открытые данные ФНС): число бизнесов по кодам ОКВЭД и их рост за год",
    "s8_who_counts": "Сколько целевых бизнесов существует: US Census CBP / Nonemployer и реестр МСП",
    "s8_freelance": "Платный спрос на биржах фриланса (заявки Kwork, проекты FL.ru) по нишам шорт-листа",
    "s8_vk_audience": "Сообщества VK по нишам: аудитория вокруг темы или ремесла (справочно; аналог размеров сабреддитов)",
    "s8_direct_forecast": "Прогноз бюджета Яндекс Директа по нишам: цены и число кликов по русским запросам (справочно)",
    "s8_offsearch": "Сводка спроса вне поиска и флаги по нишам",
    "s9_snapshot": "Фиксирует, обновляет и сравнивает снимки предложения (App Store, Google Play)",
    "s9_gplay_refresh": "Обновляет установки и оценки Google Play для приложений снимка",
    "s9_wayback": "История сайтов конкурентов в Wayback Machine: возраст и признаки жизни",
    "s5_advertisers": "Кто платит за трафик: реклама конкурентов в Google Ads Transparency Center (DataForSEO)",
    "s10_reddit_fetch": "Посты и комментарии Reddit по нишам из архива Arctic Shift",
    "s10_reddit_threads": "Ветки комментариев под найденными постами больших сабреддитов",
    "s10_reddit_classify": "LLM-разметка постов и комментариев Reddit: намерение, боль, смена продукта, готовность платить",
    "s10_reddit_metrics": "Метрики голоса покупателя на Reddit: тренд объёма, доля брендов, маркеры намерения",
    "s10_reddit_report": "Отчёт: голос покупателя на Reddit по нишам (правило вердикта, доля брендов, темы болей)",
    "s10_ru_reviews_fetch": "Русские отзывы о ведущих продуктах ниш: App Store, Google Play, Startpack",
    "s10_ru_reviews_classify": "LLM-разметка русских отзывов: о чём, намерение, боль, смена продукта, готовность платить",
    "s10_ru_reviews_report": "Отчёт: голос русских отзывов по нишам (вердикт внутри B2C/B2B, пробел по недовольным "
                             "отзывам, метка пейволла, темы болей)",
    "s10_yt_comments_fetch": "Комментарии YouTube под обучающими и обзорными видео ниш (голос покупателя; русские, "
                             "--lang en для английских)",
    "s10_yt_comments_classify": "LLM-разметка комментариев YouTube: о нише, боль, неудовлетворённая потребность, цена, "
                                "запрос продукта, вопрос, похвала",
    "s10_yt_comments_report": "Отчёт: голос покупателя в комментариях YouTube по нишам (вердикт внутри B2C/B2B, темы "
                              "потребностей, названные продукты)",
    "s10_tg_fetch": "Групповые чаты Telegram пользователей ниш: поиск публичных чатов и сообщения с названиями "
                    "инструментов (русский голос покупателя)",
    "s10_tg_classify": "LLM-разметка сообщений чатов Telegram: о нише или реклама, боль, неудовлетворённая потребность, "
                       "цена, запрос продукта, вопрос, похвала",
    "s10_tg_report": "Отчёт: голос покупателя в чатах Telegram по нишам (вердикт внутри B2C/B2B, темы потребностей, "
                     "названные продукты)",
    "s6_rescore": "Пересчёт балла с данными S8–S10 (второй проход s6_score)",
    "s6_ru": "Русскоязычный лидерборд (Wordstat и App Store RU)",
    "s6_ceiling": "Потолок снизу вверх и оценка пути к цели (A/B/B-/C)",
    "s6_passports": "Паспорта ниш (Markdown) и сводка лидерборда",
    "s7_html": "Автономный HTML-лидерборд с раскрывающимися паспортами",
    "info_discover": "Темы инфо-когорты из спроса Wordstat (основы намерений → темы от LLM → ранжирование)",
    "info_suggest": "Идеи тем инфо-когорты из подсказок YouTube (по областям-затравкам)",
    "info_youtube": "Метрики коротких видео по инфо-темам (YouTube Data API)",
    "info_telegram": "Воронки Telegram у инфо-тем: подписчики связанных каналов, платные ссылки",
    "info_ai": "Проба ИИ-замены для инфо-тем: заменяет ли микропродукт бесплатный ответ чат-бота",
    "info_paid": "Платный инфорынок по темам: курсы Stepik и книги Литрес (справочно, на балл не влияет)",
    "info_score": "Балл, вердикт и отчёт инфо-когорты",
    "ru_reestr": "Российский B2B: реестр отечественного ПО (предложение по нишам, карта классов)",
    "ru_zakupki": "Российский B2B: число госзакупок и суммы контрактов",
    "ru_bitrix": "Российский B2B: приложения Битрикс24 Маркета по нишам",
    "ru_hh": "Российский B2B: вакансии hh.ru на автоматизируемые роли и бренды",
    "ru_wordstat": "Российский B2B: бренды, категории и динамика в Wordstat",
    "ru_vendor_revenue": "Выручка российских вендоров ПО по открытой бухотчётности (открытые данные ФНС)",
    "ru_ecosystems": "Маркетплейсы приложений для МСП (МойСклад, amoCRM): приложения по нишам",
    "ru_report": "Российский B2B: балл и отчёт по пяти измерениям",
}

SPEC_KEYS = {"markets": "рынок", "side": "сегмент", "tier": "тир", "geo": "гео"}

_RULES: list[tuple[re.Pattern, str | Callable[[re.Match], str]]] = [
    (re.compile(r"^needs (\S+(?:, \S+)*) from https://my\.telegram\.org"),
     r"нужны \1 с https://my.telegram.org (API development tools) в .env воркспейса"),
    (re.compile(r"^needs ([^,\s]+)$"), r"нужен ключ \1"),
    (re.compile(r"^needs (.+)$"), r"нужны ключи \1"),
    (re.compile(r"^market (\w+) is off in the profile$"), r"рынок \1 выключен в профиле"),
    (re.compile(r"^market (\w+) is off in nf\.yaml$"), r"рынок \1 выключен в nf.yaml"),
    (re.compile(r"^market (\w+) is off$"), r"рынок \1 выключен"),
    (re.compile(r"^the Russian B2B module: the profile has no B2B niches$"),
     "российский B2B-модуль: в профиле нет B2B-ниш"),
    (re.compile(r"^Node\.js 18\+ is required for Google Play stages: (\S+)$"), r"для стадий Google Play нужен Node.js 18+: \1"),
    (re.compile(r"^google-play-scraper is not installed: run `nf setup node` (.*)$"),
     r"google-play-scraper не установлен: выполните `nf setup node` \1"),
    (re.compile(r"^(\S+) is not installed: (pip install .+)$"), r"\1 не установлен: \2"),
    (re.compile(r"^curl is required for some sources"), "нужен curl: установите его и добавьте в PATH"),
    (re.compile(r"^no Telegram session"),
     "нет сессии Telegram: выполните `nf setup telegram` и отсканируйте QR-код в приложении Telegram"),
    (re.compile(r"^missing ([^.]+?)(?: for [^.]+)?\. Add it to the workspace \.env or the environment\."),
     r"нет ключа \1: добавьте его в .env воркспейса или в окружение"),
    (re.compile(r"^not available: (.+)$", re.S), r"недоступна: \1"),
    (re.compile(r"^pick at least one (\w+)$"), lambda m: f"выберите хотя бы один {SPEC_KEYS.get(m[1], m[1])}"),
    (re.compile(r"^unknown (\w+): (.+) \(choose from (.+)\)$"),
     lambda m: f"неизвестный {SPEC_KEYS.get(m[1], m[1])}: {m[2]} (можно: {m[3]})"),
]


def why(text: str | None) -> str | None:
    """A known English reason in Russian; any other text unchanged (a stage's own failure message stays as it is)."""
    if not text:
        return text
    for rx, out in _RULES:
        m = rx.match(text)
        if m:
            return out(m) if callable(out) else m.expand(out)
    return text
