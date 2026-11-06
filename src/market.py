"""Build backpack.tf search links from item properties and bundled TF2 metadata."""
from __future__ import annotations

import html
import sys
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

KNOWN_LINK_ITEM_FIELDS = set("appid baseName defindex id imageUrl marketName name origin originalId price quality summary texture class wearTier slot particle tradable craftable priceindex level craftedBy tag killstreakTier killEaters australium giftedBy recipe sheen paint paintSecondaryHex style customName crateSeries customDesc equipped killstreaker tradableAfter elevatedQuality festivized craftNumber strangeParts rarity marketplaceTfListing dupe decal quantity attributes medalNumber containedItem".split())


@lru_cache(maxsize=1)
def _metadata():
    return json.loads(((Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]) / "assets" / "tf2_metadata.json").read_text(encoding="utf-8"))


def _entity_label(value, table):
    if isinstance(value, dict) and value.get("name"):
        return _label(value)
    number = value.get("id") if isinstance(value, dict) else value
    if table in {"sheen", "killstreaker"} and number in (0, "0"):
        raise ValueError("Неизвестен эффект Killstreak.")
    if number not in (None, "", False, 0, "0") or (table == "kill_eaters" and number in (0, "0")):
        known = _metadata().get(table, {}).get(str(number))
        if known:
            return _label(known)
    return _label(value)


