"""Listing and trade workflows, with local state saved before remote writes."""
from __future__ import annotations

import copy
import json
import os
import re
import hashlib
import threading
import time
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from string import Formatter

from clients import BackpackClient, ServiceError, SteamClient, TelegramClient
from domain import (format_price, parse_inventory, parse_price, refined_text,
                    validate_offer, offer_fingerprint, item_name, inventory_tags, STEAM_CDN)
from store import Store, InstanceLock
from vault import protect, unprotect


DEFAULTS = dict(steam_id="", steam_api_key="", backpack_token="", telegram_token="",
                telegram_chat_id="", telegram_user_id="", poll_interval=20,
                bump_enabled=False, bump_interval=30, language="ru", theme="light",
                description_template="Selling {name} for {price}. {paint} Send a trade offer.")
PENDING = {"accepting", "accept_unknown", "needs_confirmation", "confirmation_sent", "in_escrow", "decline_sent"}
TERMINAL = {3: "accepted", 4: "countered", 5: "expired", 6: "canceled", 7: "declined", 8: "invalid", 10: "canceled"}


class SellerEngine:
    def __init__(self, root, on_event=None, demo=False):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.instance = InstanceLock(self.root)
        self.store = Store(self.root)
        self.on_event = on_event or (lambda *args: None)
        self.lock = threading.RLock()
        self.demo = bool(demo)
        self.monitoring = False
        self.closed = False
        self.wakeup = threading.Event()
        self._agent_registered = False
        self._config = dict(DEFAULTS)
        path = self.root / "settings.bin"
        if path.exists() and not self.demo:
            try:
                loaded = json.loads(unprotect(path.read_bytes()).decode("utf-8"))
                self._config.update({key: value for key, value in loaded.items() if key in DEFAULTS})
                if any(key not in DEFAULTS for key in loaded):
                    temporary = path.with_suffix(".tmp")
                    temporary.write_bytes(protect(json.dumps(self._config, ensure_ascii=False).encode("utf-8")))
                    temporary.replace(path)
            except Exception:
                self.instance.close()
                self.store.close()
                raise RuntimeError("Не удалось расшифровать настройки. Откройте программу под прежней учётной записью Windows.") from None
        self._config["description_template"] = self._clean_display(self._config["description_template"])
        self._set_language(self._config.get("language", "ru"))
        self._clients()
        self._migrate_display()
        for row in self.store.listings():
            if row["status"] == "publishing":
                row["status"] = "publish_unknown"
                self.store.put("listings", row["asset_id"], row)
            elif row["status"] == "updating":
                row["status"] = "update_unknown"
                self.store.put("listings", row["asset_id"], row)
            elif row["status"] == "removing":
                row["status"] = "remove_unknown"
                self.store.put("listings", row["asset_id"], row)
        for row in self.store.offers():
            if row["status"] in PENDING:
                row["status"] = "manual"
                self.store.put("offers", row["offer_id"], row)
        for row in self.store.listings():
            if row.pop("reserved_by", None):
                self.store.put("listings", row["asset_id"], row)
        if self.demo:
            self._seed_demo()
        self.worker = threading.Thread(target=self._run, name="seller-monitor", daemon=True)
        self.worker.start()
        self.log("Демонстрационный режим. Сеть и реальные операции отключены." if demo else
                 "Готово. Наблюдение остановлено. Подтверждения обменов выполняются вручную в Steam.")

    def _clients(self):
        self.steam = SteamClient(self._config, self.root)
        self.backpack = BackpackClient(self._config)
        self.telegram = TelegramClient(self._config)

    @staticmethod
    def _set_language(language):
        from i18n import set_language
        set_language(language if language in {"ru", "en"} else "ru")

    def _translate(self, value):
        from i18n import translate
        return translate(value, self._config.get("language", "ru"))

    def emit(self, kind="changed", payload=None):
        self.on_event(kind, payload)

    def log(self, message):
        message = self._clean_display(message)
        self.store.log(message)
        self.emit("log", message)

    @staticmethod
    def _clean_display(text):
        text = re.sub(r"(?i)\basset\s*id\s*:?\s*(?:\{asset_id\}|\d+)?", "", str(text))
        text = text.replace("{asset_id}", "")
        return re.sub(r"(?i)\bscraps?\b", "металл", text).strip(" ·\n")

    def _migrate_display(self):
        for row in self.store.listings():
            row.pop("auto_accept", None)
            row["details"] = self._clean_display(row.get("details", ""))
            cached = self.store.get("inventory", row["asset_id"], {})
            if cached.get("description"):
                row["name"] = item_name(cached["description"])
            self.store.put("listings", row["asset_id"], row)
        for row in self.store.offers():
            for key in ("token", "expires", "message_id", "notified"):
                row.pop(key, None)
            row["summary"] = self._summary(row["raw"], row["raw"].get("_descriptions", [])) if row.get("raw") else self._clean_display(row.get("summary", ""))
            row["reason"] = self._clean_display(row.get("reason", ""))
            self.store.put("offers", row["offer_id"], row)
        for row in self.store.inventory_rows():
            row.pop("auto_accept", None)
            if row.get("description"):
                row["name"] = item_name(row["description"])
                row["filter_tags"] = inventory_tags(row["description"])
            if row.get("icon_path") and not re.match(r"(?:[a-z]+:)?//", row["icon_path"], re.I):
                row["icon_url"] = STEAM_CDN + row["icon_path"] + "/256fx256f"
            self.store.put("inventory", row["asset_id"], row)
        with self.store.lock, self.store.db:
            self.store.db.execute("DELETE FROM meta WHERE id LIKE 'item_auto:%' OR id LIKE 'market:%'")
            logs = self.store.db.execute("SELECT id,message FROM logs").fetchall()
            self.store.db.executemany("UPDATE logs SET message=? WHERE id=?",
                                     [(self._clean_display(text), key) for key, text in logs])
            notices = self.store.db.execute("SELECT id,data FROM outbox").fetchall()
            for key, data in notices:
                notice = json.loads(data)
                notice["text"] = self._clean_display(notice["text"])
                if key.startswith(("confirm:", "confirm-error:")) or any("callback_data" in button for line in notice.get("buttons") or [] for button in line):
                    notice.update(sent=True, canceled=True, buttons=None)
                self.store.db.execute("UPDATE outbox SET data=? WHERE id=?", (json.dumps(notice, ensure_ascii=False), key))

    def settings(self):
        with self.lock:
            return copy.deepcopy(self._config)

    @staticmethod
    def _validate_preferences(language, theme):
        if language not in {"ru", "en"}:
            raise ValueError("Выберите русский или английский язык.")
        if theme not in {"light", "dark"}:
            raise ValueError("Выберите светлую или тёмную тему.")

    def set_preferences(self, language=None, theme=None):
        """Save language and theme without reconnecting services or resetting forms."""
        with self.lock:
            cfg = {**self._config}
            cfg["language"] = cfg["language"] if language is None else language
            cfg["theme"] = cfg["theme"] if theme is None else theme
            self._validate_preferences(cfg["language"], cfg["theme"])
            if not self.demo:
                temporary = self.root / "settings.tmp"
                temporary.write_bytes(protect(json.dumps(cfg, ensure_ascii=False).encode("utf-8")))
                os.replace(temporary, self.root / "settings.bin")
            self._config = cfg
            self._set_language(cfg["language"])
            preferences = {"language": cfg["language"], "theme": cfg["theme"]}
            self.emit("preferences_changed", preferences)
            return preferences

    def save_settings(self, values):
        with self.lock:
            cfg = {**self._config, **{k: v for k, v in values.items() if k in DEFAULTS}}
            for key in DEFAULTS:
                if isinstance(DEFAULTS[key], str):
                    cfg[key] = str(cfg[key]).strip()
            if cfg["steam_id"] and not re.fullmatch(r"7656119\d{10}", cfg["steam_id"]):
                raise ValueError("SteamID64 должен состоять из 17 цифр и начинаться с 7656119.")
            if cfg["steam_api_key"] and not re.fullmatch(r"[a-fA-F0-9]{32}", cfg["steam_api_key"]):
                raise ValueError("Steam API Key: ожидаются 32 шестнадцатеричных символа.")
            if cfg["telegram_chat_id"] and not re.fullmatch(r"[1-9]\d*", cfg["telegram_chat_id"]):
                raise ValueError("Укажите положительный chat_id личного чата Telegram.")
            if cfg["telegram_user_id"] and not re.fullmatch(r"[1-9]\d*", cfg["telegram_user_id"]):
                raise ValueError("Telegram user_id должен быть положительным числом.")
            try:
                cfg["poll_interval"] = int(cfg["poll_interval"])
            except (ValueError, TypeError):
                raise ValueError("Интервал проверки — целое число от 15 до 3600 секунд.") from None
            if not 15 <= cfg["poll_interval"] <= 3600:
                raise ValueError("Интервал проверки — от 15 до 3600 секунд.")
            try:
                cfg["bump_interval"] = int(cfg["bump_interval"])
            except (ValueError, TypeError):
                raise ValueError("Интервал бампа — целое число минут от 30 до 1440.") from None
            if not 30 <= cfg["bump_interval"] <= 1440:
                raise ValueError("Интервал бампа — от 30 до 1440 минут.")
            cfg["bump_enabled"] = bool(cfg["bump_enabled"])
            self._validate_preferences(cfg["language"], cfg["theme"])
            if cfg["steam_id"] != self._config["steam_id"] and (self.store.listings() or self.store.offers()):
                raise ValueError("Для другого Steam-аккаунта используйте отдельную папку данных.")
            cfg["description_template"] = self._clean_display(cfg["description_template"])
            try:
                if any(field not in {None, "name", "price", "paint"} for _, field, _, _ in Formatter().parse(cfg["description_template"])):
                    raise ValueError()
                cfg["description_template"].format(name="Item", price="1 key", paint="")
            except (KeyError, ValueError, IndexError, AttributeError):
                raise ValueError("В шаблоне разрешены поля {name}, {price}, {paint}.") from None
            if len(cfg["description_template"]) > 1200:
                raise ValueError("Шаблон описания слишком длинный (максимум 1200 символов).")
            if not self.demo:
                temp = self.root / "settings.tmp"
                temp.write_bytes(protect(json.dumps(cfg, ensure_ascii=False).encode("utf-8")))
                os.replace(temp, self.root / "settings.bin")
            self._config = cfg
            self._set_language(cfg["language"])
            if self._agent_registered and not cfg["bump_enabled"]:
                try:
                    self.backpack.stop()
                except ServiceError:
                    pass
                self._agent_registered = False
            for client in (self.steam, self.backpack, self.telegram):
                client.close()
            self._clients()
            self.log("Настройки сохранены.")
            self.emit("settings_changed", self.settings())
            self.wakeup.set()

    def login(self):
        if self.demo:
            return "Демо: вход в Steam отключён."
        with self.lock:
            result = self.steam.login()
            owner = str(result.get("steam_id") or self.steam.steam_id)
            self.save_settings({"steam_id": owner})
            self.log("Steam-сессия сохранена в защищённом хранилище.")
            self.refresh_inventory()
            return dict(steam_id=owner, inventory_loaded=True)

    def ensure_inventory(self):
        with self.lock:
            if self.demo or not self.steam.has_session():
                return False
            if not self._config["steam_id"]:
                self.save_settings({"steam_id": self.steam.steam_id})
            self.refresh_inventory()
            return True



    def refresh_inventory(self):
        with self.lock:
            if self.demo:
                self.emit()
                return
            rows = parse_inventory(self.steam.inventory())
            sold = {row["asset_id"] for row in self.store.listings() if row["status"] == "sold"}
            rows = [row for row in rows if row["asset_id"] not in sold]
            self.store.replace_inventory(rows)
            self.log(f"Загружен инвентарь: {len(rows)} обмениваемых предметов.")
            self.emit()

    def publish(self, asset_id, keys, metal, details=""):
        with self.lock:
            if self.demo:
                raise ValueError("Демонстрация: публикация отключена.")
            asset_id = str(asset_id)
            price = parse_price(keys, metal)
            previous = self.store.get("listings", asset_id)
            if (previous and previous.get("reserved_by")) or self._pending_asset(asset_id):
                raise ValueError("Предмет участвует в незавершённом обмене.")
            # A previous POST may have succeeded even if its response was lost.
            # Check the full listing set before creating another one.
            remote = self.backpack.listings()
            found, conflicting = self._find_remote_listing(remote, asset_id, previous)
            if conflicting:
                raise ValueError("Не удалось однозначно сверить объявление. Обновите список объявлений backpack.tf.")
            if found:
                if previous:
                    self._reconcile_listing(previous, remote)
                self.emit()
                raise ValueError("Этот предмет уже выставлен на backpack.tf. Сначала снимите объявление.")
            # Recheck ownership before publishing; leave the displayed inventory alone.
            item = next((row for row in parse_inventory(self.steam.inventory()) if row["asset_id"] == asset_id), None)
            if not item or not item.get("tradable") or item.get("amount") != "1":
                raise ValueError("Точный предмет отсутствует в свежем обмениваемом инвентаре.")
            details = self._clean_display(details.strip()) or self._config["description_template"].format(
                name=item["name"], price=format_price(**price), paint=item.get("paint", ""))
            if len(details) > 1600:
                raise ValueError("Описание слишком длинное (максимум 1600 символов).")
            row = dict(asset_id=asset_id, name=item["name"], **price, details=details,
                       status="publishing", listing_id="", version=(previous or {}).get("version", 0) + 1,
                       account=self._config["steam_id"])
            self.store.put("listings", asset_id, row)
            try:
                result = self.backpack.create(asset_id, price["keys"], price["metal_scrap"], details)
                row.update(status="active", listing_id=str(result["listing_id"]))
            except ServiceError as error:
                row["status"] = "publish_unknown" if getattr(error, "uncertain", False) else "error"
                self.store.put("listings", asset_id, row)
                # Recover a lost response by reading, not by repeating the POST.
                try:
                    remote = self.backpack.listings()
                    found, conflict = self._find_remote_listing(remote, asset_id, row)
                    if found and not conflict and self._remote_price(found) == price:
                        row.update(status="active", listing_id=self._listing_id(found))
                    else:
                        if found or conflict:
                            row["status"] = "external_change"
                        self.store.put("listings", asset_id, row)
                        self.emit()
                        raise error
                except ServiceError:
                    self.emit()
                    raise error
            self.store.put("listings", asset_id, row)
            self.log(f"Объявление опубликовано: {item['name']} · {format_price(**price)}.")
            self.emit()





    def remove_listing(self, asset_id):
        with self.lock:
            if self.demo:
                raise ValueError("Демонстрация: удаление отключено.")
            row = self.store.get("listings", asset_id)
            if not row or row.get("reserved_by") or self._pending_asset(asset_id):
                raise ValueError("Объявление не найдено или предмет участвует в незавершённом обмене.")
            # The previous DELETE may have worked despite a lost response.
            remote = self.backpack.listings()
            found, conflicting = self._find_remote_listing(remote, str(asset_id), row, deleting=True)
            if conflicting:
                raise ValueError("Не удалось однозначно сверить объявление. Удаление не отправлено.")
            if found:
                row.update(status="removing", listing_id=self._listing_id(found))
                self.store.put("listings", asset_id, row)
                try:
                    self.backpack.delete(row["listing_id"])
                except ServiceError as error:
                    row["status"] = "remove_unknown"
                    self.store.put("listings", asset_id, row)
                    try:
                        after = self.backpack.listings()
                        remaining, conflict = self._find_remote_listing(after, str(asset_id), row, deleting=True)
                    except ServiceError:
                        self.emit()
                        raise error
                    if remaining or conflict:
                        self.emit()
                        raise error
            row.update(status="removed", version=row.get("version", 1) + 1)
            self.store.put("listings", asset_id, row)
            self.log(f"Объявление снято: {row.get('name', 'Предмет')}.")
            self.emit()

    def _pending_asset(self, asset_id):
        return any(str(asset_id) in {str(value) for value in offer.get("asset_ids", [])}
                   for offer in self.store.offers() if offer.get("status") in PENDING)

    def relist(self, asset_id, keys, metal, details=""):
        """Update an existing listing, or publish it again if it was removed.

        A lost PATCH response triggers a read to check the result, never a retry.
        """
        with self.lock:
            if self.demo:
                raise ValueError("Демонстрация: перевыставление отключено.")
            asset_id = str(asset_id)
            previous = self.store.get("listings", asset_id)
            if (previous and previous.get("reserved_by")) or self._pending_asset(asset_id):
                raise ValueError("Предмет участвует в незавершённом обмене.")
            price = parse_price(keys, metal)
            details = self._clean_display(str(details).strip())
            if len(details) > 1600:
                raise ValueError("Описание слишком длинное (максимум 1600 символов).")
            remote = self.backpack.listings()
            found, conflict = self._find_remote_listing(remote, asset_id, previous)
            if conflict:
                raise ValueError("Не удалось однозначно сверить объявление. Обновите список объявлений backpack.tf.")
            if not found:
                self.publish(asset_id, keys, metal, details)
                return "Объявление опубликовано заново."
            row = self._synchronize_sale(previous, found)
            target = dict(**price, details=details)
            row.update(status="updating", update_target=target)
            self.store.put("listings", asset_id, row)
            operation_error = None
            try:
                self.backpack.update(row["listing_id"], price["keys"], price["metal_scrap"], details)
            except ServiceError as error:
                operation_error = error
            row["status"] = "update_unknown"
            self.store.put("listings", asset_id, row)
            try:
                after = self.backpack.listings()
                current, conflict = self._find_remote_listing(after, asset_id, row)
            except ServiceError:
                self.emit()
                if operation_error:
                    raise operation_error
                raise ServiceError("backpack.tf: результат изменения требует сверки. Повторное изменение не отправлено.", uncertain=True) from None
            if (not current or conflict or self._remote_price(current) != price
                    or self._clean_display(current.get("details") or "") != details):
                self._reconcile_listing(row, after)
                self.emit()
                if operation_error:
                    raise operation_error
                raise ServiceError("backpack.tf: новые условия объявления пока не подтверждены. Обновите список объявлений.", uncertain=True)
            self._synchronize_sale(row, current)
            self.log(f"Объявление обновлено: {row['name']} · {format_price(**price)}.")
            self.emit()
            return "Объявление перевыставлено с новыми условиями."

    def start(self):
        with self.lock:
            if self.monitoring:
                return
            if not self.demo:
                if not self._config["steam_id"] or not self._config["steam_api_key"] or not self._config["backpack_token"]:
                    raise ValueError("Сохраните SteamID64, Steam API Key и backpack.tf User Token.")
                if not self._telegram_ready():
                    raise ValueError("Для уведомлений сохраните Telegram token и личный chat_id.")
                self.steam.check()
                self.reconcile_listings()
            self.monitoring = True
            self.wakeup.set()
            self.log("Наблюдение запущено.")
            self.emit("running", True)

    def stop(self):
        self.monitoring = False
        self.wakeup.set()
        self.log("Наблюдение остановлено. Уже отправленная операция продолжает сверяться при следующем запуске.")
        self.emit("running", False)

    @staticmethod
    def _remote_price(row):
        money = row.get("currencies") or {}
        if not isinstance(money, dict) or any(key not in {"keys", "metal"} and value not in (0, "0", None) for key, value in money.items()):
            return None
        try:
            metal = Decimal(str(money.get("metal", 0)))
            text = str(int(metal)) if metal == int(metal) else format(metal, ".2f")
            if Decimal(text) != metal:
                raise ValueError()
            return parse_price(str(money.get("keys", 0)), text)
        except (ValueError, TypeError, InvalidOperation, OverflowError):
            return None

    @staticmethod
    def _listing_id(row):
        return str(row.get("listing_id", row.get("id", "")))

    def _remote_owned_tf2(self, row):
        item = row.get("item") if isinstance(row.get("item"), dict) else {}
        if any(str(value) != "440" for value in (row.get("appid", 440), item.get("appid", 440))):
            return False
        if item.get("id") not in (None, "") and str(item["id"]) != str(row.get("asset_id", "")):
            return False
        configured = str(getattr(self, "_config", {}).get("steam_id", ""))
        owner = str(row.get("steamid") or row.get("steam_id") or "")
        return not owner or not configured or owner == configured

    def _remote_active_sale(self, row):
        return (self._remote_owned_tf2(row) and row.get("intent") in ("sell", 1, "1")
                and not row.get("archived") and row.get("status", "active") == "active"
                and row.get("source", "steam") in {"steam", "user", "userAgent", "backpackTf", "backpack.tf"})

    def _find_remote_listing(self, remote, asset_id, local=None, *, deleting=False):
        """Match the owned item, not just its name."""
        expected = str((local or {}).get("listing_id") or f"440_{asset_id}")
        candidates = []
        conflict = False
        for found in remote:
            same_asset = str(found.get("asset_id", "")) == str(asset_id)
            same_id = self._listing_id(found) == expected
            if not same_asset and not same_id:
                continue
            # Old rows without intent can be deleted, but cannot authorize a sale.
            intent = found.get("intent")
            intent_ok = intent in ("sell", 1, "1") or (deleting and intent is None)
            active = self._remote_active_sale(found)
            if same_asset and intent_ok and (deleting or active):
                candidates.append(found)
            elif same_id:
                conflict = True
        if len(candidates) > 1:
            return None, True
        return (candidates[0] if candidates else None), conflict

    def _listing_name(self, asset_id, remote, previous):
        inventory = self.store.get("inventory", asset_id, {})
        description = inventory.get("description") or {}
        canonical = item_name(description) if description else inventory.get("name")
        item = remote.get("item") if isinstance(remote.get("item"), dict) else {}
        return canonical or item_name({"market_name": item.get("marketName") or item.get("name") or item.get("baseName")}) or previous.get("name") or "Предмет TF2"

    def _synchronize_sale(self, previous, remote, *, pending_owner=None):
        """Import a listing while preserving the price locked by a pending trade."""
        asset_id = str(remote["asset_id"])
        row = copy.deepcopy(previous or {})
        price = self._remote_price(remote)
        reserved = row.get("reserved_by") or pending_owner
        current_policy = (row.get("keys"), row.get("metal_scrap"), row.get("listing_id"), row.get("status"))
        if reserved:
            row.setdefault("asset_id", asset_id)
            row.setdefault("name", self._listing_name(asset_id, remote, row))
            row.setdefault("keys", 0)
            row.setdefault("metal_scrap", 0)
            row.setdefault("version", 1)
            if not previous:
                row["price_supported"] = False
                row["account"] = str(getattr(self, "_config", {}).get("steam_id", "")
                                     or remote.get("steamid") or remote.get("steam_id") or "")
                if isinstance(remote.get("item"), dict):
                    row["backpack_item"] = copy.deepcopy(remote["item"])
            row["reserved_by"] = str(reserved)
            same_policy = (price == {"keys": row.get("keys"), "metal_scrap": row.get("metal_scrap")}
                           and self._listing_id(remote) == row.get("listing_id"))
            if not same_policy:
                row["status"] = "external_change"
            row["observed_currencies"] = copy.deepcopy(remote.get("currencies"))
            row["observed_details"] = self._clean_display(remote.get("details") or "")
        else:
            row.pop("update_target", None)
            row.update(asset_id=asset_id, name=self._listing_name(asset_id, remote, row),
                       listing_id=self._listing_id(remote),
                       account=str(getattr(self, "_config", {}).get("steam_id", "")
                                   or remote.get("steamid") or remote.get("steam_id") or ""),
                       details=self._clean_display(remote.get("details") or ""),
                       last_bumped_at=remote.get("bumpedAt"),
                       price_supported=price is not None,
                       remote_currencies=copy.deepcopy(remote.get("currencies")),
                       imported=True, status="active" if price is not None else "unsupported_price")
            if isinstance(remote.get("item"), dict):
                row["backpack_item"] = copy.deepcopy(remote["item"])
            if price is not None:
                row.update(price)
            else:
                row.setdefault("keys", 0)
                row.setdefault("metal_scrap", 0)
            new_policy = (row.get("keys"), row.get("metal_scrap"), row.get("listing_id"), row.get("status"))
            row["version"] = int(row.get("version", 0)) + (not previous or current_policy != new_policy)
        row["last_synced_at"] = time.time()
        self.store.put("listings", asset_id, row)
        return row

    def _reconcile_listing(self, row, remote, *, pending_owner=None):
        removing = row["status"] in {"removing", "remove_unknown"}
        found, conflict = self._find_remote_listing(remote, row["asset_id"], row, deleting=removing)
        if removing:
            row["status"] = "remove_unknown" if found or conflict else "removed"
        elif found and not conflict:
            return self._synchronize_sale(row, found, pending_owner=pending_owner)
        elif conflict or row.get("reserved_by") or pending_owner:
            row["status"] = "external_change"
            if pending_owner and not row.get("reserved_by"):
                row["reserved_by"] = str(pending_owner)
        elif row["status"] in {"active", "external_change", "error", "unsupported_price", "updating", "update_unknown"}:
            row["status"] = "removed"
            row.pop("update_target", None)
        # An uncertain POST needs a user decision; syncing must not replay it.
        self.store.put("listings", row["asset_id"], row)
        return row

    def reconcile_listings(self):
        with self.lock:
            if self.demo:
                self.emit()
                return {}
            remote = self.backpack.listings()
            configured = str(getattr(self, "_config", {}).get("steam_id", ""))
            if configured and any(str(row.get("steamid") or row.get("steam_id") or configured) != configured for row in remote):
                raise ServiceError("backpack.tf: токен принадлежит другому Steam-аккаунту.")
            pending = {str(asset_id): str(offer.get("offer_id", ""))
                       for offer in self.store.offers() if offer.get("status") in PENDING
                       for asset_id in offer.get("asset_ids", [])}
            previous = {str(row["asset_id"]): row for row in self.store.listings()}
            imported = updated = 0
            for row in previous.values():
                if row["status"] in {"active", "publishing", "publish_unknown", "external_change", "error", "removing", "remove_unknown", "unsupported_price", "removed", "updating", "update_unknown"}:
                    before = copy.deepcopy(row)
                    synced = self._reconcile_listing(row, remote, pending_owner=pending.get(str(row["asset_id"])))
                    updated += synced != before
            for found in remote:
                asset_id = str(found.get("asset_id", ""))
                if (not self._remote_active_sale(found) or not re.fullmatch(r"[0-9]{1,25}", asset_id)
                        or not 0 < int(asset_id) <= 2**64 - 1 or asset_id in previous):
                    continue
                # New listings need a matching owner. Older tracked rows may omit it.
                owner = str(found.get("steamid") or found.get("steam_id") or "")
                if not re.fullmatch(r"765[0-9]{14}", owner):
                    continue
                duplicates = [candidate for candidate in remote if self._remote_active_sale(candidate)
                              and str(candidate.get("asset_id", "")) == asset_id]
                if len(duplicates) != 1:
                    continue
                self._synchronize_sale(None, found, pending_owner=pending.get(asset_id))
                imported += 1
            self._last_import_stats = dict(imported=imported, updated=updated)
            self.emit()
            return {self._listing_id(row): row for row in remote}

    def import_listings(self):
        with self.lock:
            if self.demo:
                return "Демо: показаны примеры ваших объявлений."
            self.reconcile_listings()
            rows = self.store.listings()
            active = sum(row.get("status") == "active" for row in rows)
            unsupported = sum(row.get("status") == "unsupported_price" for row in rows)
            message = f"Объявления загружены. Активных: {active}. Новых: {self._last_import_stats['imported']}."
            if unsupported:
                message += f" С неподдерживаемой ценой: {unsupported}."
            self.log(message)
            return message

    def bump_status(self):
        with self.lock:
            return copy.deepcopy(self.store.get("meta", "bump_state", {}))

    def _bump_deadline(self, state):
        attempted = float(state.get("last_attempt_at", 0))
        return max(float(state.get("next_allowed_at", 0)),
                   attempted + self._config["bump_interval"] * 60 if attempted > 0 else 0)

    def bump_now(self):
        with self.lock:
            if self.demo:
                return "Демо: бамп отключён."
            if not self._config.get("steam_id") or not self._config.get("backpack_token"):
                raise ValueError("Сохраните SteamID64 и backpack.tf User Token.")
            now = time.time()
            state = self.store.get("meta", "bump_state", {})
            deadline = self._bump_deadline(state)
            if now < deadline:
                seconds = max(1, int(deadline - now) + 1)
                raise ServiceError(f"backpack.tf: следующий бамп доступен через {seconds} сек.", retry_after=seconds)
            self.reconcile_listings()
            eligible = [row for row in self.store.listings()
                        if row.get("status") in {"active", "unsupported_price"} and not row.get("reserved_by")]
            if not eligible:
                state.update(next_allowed_at=now + self._config["bump_interval"] * 60, last_check_at=now)
                self.store.put("meta", "bump_state", state)
                return "Нет активных объявлений для бампа."
            # Save the cooldown first so a restart cannot immediately repeat the bump.
            state.update(last_attempt_at=now, next_allowed_at=now + self._config["bump_interval"] * 60,
                         status="sending", error="")
            self.store.put("meta", "bump_state", state)
            try:
                self.backpack.pulse()
            except ServiceError as error:
                state.update(status="unknown" if error.uncertain else "error", error=str(error),
                             next_allowed_at=max(state["next_allowed_at"], time.time() + (error.retry_after or 0)))
                self.store.put("meta", "bump_state", state)
                self.emit()
                raise
            self._agent_registered = True
            state.update(status="requested", last_success_at=time.time())
            self.store.put("meta", "bump_state", state)
            message = "Запрос бампа отправлен. Доступность бампа определяет backpack.tf."
            self.log(message)
            self.emit()
            return message

    def _bump_tick(self):
        if self.demo or not self._config["bump_enabled"] or not self._config["backpack_token"] or not self._config["steam_id"]:
            return
        state = self.bump_status()
        deadline = self._bump_deadline(state)
        if time.time() >= deadline:
            self.bump_now()

    def _validated(self, offer):
        descriptions = list(offer.get("_descriptions") or [])
        result = validate_offer(offer, self.store.listings(), descriptions)
        if not result.valid and offer.get("items_to_receive"):
            # The Web API sometimes omits def_index; use Steam inventory metadata then.
            if any(not (d.get("app_data") or {}).get("def_index", (d.get("app_data") or {}).get("defindex"))
                   for d in descriptions) or not descriptions:
                partner = str(76561197960265728 + int(offer.get("accountid_other", 0)))
                try:
                    inventory = self.steam.inventory(partner)
                    descriptions = inventory.get("descriptions", [])
                    result = validate_offer(offer, self.store.listings(), descriptions)
                except ServiceError:
                    # One unavailable buyer inventory must not block other offers.
                    pass
        for asset_id in result.asset_ids:
            row = self.store.get("listings", asset_id)
            if row and row.get("reserved_by") not in (None, "", str(offer["tradeofferid"])):
                return result, descriptions, "Предмет уже зарезервирован другим обменом."
        return result, descriptions, ""

    def _summary(self, offer, descriptions):
        mapping = {f"{d.get('classid')}_{d.get('instanceid', '0')}": d for d in descriptions}
        lines = [f"Предложение #{offer['tradeofferid']}"]
        currency_names = {5021: "Mann Co. Supply Crate Key", 5002: "Refined Metal",
                          5001: "Reclaimed Metal", 5000: "Металлолом"}
        for field, title in (("items_to_give", "Ваши предметы"), ("items_to_receive", "Покупатель предлагает")):
            counts = Counter()
            for asset in offer.get(field, []):
                item = self.store.get("inventory", asset.get("assetid"), {})
                desc = mapping.get(f"{asset.get('classid')}_{asset.get('instanceid', '0')}", {})
                listing = self.store.get("listings", asset.get("assetid"), {})
                canonical = item_name(desc) if desc.get("market_name") or desc.get("market_hash_name") else ""
                name = canonical or item.get("name") or listing.get("name") or item_name(desc) or "Неизвестный предмет"
                if field == "items_to_give" and item.get("paint"):
                    name += " (" + item["paint"] + ")"
                if field == "items_to_receive":
                    try:
                        name = currency_names.get(int((desc.get("app_data") or {}).get("def_index", desc.get("defindex", -1))), name)
                    except (TypeError, ValueError):
                        pass
                try:
                    amount = int(asset.get("amount", 1))
                    if amount < 1:
                        raise ValueError()
                except (TypeError, ValueError):
                    amount = 1
                counts[self._clean_display(name)] += amount
            lines.extend(["", title + ":"])
            lines.append(f"Всего предметов: {sum(counts.values())}")
            lines.extend(f"• {name} × {amount}" for name, amount in counts.items())
            if not counts:
                lines.append("• Нет предметов")
        return "\n".join(lines)

    def _record_offer(self, offer):
        offer_id = str(offer["tradeofferid"])
        old = self.store.get("offers", offer_id, {})
        if offer.get("trade_offer_state") != 2:
            if old:
                old["status"] = TERMINAL.get(offer.get("trade_offer_state"), "manual")
                self.store.put("offers", offer_id, old)
            return
        remote_error = ""
        try:
            self.reconcile_listings()
        except ServiceError:
            remote_error = "Не удалось сверить объявление backpack.tf. Проверьте условия вручную."
        result, descriptions, reserved = self._validated(offer)
        valid = result.valid and not reserved and not remote_error
        reason = remote_error or reserved or ("Вещи и оплата совпадают с объявлением." if valid else result.reason)
        row = {**old, "offer_id": offer_id,
               "partner": str(76561197960265728 + int(offer.get("accountid_other", 0))),
               "status": "manual", "summary": self._summary(offer, descriptions),
               "reason": reason, "valid": valid, "fingerprint": result.fingerprint,
               "asset_ids": list(result.asset_ids), "raw": offer}
        self.store.put("offers", offer_id, row)
        signature = hashlib.sha256((row["summary"] + reason + str(valid)).encode()).hexdigest()[:20]
        verdict = "Проверка пройдена." if valid else "Проверка не пройдена."
        self._queue_notice("offer-check:" + offer_id + ":" + signature,
                           verdict + "\n" + reason + "\nОбмен выполняется вручную в Steam.\n\n" + row["summary"],
                           self._offer_button(offer_id))
        try:
            self._flush_notices()
        except ServiceError:
            self.log("Telegram: уведомление сохранено и будет отправлено после восстановления связи.")
        self.emit()


    @staticmethod
    def _offer_button(offer_id):
        return [[dict(text="Открыть обмен в Steam", url=f"https://steamcommunity.com/tradeoffer/{offer_id}/")]]



    def _cancel_notice_entries(self, prefixes):
        """Return SQL updates to commit alongside the offer state change."""
        with self.store.lock:
            rows = self.store.db.execute("SELECT id,data FROM outbox").fetchall()
        entries = []
        for key, data in rows:
            if not any(key == prefix or key.startswith(prefix + ":") for prefix in prefixes):
                continue
            notice = json.loads(data)
            if not notice.get("sent"):
                notice.update(sent=True, canceled=True)
                entries.append(("outbox", key, notice))
        return entries





    def _telegram_ready(self):
        return bool(self._config["telegram_token"] and self._config["telegram_chat_id"])

    def _queue_notice(self, key, text, buttons=None):
        if not self.store.get("outbox", key):
            self.store.put("outbox", key, dict(text=self._clean_display(text)[:3900], sent=False, buttons=buttons))

    def _flush_notices(self):
        if not self._telegram_ready():
            return
        with self.store.lock:
            rows = self.store.db.execute("SELECT id,data FROM outbox").fetchall()
        for key, payload in rows:
            notice = json.loads(payload)
            if not notice["sent"] and key.startswith("offer-check:"):
                text = self._translate(notice["text"])
                buttons = [[{**button, "text": self._translate(button["text"])} for button in line]
                           for line in notice.get("buttons") or []]
                if notice.get("buttons"):
                    self.telegram.send(text, buttons)
                else:
                    self.telegram.send(text)
                notice["sent"] = True
                self.store.put("outbox", key, notice)



    def _cleanup(self):
        for row in self.store.listings():
            if row.get("cleanup_pending") and row.get("listing_id"):
                try:
                    self.backpack.delete(row["listing_id"])
                except ServiceError:
                    continue
                row["cleanup_pending"] = False
                self.store.put("listings", row["asset_id"], row)

    def tick(self):
        with self.lock:
            if not self.monitoring or self.demo:
                return
            for offer in self.steam.offers():
                if not self.monitoring:
                    return
                self._record_offer(offer)
            self._cleanup()
            self._flush_notices()
            self.emit()

    def _run(self):
        next_trade_check = 0.0
        next_settle_check = 0.0
        while not self.closed:
            timeout = self._config["poll_interval"]
            if self._config["bump_enabled"] and self._config["backpack_token"] and self._config["steam_id"]:
                deadline = self._bump_deadline(self.bump_status())
                timeout = min(timeout, max(1, deadline - time.time()))
            signaled = self.wakeup.wait(timeout=timeout)
            self.wakeup.clear()
            if self.closed:
                return
            try:
                if self.monitoring and time.monotonic() >= next_trade_check:
                    self.tick()
                    next_trade_check = time.monotonic() + self._config["poll_interval"]
                    next_settle_check = next_trade_check
                elif not self.demo and time.monotonic() >= next_settle_check:
                    # Deliver queued notifications after a temporary connection failure.
                    with self.lock:
                        self._cleanup()
                        self._flush_notices()
                    next_settle_check = time.monotonic() + self._config["poll_interval"]
            except (ServiceError, ValueError) as error:
                self.log(str(error))
                try:
                    self._flush_notices()
                except ServiceError:
                    pass
            except Exception:
                self.log("Ошибка обработки. Операции приостановлены; проверьте настройки и журнал.")
                self.monitoring = False
                self.emit("running", False)
            # A Steam error must not stop bumps, or vice versa.
            try:
                self._bump_tick()
            except (ServiceError, ValueError) as error:
                self.log(str(error))
            except Exception:
                self.log("Не удалось выполнить автоматический бамп. Проверьте настройки и журнал.")

    def test_connections(self):
        if self.demo:
            return "Демонстрация: сетевые проверки отключены."
        with self.lock:
            results = []
            for title, client in (("Steam", self.steam), ("backpack.tf", self.backpack), ("Telegram", self.telegram)):
                if title == "Telegram" and not self._telegram_ready():
                    results.append("Telegram: не настроен")
                    continue
                try:
                    client.check()
                    results.append(title + ": соединение и авторизация подтверждены")
                except ServiceError as error:
                    results.append(str(error))
            result = "\n".join(results)
            self.log(result)
            return result

    def close(self):
        self.monitoring = False
        self.closed = True
        self.wakeup.set()
        if self._agent_registered:
            try:
                self.backpack.stop()
            except ServiceError:
                pass
            self._agent_registered = False
        # Leave the DB open if the worker is still using it; process exit releases the lock.
        if not self.worker.is_alive():
            self.store.close()
            self.instance.close()

    def _seed_demo(self):
        rows = [dict(asset_id="15178000001", name="Strange Professional Killstreak Rocket Launcher", quality="Strange", type="Primary weapon", paint="", extra_properties=[], icon_url="", tradable=True),
                dict(asset_id="15178000002", name="Team Captain", quality="Unique", type="Cosmetic", paint="Paint Color: A Distinctive Lack of Hue", extra_properties=[], icon_url="", tradable=True),
                dict(asset_id="15178000003", name="Team Captain", quality="Unique", type="Cosmetic", paint="Paint Color: Pink as Hell", extra_properties=[], icon_url="", tradable=True),
                dict(asset_id="15178000004", name="Unusual Killer Exclusive", quality="Unusual", type="Cosmetic", paint="", extra_properties=[], icon_url="", tradable=True)]
        for row in rows:
            row["icon_url"] = "demo:" + ("rocket.png" if row["asset_id"] == "15178000001" else "unusual.png" if row["asset_id"] == "15178000004" else "captain.png")
            row["name_color"] = "CF6A32" if row["quality"] == "Strange" else "8650AC" if row["quality"] == "Unusual" else "FFD700"
            row["filter_tags"] = [dict(category="Quality", name=row["quality"], label=row["quality"]),
                                   dict(category="Type", name=row["type"], label=row["type"])]
            classes = ["Soldier"] if row["asset_id"] == "15178000001" else ["Soldier", "Heavy", "Medic"] if row["asset_id"] != "15178000004" else ["Scout", "Soldier", "Pyro", "Demoman", "Heavy", "Engineer", "Medic", "Sniper", "Spy"]
            row["filter_tags"].extend(dict(category="Class", name=name, label=name) for name in classes)
        self.store.replace_inventory(rows)
        self.store.put("listings", "15178000002", dict(asset_id="15178000002", name="Team Captain", keys=1, metal_scrap=135, status="active", listing_id="440_15178000002", details="Painted Team Captain · 1 key + 15 ref", version=1,
                       backpack_item=dict(appid=440, defindex=378, name="The Team Captain", baseName="Team Captain", quality={"id": 6},
                                          craftable=True, tradable=True, paint={"name": "A Distinctive Lack of Hue"}, extra_properties=[])))
        self.store.put("offers", "90000001", dict(offer_id="90000001", partner="76561198000000000", status="waiting", valid=True, reason="Цена и состав совпадают", summary="Ваши предметы:\n• Team Captain × 1\n\nПокупатель предлагает:\n• Mann Co. Supply Crate Key × 1\n• Refined Metal × 15"))
