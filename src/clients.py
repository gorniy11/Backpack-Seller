"""Steam, backpack.tf and Telegram clients. Writes are never retried automatically."""
from __future__ import annotations

import json
import math
import re
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import requests


class ServiceError(RuntimeError):
    def __init__(self, message: str, *, uncertain: bool = False, retry_after: int | None = None,
                 status_code: int | None = None, transient: bool = False):
        super().__init__(message)
        self.uncertain = uncertain
        self.retry_after = retry_after
        self.status_code = status_code
        self.transient = transient


def _numeric(value, label="ID") -> str:
    value = str(value)
    if not re.fullmatch(r"[0-9]{1,25}", value):
        raise ServiceError(f"Некорректный {label}.")
    return value


def _integer(value, label="ответ сервера") -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        raise ServiceError(f"Некорректный числовой {label}.") from None


def _retry_after(value):
    """Read Retry-After as seconds or an HTTP date."""
    value = str(value).strip()
    try:
        if re.fullmatch(r"[0-9]{1,10}", value):
            return int(value)
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return max(0, math.ceil(date.timestamp() - time.time()))
    except (TypeError, ValueError, OverflowError):
        return None


class _HTTP:
    service = "Сервис"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "BackpackSeller/1.1", "Accept": "application/json"})

    def _request(self, method, url, *, mutation=False, text=False, timeout=(10, 30),
                 profile_redirects=False, empty_delete_ok=False, **kwargs):
        response = None
        try:
            # Profile pages may redirect to a vanity URL. Writes must not follow redirects.
            for hop in range(5):
                response = self.session.request(method, url, timeout=timeout, allow_redirects=False, **kwargs)
                if response.status_code not in {301, 302, 303, 307, 308} or not profile_redirects:
                    break
                target = urljoin(url, response.headers.get("Location", ""))
                parsed = urlsplit(target)
                if (mutation or method != "GET" or not text or hop == 4
                        or not response.headers.get("Location")
                        or parsed.scheme != "https" or parsed.netloc != "steamcommunity.com"
                        or not re.fullmatch(r"/(?:profiles/[0-9]+|id/[A-Za-z0-9_\-]+)/?", parsed.path)):
                    raise ServiceError("Steam: не удалось проверить сессию. Войдите в Steam заново.")
                response.close()
                response = None
                url = target
            status = response.status_code
            if not 200 <= status < 300:
                retry = _retry_after(response.headers.get("Retry-After", ""))
                hints = {401: "нужна авторизация", 403: "доступ запрещён или сессия истекла", 404: "не найдено", 409: "конфликт операции", 429: "слишком много запросов; повторите позднее"}
                hint = hints.get(status, "ошибка сервера" if status >= 500 else "запрос отклонён")
                raise ServiceError(f"{self.service}: HTTP {status}, {hint}.", uncertain=mutation and status >= 500,
                                   retry_after=retry, status_code=status)
            if text:
                return response.text
            if status == 204 and method.upper() == "DELETE":
                return {"success": True}
            # backpack.tf can return an empty successful DELETE response.
            # Other operations still require a valid JSON response.
            empty_delete = empty_delete_ok and mutation and method.upper() == "DELETE" and status == 200
            if empty_delete and not response.text.strip():
                return {"success": True}
            try:
                result = response.json()
            except (ValueError, TypeError):
                raise ServiceError(f"{self.service}: получен некорректный ответ.", uncertain=mutation) from None
            if empty_delete and result is None:
                return {"success": True}
            if not isinstance(result, (dict, list)):
                raise ServiceError(f"{self.service}: неожиданный формат ответа.", uncertain=mutation)
            return result
        except requests.RequestException:
            raise ServiceError(f"{self.service}: соединение не удалось. Проверьте сеть и повторите проверку.", uncertain=mutation, transient=True) from None
        finally:
            if response is not None:
                response.close()

    def close(self):
        self.session.close()


