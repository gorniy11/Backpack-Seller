"""TF2 item parsing and offer validation.

Currency is identified by Steam metadata, never by its name. Metal is stored
as whole scrap units to avoid rounding errors: 1 refined = 9 scrap.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import json
import re
from typing import Any, Mapping


APP_ID = "440"
CONTEXT_ID = "2"
CURRENCY_DEFINDEX = {5021: (1, 0), 5000: (0, 1), 5001: (0, 3), 5002: (0, 9)}
FRACTIONS = {"00": 0, "11": 1, "22": 2, "33": 3, "44": 4,
             "55": 5, "66": 6, "77": 7, "88": 8}
STEAM_CDN = "https://community.steamstatic.com/economy/image/"
QUALITY_NAMES = {0: "Normal", 1: "Genuine", 3: "Vintage", 5: "Unusual", 6: "Unique",
                 7: "Community", 8: "Valve", 9: "Self-Made", 11: "Strange", 13: "Haunted",
                 14: "Collector's", 15: "Decorated Weapon"}


def _plain(value: Any) -> str:
    return html.unescape(re.sub(r"<[^>]*>", "", str(value or ""))).strip()


def _integer(value: Any, *, minimum: int = 0, maximum: int = 2**63 - 1) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    if isinstance(value, str) and not re.fullmatch(r"[0-9]+", value):
        return None
    try:
        number = int(value)
    except (ValueError, TypeError):
        return None
    return number if minimum <= number <= maximum else None


def parse_price(keys: Any, refined: Any) -> dict[str, int]:
    """Parse keys and refined metal exactly; .11 means one scrap, not 0.11 ref."""
    key_count = _integer(keys.strip() if isinstance(keys, str) else keys)
    if key_count is None:
        raise ValueError("Ключи: введите целое неотрицательное число")
    if isinstance(refined, bool) or not isinstance(refined, (int, str)):
        raise ValueError("Металл: используйте точную цену, например 15 или 1.33 ref")
    text = str(refined).strip().replace(",", ".")
    match = re.fullmatch(r"([0-9]*)(?:\.([0-9]{2}))?", text)
    if not match or not (match.group(1) or match.group(2)):
        raise ValueError("Металл: допустимы целые ref и дроби .11, .22, .33, .44, .55, .66, .77, .88")
    fraction = match.group(2) or "00"
    if fraction not in FRACTIONS:
        raise ValueError("Допустимые доли ref: .11, .22, .33, .44, .55, .66, .77, .88")
    scrap = int(match.group(1) or 0) * 9 + FRACTIONS[fraction]
    if scrap > 2**63 - 1:
        raise ValueError("Слишком большая цена")
    if key_count == scrap == 0:
        raise ValueError("Цена должна быть больше нуля")
    return {"keys": key_count, "metal_scrap": scrap}


def refined_text(metal_scrap: int) -> str:
    if _integer(metal_scrap) is None:
        raise ValueError("Неверное количество металла")
    whole, remainder = divmod(metal_scrap, 9)
    return str(whole) if not remainder else f"{whole}.{remainder * 11:02d}"


def format_price(keys: int, metal_scrap: int) -> str:
    if _integer(keys) is None or _integer(metal_scrap) is None:
        raise ValueError("Неверная цена")
    pieces = []
    if keys:
        pieces.append(f"{keys} Mann Co. Key")
    if metal_scrap or not pieces:
        pieces.append(f"{refined_text(metal_scrap)} Refined Metal")
    return " + ".join(pieces)


def description_key(item: Mapping[str, Any]) -> str:
    return f"{item.get('classid', '')}_{item.get('instanceid', '0')}"


def _description_map(descriptions: Any) -> dict[str, dict]:
    if isinstance(descriptions, Mapping):
        rows = descriptions.get("descriptions")
        if isinstance(rows, list):
            return _description_map(rows)
        result = {}
        for key, value in descriptions.items():
            if isinstance(value, dict):
                result[str(key)] = value
                if value.get("classid") is not None:
                    result[description_key(value)] = value
        return result
    if isinstance(descriptions, list):
        return {description_key(row): row for row in descriptions if isinstance(row, dict)}
    return {}


def _metadata(description: Mapping[str, Any]) -> tuple[int | None, int | None, bool | None]:
    data = description.get("app_data")
    data = data if isinstance(data, Mapping) else {}
    defindex = _integer(data.get("def_index", data.get("defindex", description.get("defindex"))))
    quality = _integer(data.get("quality", description.get("quality")))
    craftable = description.get("craftable", data.get("craftable"))
    if craftable in (False, 0, "0", "false", "False"):
        craftable = False
    elif craftable in (True, 1, "1", "true", "True"):
        craftable = True
    else:
        # Steam marks noncraftable items with a restriction in their description.
        rows = description.get("descriptions")
        if isinstance(rows, list):
            texts = [_plain(row.get("value")).casefold() for row in rows if isinstance(row, Mapping)]
            craftable = not any("not usable in crafting" in text or "not craftable" in text or
                                "нельзя использовать в ковке" in text or "не используется в ковке" in text
                                for text in texts)
        else:
            craftable = None
    return defindex, quality, craftable


def parse_inventory(payload: Mapping[str, Any], tradable_only: bool = True) -> list[dict]:
    """Join items to their descriptions without merging separate copies of an item."""
    if not isinstance(payload, Mapping):
        raise ValueError("Steam: неверный ответ инвентаря")
    assets = payload.get("assets", [])
    descriptions = _description_map(payload.get("descriptions", []))
    if not isinstance(assets, list):
        raise ValueError("Steam: неверный список предметов")
    result = []
    seen = set()
    for asset in assets:
        if not isinstance(asset, Mapping) or str(asset.get("appid", APP_ID)) != APP_ID or str(asset.get("contextid", CONTEXT_ID)) != CONTEXT_ID:
            continue
        asset_id = str(asset.get("assetid", asset.get("id", "")))
        if _integer(asset_id, minimum=1, maximum=2**64 - 1) is None or asset_id in seen or asset.get("missing"):
            continue
        description = descriptions.get(description_key(asset))
        if not description or str(description.get("appid", APP_ID)) != APP_ID:
            continue
        tradable = description.get("tradable") in (True, 1, "1")
        if tradable_only and not tradable:
            continue
        texts = [_plain(row.get("value")) for row in description.get("descriptions", []) if isinstance(row, Mapping)]
        tags = description.get("tags") or []
        quality_tag = next((tag for tag in tags if isinstance(tag, Mapping) and tag.get("category") == "Quality"), {})
        type_tag = next((tag for tag in tags if isinstance(tag, Mapping) and tag.get("category") == "Type"), {})
        defindex, quality_id, craftable = _metadata(description)
        quality = quality_tag.get("localized_tag_name") or QUALITY_NAMES.get(quality_id, "Unknown")
        painted = next((text for text in texts if re.search(r"(?:paint color|цвет краски|краска)\s*:", text, re.I)), "")
        spells = [text for text in texts if re.search(r"halloween:|halloween spell|заклинание|хеллоуин", text, re.I)]
        icon = str(description.get("icon_url_large") or description.get("icon_url") or "")
        # Icon paths must stay on Steam's CDN.
        icon_url = STEAM_CDN + icon + "/256fx256f" if icon and not re.match(r"(?:[a-z]+:)?//", icon, re.I) else ""
        result.append({
            "asset_id": asset_id, "assetid": asset_id, "appid": APP_ID, "contextid": CONTEXT_ID,
            "classid": str(asset.get("classid", "")), "instanceid": str(asset.get("instanceid", "0")),
            "amount": str(asset.get("amount", "1")), "name": item_name(description),
            "market_hash_name": _plain(description.get("market_hash_name") or description.get("name")),
            "quality": str(quality), "quality_id": quality_id, "type": _plain(type_tag.get("localized_tag_name") or description.get("type")),
            "paint": painted, "spells": spells, "descriptions": texts, "icon_url": icon_url,
            "icon_path": icon, "name_color": str(description.get("name_color") or ""),
            "tradable": tradable, "craftable": craftable, "defindex": defindex,
            "description": dict(description),
            "filter_tags": inventory_tags(description),
        })
        seen.add(asset_id)
    return result


def item_name(description):
    """Use the base item name rather than a Name Tag alias."""
    return _plain(description.get("market_name") or description.get("market_hash_name") or description.get("name"))


def inventory_tags(description):
    result = []
    for tag in description.get("tags") or []:
        if not isinstance(tag, Mapping):
            continue
        category = str(tag.get("category") or "")
        name = str(tag.get("internal_name") or tag.get("localized_tag_name") or "")
        if not category or not name or "paint" in category.lower():
            continue
        result.append(dict(category=category, category_label=_plain(tag.get("localized_category_name") or category),
                           name=name, label=_plain(tag.get("localized_tag_name") or name)))
    return result


def inventory_matches(row, query="", selected=None):
    if query.strip().casefold() not in str(row.get("name", "")).casefold():
        return False
    tags = row.get("filter_tags") or inventory_tags(row.get("description") or {})
    by_category = {}
    for tag in tags:
        by_category.setdefault(tag["category"], set()).add(tag["name"])
    return all(not values or bool(by_category.get(category, set()) & set(values))
               for category, values in (selected or {}).items())


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str
    keys: int = 0
    metal_scrap: int = 0
    asset_ids: tuple[str, ...] = ()
    auto_eligible: bool = False
    fingerprint: str = ""

    def to_dict(self) -> dict:
        return {"valid": self.valid, "reason": self.reason, "keys": self.keys,
                "metal_scrap": self.metal_scrap, "asset_ids": list(self.asset_ids),
                "auto_eligible": self.auto_eligible, "fingerprint": self.fingerprint}


def offer_fingerprint(offer: Mapping[str, Any], listings: Any) -> str:
    """Bind a decision to the offer contents and listing price.

    Exclude timestamps and offer state: both change while confirmation is pending.
    """
    if isinstance(listings, Mapping):
        listing_map = listings
    else:
        listing_map = {str(row.get("asset_id", "")): row for row in listings or [] if isinstance(row, Mapping)}
    relevant = {}
    for item in offer.get("items_to_give") or []:
        if isinstance(item, Mapping):
            asset_id = str(item.get("assetid", ""))
            row = listing_map.get(asset_id)
            if isinstance(row, Mapping):
                relevant[asset_id] = {key: row.get(key) for key in
                                      ("asset_id", "status", "keys", "metal_scrap", "auto_accept", "version", "listing_id")}
    immutable = {key: offer.get(key) for key in ("tradeofferid", "accountid_other", "is_our_offer",
                                                "items_to_give", "items_to_receive", "message")}
    raw = json.dumps({"offer": immutable, "listings": relevant}, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_offer(offer: Mapping[str, Any], listings: Any, descriptions: Any = ()) -> ValidationResult:
    """Check the offered items and payment against the current listings.

    Currency descriptions must come from Steam. This function only validates;
    accepting the offer is handled separately by the engine.
    """
    if not isinstance(offer, Mapping):
        return ValidationResult(False, "Steam вернул неверное предложение")
    try:
        fingerprint = offer_fingerprint(offer, listings)
    except (TypeError, ValueError, AttributeError):
        return ValidationResult(False, "Неверная структура предложения или объявлений")
    def fail(reason: str, keys: int = 0, scrap: int = 0, assets: tuple[str, ...] = ()) -> ValidationResult:
        return ValidationResult(False, reason, keys, scrap, assets, False, fingerprint)

    if offer.get("is_our_offer") is not False or _integer(offer.get("trade_offer_state")) != 2:
        return fail("Предложение не является активным входящим обменом")
    if _integer(offer.get("tradeofferid"), minimum=1, maximum=2**64 - 1) is None:
        return fail("Не указан точный ID предложения")
    if _integer(offer.get("accountid_other"), minimum=1, maximum=2**32 - 1) is None:
        return fail("Steam не подтвердил аккаунт покупателя")
    give = offer.get("items_to_give")
    receive = offer.get("items_to_receive")
    if not isinstance(give, list) or not give or not isinstance(receive, list) or not receive:
        return fail("Нужны продаваемые предметы и оплата с обеих сторон")
    if isinstance(listings, Mapping):
        listing_map = {str(key): value for key, value in listings.items()}
    elif isinstance(listings, list):
        listing_map = {}
        for row in listings:
            if not isinstance(row, Mapping) or str(row.get("asset_id", "")) in listing_map:
                return fail("Неверные или дублирующиеся объявления")
            listing_map[str(row.get("asset_id", ""))] = row
    else:
        return fail("Не загружены объявления")
    description_map = _description_map(descriptions)
    wanted_keys = wanted_scrap = 0
    incoming_keys = incoming_scrap = 0
    sold = []
    all_auto = True
    for side, rows in (("give", give), ("receive", receive)):
        seen = set()
        for item in rows:
            if not isinstance(item, Mapping):
                return fail("Неверный предмет в предложении")
            asset_id = str(item.get("assetid", ""))
            if _integer(asset_id, minimum=1, maximum=2**64 - 1) is None or asset_id in seen:
                return fail("Пропущенный или повторяющийся экземпляр предмета")
            seen.add(asset_id)
            if str(item.get("appid")) != APP_ID or str(item.get("contextid")) != CONTEXT_ID:
                return fail("В предложении есть предмет другой игры или инвентаря")
            if str(item.get("amount", "")) != "1" or item.get("missing") or item.get("currencyid"):
                return fail("Пропавший предмет или неподдерживаемое количество")
            if side == "give":
                listing = listing_map.get(asset_id)
                if not isinstance(listing, Mapping) or listing.get("status") != "active":
                    return fail("Покупатель запрашивает предмет без активного объявления")
                key_price = _integer(listing.get("keys"))
                scrap_price = _integer(listing.get("metal_scrap"))
                if key_price is None or scrap_price is None or key_price + scrap_price == 0:
                    return fail("В объявлении неверная или нулевая цена")
                wanted_keys += key_price
                wanted_scrap += scrap_price
                sold.append(asset_id)
                all_auto = all_auto and listing.get("auto_accept") is True
            else:
                description = description_map.get(asset_id) or description_map.get(description_key(item))
                if not isinstance(description, Mapping) or str(description.get("appid", APP_ID)) != APP_ID:
                    return fail("Steam не предоставил достоверное описание валюты")
                if item.get("classid") is not None and description.get("classid") is not None and str(item["classid"]) != str(description["classid"]):
                    return fail("Описание валюты не соответствует предмету")
                if item.get("instanceid") is not None and description.get("instanceid") is not None and str(item["instanceid"]) != str(description["instanceid"]):
                    return fail("Описание валюты не соответствует экземпляру")
                defindex, quality, craftable = _metadata(description)
                currency = CURRENCY_DEFINDEX.get(defindex)
                if currency is None or quality != 6 or craftable is not True:
                    return fail("Оплата содержит нестандартную валюту или неполное описание")
                if description.get("tradable") not in (True, 1, "1"):
                    return fail("Оплата содержит необмениваемый предмет")
                incoming_keys += currency[0]
                incoming_scrap += currency[1]
    assets = tuple(sorted(sold))
    if incoming_keys != wanted_keys or incoming_scrap != wanted_scrap:
        return fail("Цена не совпадает: нужно " + format_price(wanted_keys, wanted_scrap) +
                    ", предложено " + format_price(incoming_keys, incoming_scrap), incoming_keys, incoming_scrap, assets)
    return ValidationResult(True, "Точные предметы и оплата совпадают", incoming_keys, incoming_scrap,
                            assets, all_auto, fingerprint)
