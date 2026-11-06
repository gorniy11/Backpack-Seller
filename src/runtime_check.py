"""Check the packaged app's dependencies without signing in to any accounts."""
import json
import ssl
import sys
import tkinter as tk
from pathlib import Path


def run(report_path):
    from vault import protect, unprotect
    from playwright.sync_api import sync_playwright
    result = {"frozen": bool(getattr(sys, "frozen", False))}
    try:
        context = ssl.create_default_context()
        result["tls_verified"] = bool(context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED)
        sample = b"backpack-seller-local-build-check"
        encrypted = protect(sample)
        result["vault_roundtrip"] = encrypted != sample and unprotect(encrypted) == sample
        from market import market_link
        from urllib.parse import urlsplit, parse_qs
        link = market_link({"backpack_item": dict(defindex=825, name="Hat of Cards", baseName="Hat of Cards", quality={"id": 6},
                   paint={"name": "A Distinctive Lack of Hue"}, tradable=True, craftable=True)})
        query = parse_qs(urlsplit(link["url"]).query)
        result["filter_links_ready"] = query.get("paint") == ["1315860"] and query.get("quality") == ["6"]
        from i18n import translate
        from appearance import palette
        result["languages_ready"] = translate("Настройки", "en") == "Settings" and translate("Настройки", "ru") == "Настройки"
        result["themes_ready"] = palette("light")["bg"] != palette("dark")["bg"]
        root = tk.Tk()
        root.withdraw()
        from PIL import Image, ImageTk
        assets = (Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]) / "assets"
        with Image.open(assets / "demo/rocket.png") as source:
            image = ImageTk.PhotoImage(source, master=root)
            result["item_images_ready"] = image.width() > 100 and image.height() > 100
        root.iconbitmap(str(assets / "app.ico"))
        result["app_icon_ready"] = True
        root.update()
        root.destroy()
        result["tk_ready"] = True
        with sync_playwright() as playwright:
            result["browser_driver_ready"] = bool(playwright.chromium)
        result["ok"] = all(result.get(k) for k in ("tls_verified", "vault_roundtrip", "tk_ready", "browser_driver_ready", "item_images_ready", "app_icon_ready", "filter_links_ready", "languages_ready", "themes_ready"))
    except Exception as error:
        result.update(ok=False, error_type=type(error).__name__)
    Path(report_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1