class SteamClient(_HTTP):
    service = "Steam"
    COMMUNITY = "https://steamcommunity.com"
    API = "https://api.steampowered.com/IEconService"

    def __init__(self, config: dict, data_root: Path):
        super().__init__()
        self.config = config
        self.data_root = Path(data_root)
        self.steam_id = str(config.get("steam_id", "")).strip()
        self.session_file = self.data_root / "steam-session.bin"
        self.session_load_error = False
        if self.session_file.exists():
            try:
                from vault import unprotect
                cookies = json.loads(unprotect(self.session_file.read_bytes()).decode("utf-8"))
                self._install_cookies(cookies)
            except Exception:
                # A broken saved session must not prevent signing in again.
                self.session.cookies.clear()
                self.session_load_error = True

    def _owner(self, steam_id=None):
        owner = _numeric(self.steam_id if steam_id is None else steam_id, "SteamID64")
        if len(owner) != 17 or not owner.startswith("765"):
            raise ServiceError("Введите SteamID64 вашего аккаунта (17 цифр).")
        return owner

    def _install_cookies(self, cookies):
        if not isinstance(cookies, list):
            raise ValueError("Invalid session")
        jar = requests.cookies.RequestsCookieJar()
        owners = set()
        for cookie in cookies:
            if not isinstance(cookie, dict):
                raise ServiceError("Steam: сохранённая сессия повреждена. Выполните вход заново.")
            domain = str(cookie.get("domain", ""))
            if domain.lstrip(".") != "steamcommunity.com":
                continue
            name, value = str(cookie.get("name", "")), str(cookie.get("value", ""))
            if name == "steamLoginSecure":
                pieces = unquote(value).split("||", 1)
                if len(pieces) != 2 or not pieces[1]:
                    raise ServiceError("Steam: сохранённая сессия повреждена. Выполните вход заново.")
                owners.add(self._owner(pieces[0]))
            options = {"domain": domain, "path": cookie.get("path", "/"), "secure": bool(cookie.get("secure", True))}
            expires = cookie.get("expires")
            if isinstance(expires, (int, float)) and expires > 0:
                options["expires"] = int(expires)
            jar.set(name, value, **options)
        if len(owners) > 1:
            raise ServiceError("Steam: сессия содержит разные аккаунты. Выполните вход заново.")
        configured = str(self.config.get("steam_id", "")).strip()
        if configured and owners and owners != {self._owner(configured)}:
            raise ServiceError("Steam: сессия принадлежит другому аккаунту.")
        if owners:
            self.steam_id = next(iter(owners))
        self.session.cookies = jar

    def has_session(self):
        """Check local cookies; Steam may still reject an expired session."""
        try:
            self._session_id()
            return True
        except ServiceError:
            return False

    def session_identity(self):
        self._session_id()
        return self.steam_id

    def _session_id(self):
        self._owner()
        session_id = None
        owner = None
        for cookie in self.session.cookies:
            if cookie.domain.lstrip(".") != "steamcommunity.com":
                continue
            if cookie.is_expired():
                continue
            if cookie.name == "sessionid":
                session_id = cookie.value
            if cookie.name == "steamLoginSecure":
                candidate = unquote(cookie.value).split("||", 1)[0]
                if candidate != self.steam_id:
                    raise ServiceError("Steam: сессия принадлежит другому аккаунту.")
                owner = candidate
        if not session_id or owner != self.steam_id:
            if self.session_load_error:
                raise ServiceError("Steam: сохранённая сессия недоступна. Выполните вход заново.")
            raise ServiceError("Steam: сначала выполните вход в аккаунт.")
        return session_id

    def login(self):
        """Open Steam's login page and save the resulting session cookies."""
        configured = str(self.config.get("steam_id", "")).strip()
        if configured:
            self._owner(configured)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ServiceError("Для входа установите зависимости программы (Playwright).") from None
        self.data_root.mkdir(parents=True, exist_ok=True)
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(str(self.data_root / "browser"), channel="msedge", headless=False)
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    page.goto(self.COMMUNITY + "/login/home/", wait_until="domcontentloaded", timeout=60000)
                    deadline = time.monotonic() + 300
                    cookies = None
                    while time.monotonic() < deadline:
                        if not context.pages:
                            raise ServiceError("Окно Steam закрыто до завершения входа.")
                        current = context.cookies([self.COMMUNITY])
                        owners = {unquote(c["value"]).split("||", 1)[0] for c in current if c["name"] == "steamLoginSecure"}
                        if owners:
                            if len(owners) != 1:
                                raise ServiceError("Steam: в сессии обнаружены разные аккаунты. Выполните вход заново.")
                            owner = self._owner(next(iter(owners)))
                            if configured and owner != configured:
                                raise ServiceError("В Edge открыт другой аккаунт Steam. Войдите в указанный SteamID64.")
                            if any(c["name"] == "sessionid" for c in current):
                                cookies = current
                                break
                        page.wait_for_timeout(1000)
                    if cookies is None:
                        raise ServiceError("Время ожидания входа Steam истекло (5 минут).")
                    self._install_cookies(cookies)
                    self._check_session()
                    from vault import protect
                    encrypted = protect(json.dumps(cookies).encode("utf-8"))
                    temporary = self.session_file.with_suffix(".tmp")
                    temporary.write_bytes(encrypted)
                    temporary.replace(self.session_file)
                    self.session_load_error = False
                    return {"ok": True, "steam_id": self.steam_id}
                finally:
                    context.close()
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("Не удалось открыть или сохранить вход Steam. Установите Microsoft Edge, закройте другое окно входа и повторите.") from None

    def _api(self, endpoint, params=None):
        key = str(self.config.get("steam_api_key", "")).strip()
        if not key:
            raise ServiceError("Укажите Steam Web API Key в настройках.")
        payload = {"key": key, **(params or {})}
        body = self._request("GET", f"{self.API}/{endpoint}/v1/", params=payload)
        if not isinstance(body, dict) or not isinstance(body.get("response"), dict):
            raise ServiceError("Steam API: ответ не содержит данных. Проверьте API Key.")
        return body["response"]

    def inventory(self, steam_id=None):
        owner = self._owner(steam_id)
        assets, descriptions, seen_cursors, seen_assets = [], {}, set(), set()
        cursor = None
        total = None
        for _ in range(100):
            params = {"l": "english", "count": 2000}
            if cursor:
                params["start_assetid"] = cursor
            body = self._request("GET", f"{self.COMMUNITY}/inventory/{owner}/440/2", params=params)
            if not isinstance(body, dict) or body.get("success") != 1:
                raise ServiceError("Steam: инвентарь закрыт или временно недоступен; неполные данные не загружены.")
            page_assets, page_descriptions = body.get("assets", []), body.get("descriptions", [])
            if not isinstance(page_assets, list) or not isinstance(page_descriptions, list):
                raise ServiceError("Steam: некорректный ответ инвентаря.")
            if body.get("total_inventory_count") is not None:
                current_total = _integer(body["total_inventory_count"], "размер инвентаря")
                if total is not None and current_total != total:
                    raise ServiceError("Steam: инвентарь изменился при загрузке. Обновите список ещё раз.")
                total = current_total
            for asset in page_assets:
                asset_id = str(asset.get("assetid", ""))
                if not asset_id or asset_id in seen_assets:
                    raise ServiceError("Steam: страницы инвентаря пересекаются. Обновите список ещё раз.")
                seen_assets.add(asset_id)
                assets.append(asset)
            for description in page_descriptions:
                key = (str(description.get("classid")), str(description.get("instanceid", "0")))
                descriptions[key] = description
            if not body.get("more_items"):
                if total is not None and total != len(assets):
                    raise ServiceError("Steam: получен неполный инвентарь. Обновите список позднее.")
                return {"success": 1, "assets": assets, "descriptions": list(descriptions.values()), "total_inventory_count": len(assets), "steam_id": owner}
            cursor = str(body.get("last_assetid", ""))
            if not cursor or cursor in seen_cursors:
                raise ServiceError("Steam: не удалось дочитать все страницы инвентаря.")
            seen_cursors.add(cursor)
        raise ServiceError("Steam: превышен предел страниц инвентаря; неполные данные не используются.")

    def offers(self):
        offers, descriptions, cursors = {}, {}, set()
        cursor = 0
        for _ in range(100):
            body = self._api("GetTradeOffers", {"get_sent_offers": 0, "get_received_offers": 1, "get_descriptions": 1, "language": "english", "active_only": 1, "historical_only": 0, "cursor": cursor})
            for description in body.get("descriptions", []):
                key = (str(description.get("appid")), str(description.get("classid")), str(description.get("instanceid", "0")))
                descriptions[key] = description
            for offer in body.get("trade_offers_received", []):
                offers[str(offer["tradeofferid"])] = offer
            cursor = body.get("next_cursor", 0)
            if not cursor or str(cursor) == "0":
                result = list(offers.values())
                for offer in result:
                    offer["_descriptions"] = list(descriptions.values())
                return result
            if str(cursor) in cursors:
                raise ServiceError("Steam: повтор страницы предложений, загрузка остановлена.")
            cursors.add(str(cursor))
        raise ServiceError("Steam: не удалось дочитать предложения обмена.")

    def offer(self, offer_id):
        offer_id = _numeric(offer_id, "номер оффера")
        body = self._api("GetTradeOffer", {"tradeofferid": offer_id, "get_descriptions": 1, "language": "english"})
        offer = body.get("offer")
        if not isinstance(offer, dict) or str(offer.get("tradeofferid")) != offer_id:
            raise ServiceError("Steam: предложение не найдено.")
        offer["_descriptions"] = body.get("descriptions", [])
        return offer



    def _check_session(self):
        self._session_id()
        page = self._request("GET", f"{self.COMMUNITY}/profiles/{self.steam_id}/", text=True,
                             profile_redirects=True, headers={"Accept": "text/html"})
        match = re.search(r"\bg_steamID\s*=\s*[\"']([0-9]+)[\"']", page)
        if not match or match.group(1) != self.steam_id:
            raise ServiceError("Steam: сессия истекла или принадлежит другому аккаунту; войдите заново.")

    def check(self):
        self._check_session()
        self._api("GetTradeOffersSummary")
        return {"ok": True, "steam_id": self.steam_id, "message": "Steam: сессия и API доступны."}