def _text(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", "", str(value or "")))).strip()


def _label(value):
    if isinstance(value, dict):
        # A paint number may be a definition ID or RGB value; match by name first.
        if value.get("name"):
            return "name:" + _text(value["name"]).casefold()
        if value.get("id") is not None:
            return "id:" + str(value["id"])
        raise ValueError("Неполное свойство варианта backpack.tf.")
    if value in (None, "", False, 0, "0"):
        return None
    if isinstance(value, (str, int)):
        return "name:" + _text(value).casefold()
    raise ValueError("Неизвестное свойство варианта backpack.tf.")


def _id(value):
    if isinstance(value, dict):
        value = value.get("id")
    if isinstance(value, bool) or not str(value).isdigit():
        raise ValueError("Недостаточно данных о качестве или типе предмета.")
    return int(value)


def _bool(value):
    if value in (True, 1, "1", "true"):
        return True
    if value in (False, 0, "0", "false"):
        return False
    raise ValueError("Неизвестны ограничения обмена или ковки предмета.")



def _filter_entity_id(label, table):
    """Convert a known game attribute to backpack.tf's filter value."""
    for number, value in _metadata().get(table, {}).items():
        name = value.get("name") if isinstance(value, dict) else value
        if label in {"id:" + str(number), _label(name)}:
            return int(number)
    return None


def _web_base_name(item, fields):
    backpack = item.get("backpack_item") or {}
    if backpack.get("baseName"):
        return _text(backpack["baseName"])
    desc = item.get("description") or {}
    name = _text(desc.get("market_name") or desc.get("market_hash_name")
                 or item.get("market_hash_name") or backpack.get("marketName") or item.get("name"))
    quality = fields.get("quality")
    prefixes = {1: "Genuine", 3: "Vintage", 5: "Unusual", 7: "Community", 9: "Self-Made",
                11: "Strange", 13: "Haunted", 14: "Collector's"}
    known = [prefixes[quality]] if quality in prefixes else []
    if fields.get("elevated_quality") == 11:
        known.append("Strange")
    if fields.get("killstreak_tier"):
        known.extend(["Professional Killstreak", "Specialized Killstreak", "Killstreak"])
    if fields.get("australium"):
        known.append("Australium")
    if fields.get("festivized"):
        known.append("Festivized")
    # Steam can reorder quality prefixes. Keep "Festive": it is part of the item name.
    while True:
        found = next((prefix for prefix in known if name.casefold().startswith(prefix.casefold() + " ")), None)
        if not found:
            break
        name = name[len(found):].lstrip()
    return name


def _partial_link_properties(item):
    """Keep known filters even when some item properties are unsupported."""
    backpack = item.get("backpack_item") or {}
    desc = item.get("description") or {}
    app = desc.get("app_data") or {}
    properties = {}
    for source, target in (("quality", "quality"), ("elevatedQuality", "elevated_quality"),
                           ("killstreakTier", "killstreak_tier")):
        raw = backpack.get(source)
        if raw is None and source == "quality":
            raw = item.get("quality_id") if item.get("quality_id") is not None else app.get("quality")
        try:
            if raw is not None:
                properties[target] = _id(raw)
        except ValueError:
            pass
    if "quality" not in properties:
        qualities = {name.casefold(): number for name, number in _metadata().get("qualities", {}).items()}
        known = {qualities[str(tag.get("internal_name", "")).casefold()]
                 for tag in desc.get("tags", []) if isinstance(tag, dict)
                 and tag.get("category") == "Quality"
                 and str(tag.get("internal_name", "")).casefold() in qualities}
        if len(known) == 1:
            properties["quality"] = known.pop()
    for key in ("craftable", "tradable", "australium", "festivized"):
        raw = backpack.get(key, item.get(key))
        if raw is None and key == "tradable":
            raw = desc.get("tradable")
        try:
            if raw is not None:
                properties[key] = _bool(raw)
        except ValueError:
            pass
    texts = [_text(part.get("value")) for part in desc.get("descriptions", [])
             if isinstance(part, dict) and part.get("type") != "usertext"]
    def attribute(pattern):
        found = {match.group(1).strip() for text in texts if (match := re.search(pattern, text, re.I))}
        return found.pop() if len(found) == 1 else None
    for key, table, pattern in (
        ("paint", "paint_ids", r"^(?:Paint Color|Цвет краски|Краска):\s*(.+)$"),
        ("particle", "particles", r"^(?:★\s*)?(?:Unusual Effect|Необычный эффект):\s*(.+)$"),
        ("sheen", "sheen", r"^(?:Sheen|Блеск):\s*(.+)$"),
        ("killstreaker", "killstreaker", r"^(?:Killstreaker|Эффект серии убийств):\s*(.+)$")):
        raw = backpack.get(key)
        try:
            if raw not in (None, "", False):
                properties[key] = _entity_label(raw, table)
            else:
                text = attribute(pattern)
                if text:
                    properties[key] = _label(text)
        except ValueError:
            pass
    canonical = _text(desc.get("market_name") or desc.get("market_hash_name")
                      or item.get("market_hash_name") or backpack.get("marketName") or item.get("name"))
    if "killstreak_tier" not in properties:
        properties["killstreak_tier"] = (3 if re.search(r"\bprofessional killstreak\b", canonical, re.I)
                                         else 2 if re.search(r"\bspecialized killstreak\b", canonical, re.I)
                                         else 1 if re.search(r"\bkillstreak\b", canonical, re.I) else 0)
    if properties.get("killstreak_tier") not in (0, 1, 2, 3):
        properties.pop("killstreak_tier", None)
    for key in ("australium", "festivized"):
        if key not in properties and re.search(r"\b" + key + r"\b", canonical, re.I):
            properties[key] = True
    for source, target in (("texture", "texture"), ("wearTier", "wear"), ("style", "style")):
        try:
            if backpack.get(source):
                properties[target] = _label(backpack[source])
        except ValueError:
            pass
    for source, target in (("strangeParts", "strange_parts"), ("craftNumber", "craft_number"),
                           ("medalNumber", "medal_number"), ("crateSeries", "crate_series"),
                           ("attributes", "attributes")):
        if backpack.get(source):
            properties[target] = backpack[source]
    return properties


def market_link(item):
    """Build a search link and list properties that need checking on the website.

    Some attachments have no URL filter.
    """
    properties = _partial_link_properties(item)
    backpack = item.get("backpack_item") or {}
    manual = []
    if any(key not in KNOWN_LINK_ITEM_FIELDS and value not in (None, False, "", [], {})
           for key, value in backpack.items()):
        manual.append("Дополнительные свойства")
    if properties.get("quality") == 11 or properties.get("elevated_quality") == 11:
        manual.append("Счётчики Strange")
    fields = {"item": _web_base_name(item, properties), "intent": "sell"}
    if not fields["item"]:
        raise ValueError("Нет названия предмета для открытия backpack.tf.")
    for key in ("quality", "craftable", "tradable"):
        if key in properties:
            fields[key] = int(properties[key])
    if properties.get("elevated_quality") is not None:
        fields["elevated"] = properties["elevated_quality"]
    paint = properties.get("paint")
    if paint:
        entity = next((value for value in _metadata().get("paint_ids", {}).values() if _label(value) == paint), None)
        if entity:
            fields["paint"] = entity["primary"]
        else:
            manual.append("Краска")
    for key, table in (("particle", "particles"), ("sheen", "sheen"), ("killstreaker", "killstreaker")):
        if properties.get(key):
            number = _filter_entity_id(properties[key], table)
            if number is None:
                manual.append({"particle": "Unusual Effect", "sheen": "Sheen", "killstreaker": "Killstreaker"}[key])
            else:
                fields[key] = number
    if "killstreak_tier" in properties:
        fields["killstreak_tier"] = properties["killstreak_tier"]
    if properties.get("australium"):
        fields["australium"] = 1
    texture = properties.get("texture")
    if texture:
        original = backpack.get("texture")
        name = original.get("name") if isinstance(original, dict) else original if isinstance(original, str) else None
        if name and not name.isdigit():
            fields["texture_name"] = _text(name)
        else:
            manual.append("War Paint")
    wear_names = {"factory new": "Factory New", "minimal wear": "Minimal Wear", "field-tested": "Field-Tested",
                  "well-worn": "Well-Worn", "battle scarred": "Battle Scarred", "battle-scarred": "Battle Scarred"}
    wear = properties.get("wear")
    if wear:
        name = wear_names.get(wear.removeprefix("name:"))
        if name:
            fields["wear"] = name
        else:
            manual.append("Износ")
    for key, title in (("style", "Стиль"), ("strange_parts", "Strange Parts"), ("festivized", "Festivized"),
                       ("craft_number", "Номер ковки"), ("medal_number", "Номер медали"),
                       ("crate_series", "Серия ящика"), ("attributes", "Дополнительные свойства")):
        if properties.get(key):
            manual.append(title)
    return dict(url="https://backpack.tf/classifieds?" + urlencode(fields), parameters=fields,
                manual=list(dict.fromkeys(manual)), exact=False)


def market_url(item):
    return market_link(item)["url"]