class BackpackClient(_HTTP):
    service = "backpack.tf"
    BASE = "https://api.backpack.tf/api"

    def __init__(self, config):
        super().__init__()
        self.config = config

    def _call(self, method, path, *, mutation=False, params=None, body=None):
        token = str(self.config.get("backpack_token", "")).strip()
        if not token:
            raise ServiceError("Укажите backpack.tf User Token в настройках (не WebAPI Key).")
        for attempt in range(2):
            try:
                result = self._request(method, self.BASE + path, mutation=mutation,
                                       timeout=(15, 90 if mutation else 60),
                                       empty_delete_ok=method.upper() == "DELETE",
                                       params={"token": token, **(params or {})},
                                       **({"json": body} if body is not None else {}))
                break
            except ServiceError as error:
                # Retry reads only. A timed-out write may already have succeeded.
                if mutation or method.upper() != "GET" or attempt or not (error.transient or error.status_code in (502, 503, 504)):
                    raise
                time.sleep(1)
        if isinstance(result, dict) and (result.get("error") or result.get("success") is False or (result.get("reason") and result.get("message"))):
            raise ServiceError("backpack.tf: запрос отклонён. Проверьте токен, доступность предмета и лимит объявлений.", uncertain=mutation)
        return result

    @staticmethod
    def _listing(value):
        if not isinstance(value, dict):
            raise ServiceError("backpack.tf: некорректное объявление.", uncertain=True)
        result = dict(value)
        raw_id = value.get("id") or value.get("listing_id")
        listing_id = str(raw_id) if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", listing_id):
            raise ServiceError("backpack.tf: ответ не содержит ID объявления.", uncertain=True)
        result["listing_id"] = listing_id
        item = value.get("item") or {}
        asset = value.get("asset_id", value.get("assetid", item.get("id", "") if isinstance(item, dict) else ""))
        if not asset and listing_id.startswith("440_") and listing_id[4:].isdigit():
            asset = listing_id[4:]
        result["asset_id"] = str(asset)
        return result

    def create(self, asset_id, keys, metal_scrap, details):
        asset_id = _numeric(asset_id, "предмет")
        if type(keys) is not int or type(metal_scrap) is not int or keys < 0 or metal_scrap < 0 or keys + metal_scrap == 0:
            raise ServiceError("Укажите положительную цену в ключах и Refined Metal.")
        cents = metal_scrap * 100 // 9
        body = {"appid": 440, "id": asset_id, "intent": "sell", "currencies": {"keys": keys, "metal": cents / 100}, "details": str(details), "tradeOffersPreferred": True, "buyoutOnly": True}
        result = self._call("POST", "/v2/classifieds/listings", mutation=True, body=body)
        if isinstance(result, dict) and isinstance(result.get("result"), dict):
            result = result["result"]
        listing = self._listing(result)
        if listing.get("archived") or (listing["asset_id"] and listing["asset_id"] != asset_id):
            raise ServiceError("backpack.tf: объявление не опубликовано активно. Обновите список объявлений.", uncertain=True)
        return listing

    def delete(self, listing_id):
        listing_id = str(listing_id)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", listing_id):
            raise ServiceError("Некорректный ID объявления.")
        return self._call("DELETE", "/v2/classifieds/listings/" + listing_id, mutation=True)

    def update(self, listing_id, keys, metal_scrap, details):
        listing_id = str(listing_id)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", listing_id):
            raise ServiceError("Некорректный ID объявления.")
        if type(keys) is not int or type(metal_scrap) is not int or keys < 0 or metal_scrap < 0 or keys + metal_scrap == 0:
            raise ServiceError("Укажите положительную цену в ключах и Refined Metal.")
        cents = metal_scrap * 100 // 9
        body = dict(currencies={"keys": keys, "metal": cents / 100}, details=str(details))
        result = self._call("PATCH", "/v2/classifieds/listings/" + listing_id, mutation=True, body=body)
        if isinstance(result, dict) and isinstance(result.get("result"), dict):
            result = result["result"]
        listing = self._listing(result)
        if listing["listing_id"] != listing_id:
            raise ServiceError("backpack.tf: результат изменения требует сверки объявления.", uncertain=True)
        return listing

    def listing(self, listing_id):
        listing_id = str(listing_id)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", listing_id):
            raise ServiceError("Некорректное объявление backpack.tf.")
        try:
            body = self._call("GET", "/v2/classifieds/listings/" + listing_id)
        except ServiceError as error:
            if error.status_code == 404:
                return None
            raise
        result = self._listing(body)
        if result["listing_id"] != listing_id:
            raise ServiceError("backpack.tf: получено другое объявление; проверка отменена.")
        return result

    def pulse(self):
        return self._call("POST", "/agent/pulse", mutation=True)

    def stop(self):
        return self._call("POST", "/agent/stop", mutation=True)

    def listings(self):
        listings, seen, skip, expected_total = [], set(), 0, None
        for _ in range(100):
            body = self._call("GET", "/v2/classifieds/listings", params={"skip": skip, "limit": 100})
            if not isinstance(body, dict) or not isinstance(body.get("results"), list):
                raise ServiceError("backpack.tf: ответ не содержит списка объявлений.")
            batch, cursor = body["results"], body.get("cursor")
            if not isinstance(cursor, dict) or any(key not in cursor for key in ("total", "limit", "skip")):
                raise ServiceError("backpack.tf: не удалось подтвердить полноту списка объявлений.")
            values = [cursor[key] for key in ("total", "limit", "skip")]
            if any(isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)) for value in values):
                raise ServiceError("backpack.tf: некорректная страница объявлений.")
            total, limit, page_skip = map(int, values)
            if (limit <= 0 or page_skip != skip or total < skip
                    or len(batch) != min(limit, total - skip)
                    or expected_total is not None and total != expected_total):
                raise ServiceError("backpack.tf: не удалось дочитать полный список объявлений.")
            expected_total = total
            for value in batch:
                listing = self._listing(value)
                owner = str(listing.get("steamid", listing.get("steam_id", "")))
                configured = str(self.config.get("steam_id", ""))
                if owner and configured and owner != configured:
                    raise ServiceError("backpack.tf: токен принадлежит другому Steam-аккаунту.")
                if listing["listing_id"] in seen:
                    raise ServiceError("backpack.tf: повтор страницы объявлений; загрузка остановлена.")
                seen.add(listing["listing_id"])
                listings.append(listing)
            next_skip = skip + limit
            if next_skip >= total:
                return listings
            skip = next_skip
        raise ServiceError("backpack.tf: превышен предел страниц объявлений.")

    def check(self):
        values = self.listings()
        return {"ok": True, "listings": len(values), "message": "backpack.tf: токен доступен, объявления прочитаны."}


class TelegramClient(_HTTP):
    service = "Telegram"

    def __init__(self, config):
        super().__init__()
        self.config = config

    def _call(self, method, data=None, *, mutation=False, timeout=(10, 30)):
        token = str(self.config.get("telegram_token", "")).strip()
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
            raise ServiceError("Укажите Telegram Bot Token в настройках.")
        body = self._request("POST", f"https://api.telegram.org/bot{token}/{method}", json=data or {}, mutation=mutation, timeout=timeout)
        if not isinstance(body, dict) or body.get("ok") is not True:
            code = body.get("error_code") if isinstance(body, dict) else None
            hint = "закройте другой экземпляр бота с тем же токеном" if code == 409 else "проверьте токен, chat_id и запуск бота командой /start"
            raise ServiceError("Telegram: запрос отклонён; " + hint + ".", uncertain=mutation)
        return body.get("result")

    def send(self, text, buttons=None):
        chat_id = str(self.config.get("telegram_chat_id", "")).strip()
        if not re.fullmatch(r"-?[0-9]+", chat_id):
            raise ServiceError("Укажите числовой Telegram chat_id.")
        data = {"chat_id": chat_id, "text": str(text)[:4096], "disable_web_page_preview": True}
        if buttons is not None:
            data["reply_markup"] = {"inline_keyboard": buttons}
        return self._call("sendMessage", data, mutation=True)

    def poll(self, offset, timeout=0):
        timeout = min(25, max(0, int(timeout)))
        result = self._call("getUpdates", {"offset": int(offset), "timeout": timeout, "limit": 100, "allowed_updates": ["callback_query", "message"]}, timeout=(10, timeout + 15))
        if not isinstance(result, list):
            raise ServiceError("Telegram: некорректный список обновлений.")
        return result

    def answer(self, callback_id, text=""):
        return self._call("answerCallbackQuery", {"callback_query_id": str(callback_id), "text": str(text)[:200]}, mutation=True)

    def check(self):
        result = self._call("getMe")
        return {"ok": True, "username": result.get("username", "") if isinstance(result, dict) else "", "message": "Telegram: токен бота доступен."}
