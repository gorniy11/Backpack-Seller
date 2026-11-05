"""Desktop interface for listings, inventory and trade offers."""
from __future__ import annotations

import argparse
import io
import queue
import sys
import threading
import time
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from datetime import datetime

from domain import format_price, inventory_matches, inventory_tags
from media import load_image, allowed_image
from PIL import Image, ImageTk, ImageOps
from appearance import palette
from i18n import translate, LANGUAGES


BG = "#F4F6FA"
WHITE = "#FFFFFF"
INK = "#172638"
MUTED = "#6B7788"
NAVY = "#142536"
ORANGE = "#E96F35"
LINE = "#E1E7EF"
GREEN = "#268262"

STATUS = {
    "active": "Выставлено", "pending": "Ожидает решения", "new": "Новое",
    "accepted": "Обмен завершён", "completed": "Обмен завершён", "sold": "Продано",
    "declined": "Отклонено", "invalid": "Не прошло проверку", "rejected": "Отклонено",
    "accepting": "Принимается", "accept_sent": "Приём отправлен", "unknown": "Нужна сверка",
    "needs_confirmation": "Подтверждение Steam", "confirmation_pending": "Подтверждение Steam",
    "in_escrow": "Удержание Steam", "removed": "Снято", "deleted": "Снято",
    "publishing": "Публикация", "error": "Ошибка", "canceled": "Отменено",
    "expired": "Истекло", "unavailable": "Недоступно", "waiting": "Ожидает решения",
    "awaiting_approval": "Ожидает решения", "manual": "Ручное решение",
    "publish_unknown": "Нужна сверка публикации", "external_change": "Объявление изменено",
    "removing": "Снятие объявления", "remove_unknown": "Нужна сверка удаления",
    "unsupported_price": "Проверьте валюту на сайте",
    "updating": "Изменение объявления", "update_unknown": "Нужна сверка изменений",
    "blocked": "Заблокировано", "accept_unknown": "Нужна сверка приёма",
    "confirmation_sent": "Подтверждение отправлено", "decline_sent": "Отказ отправлен",
    "countered": "Встречное предложение",
}


def status_text(value):
    return STATUS.get(str(value), str(value or "—"))


def price_text(row):
    if row.get("price_supported") is False:
        return "Неподдерживаемая валюта"
    try:
        return format_price(int(row.get("keys", 0)), int(row.get("metal_scrap", 0)))
    except (TypeError, ValueError):
        return "—"


class App:
    def __init__(self, root, engine, events=None):
        self.root, self.engine = root, engine
        self.events = events if events is not None else queue.Queue()
        if events is None:
            engine.on_event = self.receive_event
        self.closed = False
        self.busy = 0
        self.running = False
        self.inventory = []
        self.listing_rows = []
        self.offer_rows = []
        self.images = {}
        self.large_images = {}
        self.image_failed = set()
        self.item_cards = {}
        self.item_labels = {}
        self.filter_vars = {}
        self.filter_signature = None
        self.page_index = 0
        self.grid_columns = 5
        self.image_waiting = set()
        self.image_queue = queue.Queue()
        self.nav_buttons = {}
        self.pages = {}
        self.demo = bool(getattr(engine, "demo", False))
        self.selected_asset = None
        self.selected_offer = None
        self.selected_listing = None
        self.cached_settings = self.engine.settings()
        self.language = self.cached_settings.get("language", "ru")
        self.theme = self.cached_settings.get("theme", "light")
        self._preference_revision = 0
        self._preference_save_lock = threading.Lock()
        self._status_source = ""
        self._use_palette(self.theme)
        self._configure_window()
        self._styles()
        self._layout()
        self._inventory_page()
        self._listings_page()
        self._offers_page()
        self._settings_page()
        self._logs_page()
        self._install_input_support()
        self._load_settings()
        self.show_page("inventory")
        self.refresh_views()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._drain)
        if not self.demo:
            for _ in range(3):
                threading.Thread(target=self._image_worker, daemon=True).start()
            if self.cached_settings.get("backpack_token") and self.cached_settings.get("steam_id"):
                self.root.after(300, lambda: self._run("Сверка объявлений backpack.tf…",
                                                     self.engine.import_listings, quiet=True))


    def receive_event(self, kind, payload=None):
        self.events.put((kind, payload))

    def _configure_window(self):
        self.root.title("Backpack Seller · TF2")
        self.root.geometry("1460x940")
        self.root.minsize(1150, 780)
        self.root.configure(bg=BG)
        self.asset_root = Path(__file__).resolve().parent / "assets"
        try:
            self.app_icon = tk.PhotoImage(file=str(self.asset_root / "app.png"))
            self.root.iconphoto(True, self.app_icon)
            self.root.iconbitmap(str(self.asset_root / "app.ico"))
        except tk.TclError:
            pass
        self.root.option_add("*Font", "{Segoe UI} 10")

    def _use_palette(self, theme):
        global BG, WHITE, INK, MUTED, NAVY, ORANGE, LINE, GREEN
        self.palette = palette(theme)
        BG, WHITE, INK, MUTED = (self.palette[key] for key in ("bg", "surface", "text", "muted"))
        NAVY, ORANGE, LINE, GREEN = (self.palette[key] for key in ("nav", "accent", "border", "success"))

    def tr(self, text):
        return translate(str(text), self.language)

    def _status(self, text):
        self._status_source = str(text)
        self.status_var.set(self.tr(text))

    def _styles(self):
        p = self.palette
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=p["bg"], foreground=p["text"], font=("Segoe UI", 10))
        style.configure("TFrame", background=p["bg"])
        style.configure("Card.TFrame", background=p["surface"])
        for name, background, foreground in (("TLabel", p["bg"], p["text"]), ("Card.TLabel", p["surface"], p["text"]),
                                             ("Muted.TLabel", p["bg"], p["muted"]), ("CardMuted.TLabel", p["surface"], p["muted"])):
            style.configure(name, background=background, foreground=foreground)
        style.configure("TButton", background=p["surface"], foreground=p["text"], bordercolor=p["border"],
                        padding=(12, 8), focusthickness=0)
        style.map("TButton", background=[("disabled", p["disabled"]), ("active", p["hover"])], foreground=[("disabled", p["disabled_text"])])
        style.configure("Accent.TButton", background=p["accent"], foreground=p["on_accent"], bordercolor=p["accent"], font=("Segoe UI Semibold", 10))
        style.map("Accent.TButton", background=[("disabled", p["accent_disabled"]), ("active", p["accent_hover"])], foreground=[("disabled", p["on_accent"]), ("!disabled", p["on_accent"])])
        style.configure("Danger.TButton", foreground=p["danger"])
        for name in ("TEntry", "TCombobox"):
            style.configure(name, fieldbackground=p["surface"], background=p["surface"], foreground=p["text"],
                            bordercolor=p["border"], arrowcolor=p["text"], insertcolor=p["text"],
                            selectbackground=p["selection"], selectforeground=p["selection_text"], padding=7)
            style.map(name, fieldbackground=[("readonly", p["surface"]), ("disabled", p["disabled"])],
                      foreground=[("disabled", p["disabled_text"]), ("readonly", p["text"])])
        for name in ("TCheckbutton", "TRadiobutton", "SteamFilter.TCheckbutton"):
            style.configure(name, background=p["surface"], foreground=p["text"], indicatorbackground=p["surface"], padding=3)
            style.map(name, background=[("active", p["surface"])], foreground=[("disabled", p["disabled_text"])],
                      indicatorbackground=[("selected", p["accent"]), ("!selected", p["surface"])])
        style.configure("Filter.TCheckbutton", background=p["bg"])
        style.configure("SteamFilter.TCheckbutton", wraplength=190)
        style.configure("Treeview", background=p["surface"], fieldbackground=p["surface"], foreground=p["text"],
                        bordercolor=p["border"], rowheight=52, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background=p["hover"], foreground=p["muted"], font=("Segoe UI Semibold", 9), padding=(8, 10), relief="flat")
        style.map("Treeview", background=[("selected", p["selection"])], foreground=[("selected", p["selection_text"])])
        style.configure("Compact.Treeview", rowheight=45)
        style.configure("TLabelframe", background=p["surface"], bordercolor=p["border"])
        style.configure("TLabelframe.Label", background=p["surface"], foreground=p["text"])
        for name in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            style.configure(name, background=p["scrollbar"], troughcolor=p["bg"], bordercolor=p["bg"], arrowcolor=p["muted"])
        self.root.option_add("*TCombobox*Listbox.background", p["surface"])
        self.root.option_add("*TCombobox*Listbox.foreground", p["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", p["selection"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", p["selection_text"])

    def _walk_widgets(self, parent=None):
        parent = self.root if parent is None else parent
        yield parent
        for child in parent.winfo_children():
            yield from self._walk_widgets(child)

    def _apply_language(self):
        protected = {getattr(self, name, None) for name in ("item_properties", "listing_details")}
        if self.selected_asset:
            protected.add(self.item_title)
        for widget in self._walk_widgets():
            if widget in protected or isinstance(widget, (tk.Text, ttk.Entry, ttk.Combobox)):
                continue
            try:
                current = str(widget.cget("text"))
            except tk.TclError:
                continue
            if current != getattr(widget, "_translated_text", None):
                widget._source_text = current
            canonical = getattr(widget, "_source_text", current)
            translated = self.tr(canonical)
            widget.configure(text=translated)
            widget._translated_text = translated
        for name in ("listings_tree", "offers_tree", "logs_tree"):
            table = getattr(self, name, None)
            if table is None:
                continue
            if not hasattr(table, "_headings_source"):
                table._headings_source = {column: table.heading(column, "text") for column in table["columns"]}
            for column, title in table._headings_source.items():
                table.heading(column, text=self.tr(title))
        if hasattr(self, "language_var"):
            self.language_var.set(LANGUAGES.get(self.language, LANGUAGES["ru"]))
        if hasattr(self, "theme_picker"):
            self.theme_picker.configure(values=(self.tr("Светлая"), self.tr("Тёмная")))
            self.theme_var.set(self.tr("Светлая" if self.theme == "light" else "Тёмная"))
        self.status_var.set(self.tr(self._status_source))

    def _apply_theme(self, theme):
        old = self.palette
        self.theme = theme
        self._use_palette(theme)
        self._styles()
        p = self.palette
        backgrounds = {old[key]: p[key] for key in ("bg", "surface", "nav", "nav_active", "hover", "disabled", "item_bg")}
        foregrounds = {old[key]: p[key] for key in ("text", "muted", "nav_text", "on_accent", "success", "danger", "selection_text")}
        borders = {old[key]: p[key] for key in ("border", "item_border", "accent")}
        for widget in self._walk_widgets():
            if isinstance(widget, ttk.Widget):
                if isinstance(widget, ttk.Combobox):
                    try:
                        popup = widget.tk.call("ttk::combobox::PopdownWindow", widget._w)
                        widget.tk.call(str(popup) + ".f.l", "configure", "-background", p["surface"], "-foreground", p["text"],
                                       "-selectbackground", p["selection"], "-selectforeground", p["selection_text"])
                    except tk.TclError:
                        pass
                continue
            for option, mapping in (("background", backgrounds), ("foreground", foregrounds), ("highlightbackground", borders),
                                    ("activebackground", backgrounds), ("activeforeground", foregrounds)):
                try:
                    value = str(widget.cget(option))
                    if value in mapping:
                        widget.configure(**{option: mapping[value]})
                except tk.TclError:
                    pass
            if isinstance(widget, tk.Text):
                widget.configure(background=p["surface"], foreground=p["text"], insertbackground=p["text"],
                                 selectbackground=p["selection"], selectforeground=p["selection_text"], highlightbackground=p["border"])
        self.root.configure(bg=p["bg"])
        self.brand_label.configure(bg=p["nav"], fg=p["nav_text"])
        if hasattr(self, "placeholder"):
            del self.placeholder
        self.show_page(getattr(self, "current_page", "inventory"))
        self._set_running(self.running)
        self.refresh_views()

    def _save_preferences(self):
        self._preference_revision += 1
        revision = self._preference_revision
        self.cached_settings.update(language=self.language, theme=self.theme)
        def save():
            with self._preference_save_lock:
                if revision == self._preference_revision:
                    self.engine.set_preferences(language=self.language, theme=self.theme)
        self._run("Сохранение настроек…", save, quiet=True)

    def _change_language(self, event=None):
        self.language = next((key for key, value in LANGUAGES.items() if value == self.language_var.get()), "ru")
        self.cached_settings["language"] = self.language
        self.refresh_views()
        self._save_preferences()

    def _change_theme(self, event=None):
        theme = "dark" if self.theme_var.get() == self.tr("Тёмная") else "light"
        self._apply_theme(theme)
        self._save_preferences()

    def _layout(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        top = tk.Frame(self.root, bg=NAVY)
        top.grid(row=0, column=0, sticky="ew")
        self.brand_label = tk.Label(top, text="Backpack Seller", bg=NAVY, fg=self.palette["nav_text"],
                 font=("Segoe UI Semibold", 15))
        self.brand_label.pack(side="left", padx=(20, 24), pady=14)
        for key, text in (("inventory", "Инвентарь"), ("listings", "Объявления"),
                          ("offers", "Предложения"),
                          ("settings", "Настройки"), ("logs", "Журнал")):
            button = tk.Button(top, text=text, relief="flat", bd=0, padx=14, pady=12,
                               cursor="hand2", bg=NAVY, fg=self.palette["nav_text"],
                               activebackground=self.palette["nav_active"], activeforeground=INK,
                               font=("Segoe UI", 10), command=lambda k=key: self.show_page(k))
            button.pack(side="left", fill="y")
            self.nav_buttons[key] = button
        self.language_var = tk.StringVar(value=LANGUAGES.get(self.language, "Русский"))
        self.language_picker = ttk.Combobox(top, textvariable=self.language_var, values=tuple(LANGUAGES.values()), state="readonly", width=10)
        self.language_picker.pack(side="right", padx=16, pady=12)
        self.language_picker.bind("<<ComboboxSelected>>", self._change_language)
        if self.demo:
            tk.Label(top, text="ДЕМО", bg=NAVY, fg=self.palette["muted"], font=("Segoe UI", 9)).pack(side="right", padx=4)
        shell = ttk.Frame(self.root, padding=(20, 14, 20, 10))
        shell.grid(row=1, column=0, sticky="nsew")
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(1, weight=1)
        header = ttk.Frame(shell)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)
        self.page_title = ttk.Label(header, text="Инвентарь", font=("Segoe UI Semibold", 17))
        self.page_title.grid(row=0, column=0, sticky="w")
        self.page_subtitle = ttk.Label(header, text="")
        control = ttk.Frame(header)
        control.grid(row=0, column=1, sticky="e")
        self.monitor_label = tk.Label(control, text="●  Обмены: остановлены", bg=BG, fg=MUTED, font=("Segoe UI", 10))
        self.monitor_label.pack(side="left", padx=(0, 14))
        self.start_button = ttk.Button(control, text="Запустить", style="Accent.TButton", command=self._start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(control, text="Стоп", command=self._stop, state="disabled")
        self.stop_button.pack(side="left", padx=(7, 0))
        self.body = ttk.Frame(shell)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.grid_rowconfigure(0, weight=1)
        self.body.grid_columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="")
        footer = ttk.Frame(shell)
        footer.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        footer.grid_columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel", wraplength=1100).grid(row=0, column=0, sticky="w")
        ttk.Label(footer, text="1.0", style="Muted.TLabel").grid(row=0, column=1, sticky="e")

    def _page(self, key):
        page = ttk.Frame(self.body)
        page.grid(row=0, column=0, sticky="nsew")
        self.pages[key] = page
        return page

    @staticmethod
    def _card(parent, padding=16):
        return ttk.Frame(parent, style="Card.TFrame", padding=padding)

    @staticmethod
    def _table(parent, columns, *, icons=False, compact=False):
        box = ttk.Frame(parent, style="Card.TFrame")
        box.grid_columnconfigure(0, weight=1)
        box.grid_rowconfigure(0, weight=1)
        table = ttk.Treeview(box, columns=[x[0] for x in columns], show="tree headings" if icons else "headings",
                             selectmode="browse", style="Compact.Treeview" if compact else "Treeview")
        if icons:
            table.heading("#0", text="")
            table.column("#0", width=60, minwidth=60, stretch=False)
        for key, title, width, stretch in columns:
            table.heading(key, text=title, anchor="w")
            table.column(key, width=width, minwidth=min(width, 85), stretch=stretch, anchor="w")
        table.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(box, orient="vertical", command=table.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        table.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(box, orient="horizontal", command=table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        table.configure(xscrollcommand=horizontal.set)
        return box, table

    def _inventory_page(self):
        page = self._page("inventory")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=1)
        search = ttk.Frame(page)
        search.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        search.grid_columnconfigure(1, weight=1)
        ttk.Label(search, text="Поиск по названию").grid(row=0, column=0, padx=(0, 10))
        self.search_var = tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.search_var)
        entry.grid(row=0, column=1, sticky="ew")
        entry.bind("<Escape>", lambda event: self.search_var.set(""))
        self.filters_button = ttk.Button(search, text="Показать фильтры ▾", command=self._toggle_filters)
        self.filters_button.grid(row=0, column=2, padx=8)
        ttk.Button(search, text="Обновить инвентарь", command=self._refresh_inventory).grid(row=0, column=3)
        ttk.Button(search, text="Войти в Steam", command=self._login).grid(row=0, column=4, padx=(8, 0))
        self.search_var.trace_add("write", lambda *_: self._filter_changed())
        self.filters_open = False
        self.filter_panel = self._card(page, 12)
        self.filter_panel.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.filter_panel.grid_columnconfigure(0, weight=1)
        filter_head = self._card(self.filter_panel, 0)
        filter_head.grid(row=0, column=0, sticky="ew")
        ttk.Label(filter_head, text="Фильтры инвентаря", style="Card.TLabel").pack(side="left")
        ttk.Button(filter_head, text="Сбросить", command=self._reset_filters).pack(side="right")
        self.filter_canvas = tk.Canvas(self.filter_panel, height=150, bg=WHITE, highlightthickness=0)
        self.filter_canvas.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        fs = ttk.Scrollbar(self.filter_panel, orient="vertical", command=self.filter_canvas.yview)
        fs.grid(row=1, column=1, sticky="ns")
        self.filter_canvas.configure(yscrollcommand=fs.set)
        self.filter_panel._scroll_target = self.filter_canvas
        self.filter_content = self._card(self.filter_canvas, 0)
        fw = self.filter_canvas.create_window((0, 0), window=self.filter_content, anchor="nw")
        self.filter_canvas.bind("<Configure>", lambda e: self.filter_canvas.itemconfigure(fw, width=e.width))
        self.filter_content.bind("<Configure>", lambda e: self.filter_canvas.configure(scrollregion=self.filter_canvas.bbox("all")))
        self.filter_panel.grid_remove()
        split = ttk.Panedwindow(page, orient="horizontal")
        split.grid(row=2, column=0, sticky="nsew")
        inventory_card = self._card(split, 0)
        inventory_card.grid_columnconfigure(0, weight=1)
        inventory_card.grid_rowconfigure(1, weight=1)
        list_header = self._card(inventory_card, (12, 10))
        list_header.grid(row=0, column=0, sticky="ew")
        list_header.grid_columnconfigure(0, weight=1)
        ttk.Label(list_header, text="Обмениваемые предметы", style="Card.TLabel",
                  font=("Segoe UI Semibold", 11)).grid(row=0, column=0, sticky="w")
        self.inventory_count = ttk.Label(list_header, style="CardMuted.TLabel")
        self.inventory_count.grid(row=0, column=1, sticky="e")
        self.inventory_canvas = tk.Canvas(inventory_card, bg=WHITE, highlightthickness=0, width=900)
        self.inventory_canvas.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(inventory_card, orient="vertical", command=self.inventory_canvas.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.inventory_canvas.configure(yscrollcommand=scroll.set)
        inventory_card._scroll_target = self.inventory_canvas
        self.inventory_grid = tk.Frame(self.inventory_canvas, bg=WHITE)
        self.grid_window = self.inventory_canvas.create_window((0, 0), window=self.inventory_grid, anchor="nw")
        self.inventory_grid.bind("<Configure>", lambda e: self.inventory_canvas.configure(scrollregion=self.inventory_canvas.bbox("all")))
        self.inventory_canvas.bind("<Configure>", self._resize_inventory)
        self.inventory_canvas.bind("<MouseWheel>", self._inventory_wheel)
        pager = self._card(inventory_card, (10, 8))
        pager.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.prev_button = ttk.Button(pager, text="‹", width=3, command=lambda: self._move_inventory_page(-1))
        self.prev_button.pack(side="left")
        self.page_number = ttk.Label(pager, text="", style="CardMuted.TLabel")
        self.page_number.pack(side="left", padx=12)
        self.next_button = ttk.Button(pager, text="›", width=3, command=lambda: self._move_inventory_page(1))
        self.next_button.pack(side="left")
        self.inventory_empty = ttk.Label(pager, text="Войдите в Steam.", style="CardMuted.TLabel")
        self.inventory_empty.pack(side="right")
        split.add(inventory_card, weight=4)
        details_holder = self._card(split, 0)
        details_holder.grid_columnconfigure(0, weight=1)
        details_holder.grid_rowconfigure(0, weight=1)
        detail_canvas = tk.Canvas(details_holder, width=300, background=WHITE, bd=0, highlightthickness=0)
        detail_canvas.grid(row=0, column=0, sticky="nsew")
        detail_scroll = ttk.Scrollbar(details_holder, orient="vertical", command=detail_canvas.yview)
        detail_scroll.grid(row=0, column=1, sticky="ns")
        detail_canvas.configure(yscrollcommand=detail_scroll.set)
        details_holder._scroll_target = detail_canvas
        details = self._card(detail_canvas, (18, 17))
        detail_window = detail_canvas.create_window((0, 0), window=details, anchor="nw")
        details.bind("<Configure>", lambda event: detail_canvas.configure(scrollregion=detail_canvas.bbox("all")))
        detail_canvas.bind("<Configure>", lambda event: detail_canvas.itemconfigure(detail_window, width=event.width))
        details.grid_columnconfigure(0, weight=1)
        split.add(details_holder, weight=1)
        self.item_icon = ttk.Label(details, style="Card.TLabel", anchor="center")
        self.item_icon.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        self.item_title = ttk.Label(details, text="Выберите предмет", style="Card.TLabel",
                                    font=("Segoe UI Semibold", 15), wraplength=290)
        self.item_title.grid(row=1, column=0, sticky="ew")
        self.item_properties = ttk.Label(details, text="",
                                         style="CardMuted.TLabel", wraplength=290, justify="left")
        self.item_properties.grid(row=2, column=0, sticky="ew", pady=(9, 12))
        self.market_notes = ttk.Label(details, text="", style="CardMuted.TLabel", wraplength=290, justify="left")
        self.market_notes.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        self.sale_state = ttk.Label(details, text="", style="CardMuted.TLabel", wraplength=290)
        self.sale_state.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(details, text="Цена продажи", style="Card.TLabel", font=("Segoe UI Semibold", 11)).grid(row=5, column=0, sticky="w")
        price = self._card(details, (0, 8))
        price.grid(row=6, column=0, sticky="ew")
        price.grid_columnconfigure((0, 1), weight=1)
        self.keys_var, self.metal_var = tk.StringVar(value="0"), tk.StringVar(value="0")
        ttk.Entry(price, textvariable=self.keys_var, width=8).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Entry(price, textvariable=self.metal_var, width=10).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ttk.Label(price, text="Mann Co. Key", style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(price, text="Refined Metal", style="CardMuted.TLabel").grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(4, 0))
        ttk.Label(details, text="Описание объявления", style="Card.TLabel").grid(row=7, column=0, sticky="w", pady=(8, 5))
        self.details_text = tk.Text(details, height=4, width=30, wrap="word", relief="solid", bd=1, highlightthickness=0,
                                    background=WHITE, foreground=INK, insertbackground=INK, font=("Segoe UI", 10))
        self.details_text.grid(row=8, column=0, sticky="ew")
        ttk.Button(details, text="Составить автоматически", command=self._generate_details).grid(row=9, column=0, sticky="w", pady=(7, 0))
        footer = self._card(details_holder, (18, 10, 18, 13))
        footer.grid(row=1, column=0, columnspan=2, sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        self.publish_button = ttk.Button(footer, text="Выставить", style="Accent.TButton", command=self._publish, state="disabled")
        self.publish_button.grid(row=0, column=0, sticky="ew")
        row = self._card(footer, 0)
        row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        row.grid_columnconfigure((0, 1), weight=1)
        self.open_market_button = ttk.Button(row, text="Открыть сайт", command=self._open_market, state="disabled")
        self.open_market_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.withdraw_button = ttk.Button(row, text="Снять", command=self._withdraw_selected, state="disabled")
        self.withdraw_button.grid(row=0, column=1, sticky="ew", padx=(3, 0))

    def _listings_page(self):
        page = self._page("listings")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        header = ttk.Frame(page)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 15))
        header.grid_columnconfigure(0, weight=1)
        ttk.Button(header, text="Загрузить мои объявления", command=lambda: self._run("Загрузка объявлений…", self.engine.import_listings)).grid(row=0, column=1, sticky="e")
        ttk.Button(header, text="Бампнуть сейчас", command=lambda: self._run("Бамп объявлений…", self.engine.bump_now)).grid(row=0, column=2, padx=(8, 0))
        box, self.listings_tree = self._table(page, (("name", "Предмет", 420, True), ("price", "Цена", 270, False), ("status", "Состояние", 230, True)), compact=True)
        box.grid(row=1, column=0, sticky="nsew")
        self.listings_tree.bind("<<TreeviewSelect>>", self._select_listing)
        panel = self._card(page)
        panel.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        panel.grid_columnconfigure(0, weight=1)
        self.listing_details = ttk.Label(panel, text="", style="CardMuted.TLabel", wraplength=1000)
        self.listing_details.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self.listing_edit_button = ttk.Button(panel, text="Изменить цену", command=self._edit_listing, state="disabled")
        self.listing_edit_button.grid(row=1, column=0, sticky="e", padx=(0, 8))
        self.listing_site_button = ttk.Button(panel, text="Открыть сайт", command=self._open_listing_site, state="disabled")
        self.listing_site_button.grid(row=1, column=1, padx=(0, 8))
        self.remove_listing_button = ttk.Button(panel, text="Снять объявление", style="Danger.TButton", command=self._remove_listing, state="disabled")
        self.remove_listing_button.grid(row=1, column=2)

    def _offers_page(self):
        page = self._page("offers")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1, minsize=160)
        page.grid_rowconfigure(2, weight=2, minsize=285)
        box, self.offers_tree = self._table(page,
            (("offer", "Предложение", 130, False), ("partner", "Покупатель SteamID", 180, False),
             ("check", "Проверка", 165, False), ("status", "Состояние", 210, True)), compact=True)
        box.grid(row=1, column=0, sticky="nsew")
        self.offers_tree.configure(height=3)
        self.offers_tree.bind("<<TreeviewSelect>>", self._select_offer)
        card = self._card(page)
        card.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)
        ttk.Label(card, text="Предметы и оплата", style="Card.TLabel",
                  font=("Segoe UI Semibold", 12)).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.offer_summary = tk.Text(card, height=9, wrap="word", relief="flat", background=WHITE,
                                     foreground=INK, font=("Segoe UI", 10), state="disabled")
        self.offer_summary.grid(row=1, column=0, sticky="nsew")
        summary_scroll = ttk.Scrollbar(card, orient="vertical", command=self.offer_summary.yview)
        summary_scroll.grid(row=1, column=1, sticky="ns")
        self.offer_summary.configure(yscrollcommand=summary_scroll.set)
        controls = self._card(card, (0, 10, 0, 0))
        controls.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.offer_open_button = ttk.Button(controls, text="Открыть в Steam", command=self._open_offer, state="disabled")
        self.offer_open_button.pack(side="left")

    def _scroll_page(self, key):
        page = self._page(key)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)
        canvas = tk.Canvas(page, background=BG, bd=0, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scroll.set)
        page._scroll_target = canvas
        inner = ttk.Frame(canvas)
        inner.grid_columnconfigure(0, weight=1)
        content = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(content, width=event.width))
        return page, inner

    def _section(self, parent, title, row):
        card = self._card(parent, 19)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 13))
        card.grid_columnconfigure(1, weight=1)
        ttk.Label(card, text=title, style="Card.TLabel", font=("Segoe UI Semibold", 14)).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 13))
        return card

    def _setting_field(self, card, row, key, label, secret=False):
        ttk.Label(card, text=label, style="Card.TLabel", width=24).grid(
            row=row, column=0, sticky="w", padx=(0, 16), pady=5)
        variable = tk.StringVar()
        self.setting_vars[key] = variable
        holder = ttk.Frame(card, style="Card.TFrame")
        holder.grid(row=row, column=1, sticky="ew", pady=5)
        holder.grid_columnconfigure(0, weight=1)
        entry = ttk.Entry(holder, textvariable=variable, show="•" if secret else "")
        entry.grid(row=0, column=0, sticky="ew")
        if secret:
            def toggle():
                entry.configure(show="" if entry.cget("show") else "•")
            ttk.Button(holder, text="◉", width=3, command=toggle).grid(row=0, column=1, sticky="ns")
            self.secret_entries.append(entry)
        return entry

    def _settings_page(self):
        page, inner = self._scroll_page("settings")
        self.setting_vars = {}
        self.secret_entries = []
        steam = self._section(inner, "Steam", 0)
        self._setting_field(steam, 1, "steam_id", "SteamID64")
        self._setting_field(steam, 2, "steam_api_key", "Steam Web API Key", True)
        bar = self._card(steam, 0)
        bar.grid(row=3, column=1, sticky="w", pady=(8, 0))
        ttk.Button(bar, text="Войти в Steam", command=self._login).pack(side="left")
        ttk.Button(bar, text="Получить API Key", command=lambda: webbrowser.open("https://steamcommunity.com/dev/apikey")).pack(side="left", padx=8)
        backpack = self._section(inner, "backpack.tf", 1)
        self._setting_field(backpack, 1, "backpack_token", "User Token", True)
        ttk.Button(backpack, text="Получить токен", command=lambda: webbrowser.open("https://next.backpack.tf/developer/")).grid(row=2, column=1, sticky="w", pady=(8, 0))
        telegram = self._section(inner, "Telegram", 2)
        self._setting_field(telegram, 1, "telegram_token", "Bot Token", True)
        self._setting_field(telegram, 2, "telegram_chat_id", "Личный chat_id")
        policy = self._section(inner, "Продажи", 3)
        self._setting_field(policy, 2, "poll_interval", "Проверка офферов, сек.")
        bump = self._section(inner, "Бамп объявлений", 4)
        self.setting_vars["bump_enabled"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(bump, text="Автоматический бамп", variable=self.setting_vars["bump_enabled"]).grid(row=1, column=0, columnspan=2, sticky="w")
        self._setting_field(bump, 2, "bump_interval", "Интервал бампа, минут")
        appearance = self._section(inner, "Оформление", 5)
        ttk.Label(appearance, text="Тема", style="Card.TLabel", width=24).grid(row=1, column=0, sticky="w", padx=(0, 16))
        self.theme_var = tk.StringVar()
        self.theme_picker = ttk.Combobox(appearance, textvariable=self.theme_var, state="readonly", width=20)
        self.theme_picker.grid(row=1, column=1, sticky="w")
        self.theme_picker.bind("<<ComboboxSelected>>", self._change_theme)
        actions = ttk.Frame(page)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Сохранить", style="Accent.TButton", command=self._save_settings).pack(side="left")
        ttk.Button(actions, text="Проверить подключения", command=lambda: self._run("Проверка подключений…", self.engine.test_connections)).pack(side="left", padx=9)





    def _logs_page(self):
        page = self._page("logs")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        head = ttk.Frame(page)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 13))
        ttk.Button(head, text="Обновить", command=self._render_logs).pack(side="right")
        box, self.logs_tree = self._table(page, (("time", "Время", 175, False), ("message", "Событие", 750, True)), compact=True)
        box.grid(row=1, column=0, sticky="nsew")

    def show_page(self, key):
        self.pages[key].tkraise()
        self.current_page = key
        labels = {
            "inventory": ("Инвентарь", ""),
            "listings": ("Объявления", ""),
            "offers": ("Предложения", ""),
            "settings": ("Настройки", ""),
            "logs": ("Журнал", ""),
        }
        self.page_title.configure(text=labels[key][0])
        self.page_subtitle.configure(text=labels[key][1])
        for name, button in self.nav_buttons.items():
            button.configure(bg=self.palette["nav_active"] if name == key else NAVY, fg=self.palette["text"] if name == key else self.palette["nav_text"])
        self._apply_language()

    def _load_settings(self):
        settings = self.cached_settings
        for key, variable in self.setting_vars.items():
            default = False if key == "bump_enabled" else "30" if key == "bump_interval" else "20" if key == "poll_interval" else ""
            variable.set(settings.get(key, default))
        self._apply_language()

    def _save_settings(self):
        values = {key: var.get() for key, var in self.setting_vars.items()}
        def save():
            values.update(language=self.language, theme=self.theme)
            result = self.engine.save_settings(values)
            self.events.put(("settings_saved", self.engine.settings()))
            return result
        self._run("Сохранение настроек…", save)

    def _login(self):
        values = {key: var.get() for key, var in self.setting_vars.items()}
        def login():
            values.update(language=self.language, theme=self.theme)
            self.engine.save_settings(values)
            result = self.engine.login()
            self.events.put(("settings_saved", self.engine.settings()))
            return result
        self._run("Вход в Steam…", login)

    def refresh_views(self):
        try:
            self.inventory = self.engine.store.inventory_rows()
            self.listing_rows = self.engine.store.listings()
            self.offer_rows = self.engine.store.offers()
        except Exception:
            self._status("Не удалось прочитать локальные данные.")
            return
        self._rebuild_filters()
        self._render_inventory()
        self._render_listings()
        self._render_offers()
        self._render_logs()
        self._apply_language()

    def _render_inventory(self):
        if not hasattr(self, "inventory_grid"):
            return
        for child in self.inventory_grid.winfo_children():
            child.destroy()
        self.item_cards.clear()
        self.item_labels.clear()
        listed = {str(row.get("asset_id")) for row in self.listing_rows if row.get("status") == "active"}
        selected = {}
        for (category, name), variable in self.filter_vars.items():
            if variable.get():
                selected.setdefault(category, set()).add(name)
        visible = [row for row in self.inventory if inventory_matches(row, self.search_var.get(), selected)]
        page_size = self.grid_columns * 3
        pages = max(1, (len(visible) + page_size - 1) // page_size)
        self.page_index = min(self.page_index, pages - 1)
        for column in range(10):
            self.inventory_grid.grid_columnconfigure(column, weight=1 if column < self.grid_columns else 0, uniform="items" if column < self.grid_columns else "")
        for index, row in enumerate(visible[self.page_index * page_size:(self.page_index + 1) * page_size]):
            aid, url = str(row["asset_id"]), row.get("icon_url", "")
            color = "#" + row.get("name_color", "") if len(row.get("name_color", "")) == 6 and all(c in "0123456789abcdefABCDEF" for c in row["name_color"]) else "#D2BE8B"
            color = {"#8650ac": "#C49AE8", "#cf6a32": "#F2AA79", "#4d7455": "#9ACAA4", "#476291": "#9BB9EA"}.get(color.lower(), color)
            card = tk.Frame(self.inventory_grid, bg=self.palette["item_bg"], highlightthickness=2,
                            highlightbackground=ORANGE if aid == self.selected_asset else self.palette["item_border"], cursor="hand2")
            card.grid(row=index // self.grid_columns, column=index % self.grid_columns, sticky="nsew", padx=4, pady=4)
            card.grid_columnconfigure(0, weight=1)
            picture = tk.Label(card, image=self.images.get(url) or self._placeholder(), bg=self.palette["item_bg"], width=132, height=116)
            picture.grid(row=0, column=0, sticky="ew", pady=(5, 0))
            label = tk.Label(card, text=row.get("name", "Предмет"), bg=self.palette["item_bg"], fg=color,
                             font=("Segoe UI", 9), wraplength=135, height=3, anchor="n", justify="center")
            label.grid(row=1, column=0, sticky="ew", padx=3)
            bottom = tk.Frame(card, bg=self.palette["item_bg"])
            bottom.grid(row=2, column=0, sticky="ew", padx=3, pady=(0, 5))
            tk.Label(bottom, text=self.tr("Выставлен") if aid in listed else "", fg="#91C99D", bg=self.palette["item_bg"], font=("Segoe UI", 9)).pack(side="left")
            for widget in (card, picture, label):
                widget.bind("<Button-1>", lambda e, a=aid: self._select_inventory(a))
                widget.bind("<MouseWheel>", self._inventory_wheel)
            self.item_cards[aid] = card
            self.item_labels[aid] = picture
            self._queue_image(url)
        self.inventory_count.configure(text=f"{len(visible)} из {len(self.inventory)}")
        self.page_number.configure(text=f"{self.page_index + 1} / {pages}")
        self.prev_button.configure(state="normal" if self.page_index else "disabled")
        self.next_button.configure(state="normal" if self.page_index < pages - 1 else "disabled")
        self.inventory_empty.configure(text="" if visible else "Ничего не найдено." if self.inventory else "Войдите в Steam и обновите инвентарь.")
        if self.selected_asset and not any(str(r.get("asset_id")) == self.selected_asset for r in [*self.inventory, *self.listing_rows]):
            self.selected_asset = None
            self.item_title.configure(text="Выберите предмет")
            self.item_properties.configure(text="")
            self.item_icon.configure(image="")
            self.publish_button.configure(state="disabled")
            self.withdraw_button.configure(state="disabled")
            self.sale_state.configure(text="")
            self.open_market_button.configure(state="disabled")
            self.market_notes.configure(text="")
        elif self.selected_asset:
            self._select_inventory(self.selected_asset)
        self._tag_widget_tree(self.inventory_grid)

    def _resize_inventory(self, event):
        self.inventory_canvas.itemconfigure(self.grid_window, width=event.width)
        columns = max(3, min(9, event.width // 150))
        if columns != self.grid_columns:
            self.grid_columns = columns
            self.page_index = 0
            self._render_inventory()

    def _inventory_wheel(self, event):
        self.inventory_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _move_inventory_page(self, direction):
        self.page_index = max(0, self.page_index + direction)
        self.inventory_canvas.yview_moveto(0)
        self._render_inventory()

    def _filter_changed(self):
        self.page_index = 0
        self._render_inventory()

    def _toggle_filters(self):
        self.filters_open = not self.filters_open
        if self.filters_open:
            self.filter_panel.grid()
        else:
            self.filter_panel.grid_remove()
        self.filters_button.configure(text="Скрыть фильтры ▴" if self.filters_open else "Показать фильтры ▾")
        self._apply_language()

    def _reset_filters(self):
        for variable in self.filter_vars.values():
            variable.set(False)
        self.search_var.set("")
        self._filter_changed()

    def _rebuild_filters(self):
        groups = {}
        for row in self.inventory:
            tags = row.get("filter_tags") or inventory_tags(row.get("description") or {})
            if not tags:
                tags = [dict(category=k, name=str(row[v]), label=str(row[v])) for k, v in (("Quality", "quality"), ("Type", "type")) if row.get(v)]
                row["filter_tags"] = tags
            for tag in tags:
                group = groups.setdefault(tag["category"], {})
                value = group.setdefault(tag["name"], [tag["label"], 0])
                value[1] += 1
        signature = repr(groups)
        if signature == self.filter_signature:
            return
        self.filter_signature = signature
        previous = {key for key, var in self.filter_vars.items() if var.get()}
        self.filter_vars.clear()
        for child in self.filter_content.winfo_children():
            child.destroy()
        names = {"Quality": "Качество", "Type": "Тип", "Class": "Класс", "Rarity": "Редкость", "Collection": "Коллекция", "Exterior": "Износ"}
        order = sorted(groups, key=lambda c: (list(names).index(c) if c in names else 99, c))
        def wheel(event):
            self.filter_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"
        self.filter_canvas.bind("<MouseWheel>", wheel)
        self.filter_content.bind("<MouseWheel>", wheel)
        for index, category in enumerate(order):
            box = self._card(self.filter_content, (0, 0, 20, 12))
            box.grid(row=index // 5, column=index % 5, sticky="nw")
            ttk.Label(box, text=names.get(category, category), style="Card.TLabel", font=("Segoe UI Semibold", 10)).pack(anchor="w", pady=(0, 5))
            for name, (label, count) in sorted(groups[category].items(), key=lambda item: item[1][0]):
                variable = tk.BooleanVar(value=(category, name) in previous)
                self.filter_vars[(category, name)] = variable
                check = ttk.Checkbutton(box, text=f"{label} ({count})", variable=variable, style="SteamFilter.TCheckbutton", command=self._filter_changed)
                check.pack(anchor="w")
                check.bind("<MouseWheel>", wheel)
        if not groups:
            ttk.Label(self.filter_content, text="Фильтры появятся после загрузки инвентаря.", style="CardMuted.TLabel").pack(anchor="w")
        self._tag_widget_tree(self.filter_content)

    def _install_input_support(self):
        self.root.bind_class("SellerEditing", "<Control-KeyPress>", self._editing_shortcut)
        self.root.bind_class("SellerEditing", "<Shift-Insert>", lambda e: self._editing_action(e.widget, "paste"))
        self.root.bind_class("SellerEditing", "<Control-Insert>", lambda e: self._editing_action(e.widget, "copy"))
        self.root.bind_class("SellerEditing", "<Shift-Delete>", lambda e: self._editing_action(e.widget, "cut"))
        self.root.bind_class("SellerEditing", "<Button-3>", self._editing_menu)
        self.root.bind_class("SellerWheel", "<MouseWheel>", self._route_wheel)
        self.root.bind_class("SellerWheel", "<Button-4>", lambda e: self._route_wheel(e, 120))
        self.root.bind_class("SellerWheel", "<Button-5>", lambda e: self._route_wheel(e, -120))
        self._tag_widget_tree(self.root)

    def _tag_widget_tree(self, widget):
        tags = list(widget.bindtags())
        if "SellerWheel" not in tags:
            tags.insert(0, "SellerWheel")
        if isinstance(widget, (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text)) and "SellerEditing" not in tags:
            tags.insert(0, "SellerEditing")
        widget.bindtags(tuple(tags))
        for child in widget.winfo_children():
            self._tag_widget_tree(child)

    def _editing_shortcut(self, event):
        # Windows virtual key codes remain C/V/X/A even in a Cyrillic layout.
        action = {67: "copy", 86: "paste", 88: "cut", 65: "all"}.get(event.keycode)
        if action:
            return self._editing_action(event.widget, action)

    def _editing_action(self, widget, action):
        try:
            if action == "all":
                if isinstance(widget, tk.Text):
                    widget.tag_add("sel", "1.0", "end-1c")
                    widget.mark_set("insert", "end-1c")
                else:
                    widget.selection_range(0, "end")
                    widget.icursor("end")
            else:
                widget.event_generate({"copy": "<<Copy>>", "paste": "<<Paste>>", "cut": "<<Cut>>"}[action])
        except tk.TclError:
            pass
        return "break"

    def _editing_menu(self, event):
        event.widget.focus_set()
        menu = tk.Menu(self.root, tearoff=False, background=self.palette["surface"], foreground=self.palette["text"], activebackground=self.palette["selection"], activeforeground=self.palette["selection_text"])
        for title, action in (("Копировать", "copy"), ("Вставить", "paste"), ("Вырезать", "cut"), ("Выделить всё", "all")):
            menu.add_command(label=self.tr(title), command=lambda a=action, w=event.widget: self._editing_action(w, a))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _route_wheel(self, event, delta=None):
        delta = event.delta if delta is None else delta
        if not delta:
            return "break"
        direction = -1 if delta > 0 else 1
        widget = event.widget
        while widget is not None:
            target = getattr(widget, "_scroll_target", None)
            if target is None and isinstance(widget, (tk.Text, ttk.Treeview, tk.Listbox)):
                target = widget
            if target is not None:
                try:
                    first, last = target.yview()
                    if (direction < 0 and first > 0) or (direction > 0 and last < 1):
                        target.yview_scroll(direction * max(1, int(abs(delta) / 120) * 3), "units")
                        return "break"
                except tk.TclError:
                    pass
            widget = getattr(widget, "master", None)
        return "break"

    def _market_item(self, asset_id):
        item = dict(next((r for r in self.inventory if str(r.get("asset_id")) == str(asset_id)), {}))
        listing = next((r for r in self.listing_rows if str(r.get("asset_id")) == str(asset_id)), {})
        item.setdefault("name", listing.get("name", "Предмет"))
        if listing.get("backpack_item"):
            item["backpack_item"] = listing["backpack_item"]
        return item

    def _open_market_for(self, asset_id):
        from market import market_link
        link = market_link(self._market_item(asset_id))
        if link["url"].startswith(("https://backpack.tf/classifieds?", "https://next.backpack.tf/classifieds?")):
            webbrowser.open(link["url"])

    def _open_market(self):
        if self.selected_asset:
            self._open_market_for(self.selected_asset)

    def _open_listing_site(self):
        if self.selected_listing:
            self._open_market_for(self.selected_listing)

    def _edit_listing(self):
        if self.selected_listing:
            self.show_page("inventory")
            self._select_inventory(self.selected_listing, force=True)

    def _generate_details(self):
        if self.selected_asset:
            from domain import parse_price
            try:
                price = parse_price(self.keys_var.get(), self.metal_var.get())
            except ValueError as error:
                self._status(str(error))
                return
            item = self._market_item(self.selected_asset)
            template = self.cached_settings.get("description_template") or "Selling {name} for {price}. {paint} Send a trade offer."
            value = template.format(name=item.get("name", ""), price=price_text(price), paint=item.get("paint", ""))
            self.details_text.delete("1.0", "end")
            self.details_text.insert("1.0", value.strip())

    def _publish(self):
        if not self.selected_asset:
            return
        active = next((r for r in self.listing_rows if str(r.get("asset_id")) == self.selected_asset
                       and r.get("status") not in {"removed", "sold", "error"}), None)
        operation = self.engine.relist if active else self.engine.publish
        self._run("Перевыставление объявления…" if active else "Публикация объявления…", operation,
                  self.selected_asset, self.keys_var.get(), self.metal_var.get(), self.details_text.get("1.0", "end-1c"))

    def _withdraw_selected(self):
        if self.selected_asset:
            self.selected_listing = self.selected_asset
            self._remove_listing()

    def _remove_listing(self):
        if self.selected_listing and messagebox.askyesno(self.tr("Снять объявление"), self.tr("Снять выбранное объявление с backpack.tf?"), parent=self.root):
            self._run("Снятие объявления…", self.engine.remove_listing, self.selected_listing)

    def _refresh_inventory(self):
        self.image_failed.clear()
        self._run("Загрузка инвентаря…", self.engine.refresh_inventory)

    def _select_inventory(self, asset_id, force=False):
        asset_id = str(asset_id)
        row = next((r for r in self.inventory if str(r.get("asset_id")) == asset_id), None)
        listing = next((r for r in self.listing_rows if str(r.get("asset_id")) == asset_id), {})
        if row is None and not listing:
            return
        changed = self.selected_asset != asset_id or force
        self.selected_asset = asset_id
        row = row or {"name": listing.get("name", "Предмет"), "icon_url": ""}
        for key, card in self.item_cards.items():
            card.configure(highlightbackground=ORANGE if key == asset_id else self.palette["item_border"])
        self.item_title.configure(text=row.get("name", "Предмет"))
        props = [str(row.get("quality") or ""), str(row.get("paint") or "")]
        props.extend(str(value) for value in row.get("spells") or [])
        self.item_properties.configure(text="\n".join(filter(None, props)))
        self.item_icon.configure(image=self.large_images.get(row.get("icon_url")) or self._placeholder())
        from market import market_link
        notes = market_link(self._market_item(asset_id)).get("manual", [])
        self.market_notes.configure(text="Проверьте на сайте:\n" + "\n".join(notes) if notes else "")
        self.open_market_button.configure(state="normal")
        active = listing.get("status") in {"active", "unsupported_price"}
        reserved = bool(listing.get("reserved_by"))
        self.publish_button.configure(text="Перевыставить" if active else "Выставить", state="disabled" if reserved or listing.get("status") in {"updating", "update_unknown", "publishing", "publish_unknown", "removing", "remove_unknown"} else "normal")
        removable = listing.get("status") in {"active", "external_change", "publish_unknown", "remove_unknown", "update_unknown", "unsupported_price"}
        self.withdraw_button.configure(state="normal" if removable and not reserved else "disabled")
        self.sale_state.configure(text=("Текущая цена: " + price_text(listing)) if active else self.tr(status_text(listing.get("status"))) if listing else "")
        if changed:
            self.keys_var.set(str(listing.get("keys", 0)))
            from domain import refined_text
            self.metal_var.set(refined_text(int(listing.get("metal_scrap", 0))))
            self.details_text.delete("1.0", "end")
            self.details_text.insert("1.0", listing.get("details", ""))
        self._apply_language()

    def _render_listings(self):
        selected = self.listings_tree.selection()
        aid = selected[0] if selected else None
        self.listings_tree.delete(*self.listings_tree.get_children())
        for row in self.listing_rows:
            asset = str(row.get("asset_id", ""))
            if asset:
                self.listings_tree.insert("", "end", iid=asset, values=(row.get("name", "—"), self.tr(price_text(row)), self.tr(status_text(row.get("status")))))
        if aid and self.listings_tree.exists(aid):
            self.listings_tree.selection_set(aid)

    def _select_listing(self, event=None):
        selected = self.listings_tree.selection()
        if not selected:
            return
        self.selected_listing = selected[0]
        row = next((r for r in self.listing_rows if str(r.get("asset_id")) == self.selected_listing), {})
        self.listing_details.configure(text=row.get("details") or self.tr("Описание не задано."))
        self.listing_site_button.configure(state="normal")
        self.listing_edit_button.configure(state="disabled" if row.get("reserved_by") else "normal")
        self.remove_listing_button.configure(state="normal" if not row.get("reserved_by") and row.get("status") not in {"removed", "sold", "removing"} else "disabled")

    def _render_offers(self):
        selected = self.offers_tree.selection()
        oid = selected[0] if selected else None
        self.offers_tree.delete(*self.offers_tree.get_children())
        for row in self.offer_rows:
            offer = str(row.get("offer_id", ""))
            if not offer:
                continue
            state = row.get("status")
            if state in {"accepted", "completed"}:
                check = "Завершено"
            elif state in {"accepting", "accept_unknown", "needs_confirmation", "confirmation_sent", "in_escrow", "decline_sent"}:
                check = "—"
            else:
                check = "Сумма верна" if row.get("valid") else "Не прошло проверку"
            self.offers_tree.insert("", "end", iid=offer, values=(f"#{offer}", row.get("partner") or "—", self.tr(check), self.tr(status_text(state))))
        if oid and self.offers_tree.exists(oid):
            self.offers_tree.selection_set(oid)

    def _select_offer(self, event=None):
        selected = self.offers_tree.selection()
        if not selected:
            return
        self.selected_offer = selected[0]
        row = next((r for r in self.offer_rows if str(r.get("offer_id")) == self.selected_offer), {})
        summary = row.get("summary") or "Состав предложения ещё не получен."
        if isinstance(summary, (dict, list)):
            import json
            summary = json.dumps(summary, ensure_ascii=False, indent=2)
        text = self.tr(str(summary))
        if row.get("status") == "blocked" and row.get("reason"):
            text += "\n\n" + self.tr(row["reason"])
        self.offer_summary.configure(state="normal")
        self.offer_summary.delete("1.0", "end")
        self.offer_summary.insert("1.0", text)
        self.offer_summary.configure(state="disabled")
        actionable = row.get("status") in {"waiting", "blocked", "pending", "new"}
        self.offer_open_button.configure(state="normal")

    def _open_offer(self):
        if self.selected_offer and self.selected_offer.isdigit():
            webbrowser.open(f"https://steamcommunity.com/tradeoffer/{self.selected_offer}/")





    def _render_logs(self):
        if not hasattr(self, "logs_tree"):
            return
        rows = self.engine.store.logs()
        self.logs_tree.delete(*self.logs_tree.get_children())
        for index, row in enumerate(rows):
            time = str(row.get("time", "")).replace("T", " ")[:19]
            self.logs_tree.insert("", "end", iid=str(index), values=(time, self.tr(row.get("message", ""))))

    def _start(self):
        self._run("Запуск наблюдения…", self.engine.start, after="started")

    def _stop(self):
        self._run("Остановка наблюдения…", self.engine.stop, after="stopped")

    def _set_running(self, enabled):
        self.running = bool(enabled)
        self.monitor_label.configure(text="●  Обмены: включены" if enabled else "●  Обмены: остановлены", fg=GREEN if enabled else MUTED)
        self.start_button.configure(state="disabled" if enabled else "normal")
        self.stop_button.configure(state="normal" if enabled else "disabled")

    def _run(self, label, function, *args, after=None, quiet=False):
        if self.closed:
            return
        self._status(label)
        self.busy += 1

        def execute():
            try:
                result = function(*args)
                self.events.put(("task_done", {"result": result, "after": after}))
            except Exception as error:
                safe = getattr(error, "public_message", None)
                if safe is None:
                    safe = str(error) if isinstance(error, (ValueError, RuntimeError)) else f"Не удалось выполнить действие ({type(error).__name__})."
                self.engine.log(label.rstrip("…") + ": " + str(safe))
                self.events.put(("background_error" if quiet else "task_error", str(safe)))
        threading.Thread(target=execute, daemon=True).start()

    def _drain(self):
        if self.closed:
            return
        changed = False
        for _ in range(80):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if not isinstance(event, tuple) or len(event) != 2:
                continue
            kind, payload = event
            if kind == "task_done":
                self.busy = max(0, self.busy - 1)
                if payload.get("after") == "started":
                    self._set_running(True)
                elif payload.get("after") == "stopped":
                    self._set_running(False)
                result = payload.get("result")
                self._status(result if isinstance(result, str) and result else "Готово.")
                changed = True
            elif kind in {"task_error", "background_error"}:
                self.busy = max(0, self.busy - 1)
                self._status(payload)
                changed = True
                if kind == "task_error":
                    messagebox.showerror(self.tr("Не удалось выполнить действие"), self.tr(payload), parent=self.root)
            elif kind == "image":
                self._image_received(*payload)
            elif kind == "preferences_changed" and isinstance(payload, dict):
                if payload.get("language", self.language) == self.language and payload.get("theme", self.theme) == self.theme:
                    self.cached_settings.update(payload)
                changed = True
            elif kind in {"settings_saved", "settings_changed"} and isinstance(payload, dict):
                self.cached_settings = payload
                self._load_settings()
                changed = True
            elif kind in ("running", "started", "stopped"):
                self._set_running(bool(payload) if kind == "running" else kind == "started")
            else:
                if kind in ("status", "progress") and isinstance(payload, str):
                    self._status(payload)
                changed = kind != "progress" or changed
        if changed:
            self.refresh_views()
        self.root.after(100, self._drain)

    def _placeholder(self):
        if not hasattr(self, "placeholder"):
            self.placeholder = tk.PhotoImage(master=self.root, width=112, height=112)
            self.placeholder.put(self.palette["item_bg"], to=(0, 0, 112, 112))
            self.placeholder.put(self.palette["placeholder"], to=(34, 32, 78, 77))
            self.placeholder.put(self.palette["item_bg"], to=(42, 42, 70, 67))
        return self.placeholder

    def _queue_image(self, url):
        if not url or url in self.images or url in self.image_waiting or url in self.image_failed:
            return
        if self.demo:
            if url.startswith("demo:"):
                filename = url.removeprefix("demo:")
                if filename in {"rocket.png", "captain.png", "unusual.png"}:
                    file = self.asset_root / "demo" / filename
                    if file.is_file():
                        self._image_received(url, file.read_bytes())
            return
        if not allowed_image(url):
            return
        self.image_waiting.add(url)
        self.image_queue.put(url)

    def _image_worker(self):
        import requests
        session = requests.Session()
        while not self.closed:
            try:
                url = self.image_queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                blob = load_image(url, self.engine.root / "images", session)
                self.events.put(("image", (url, blob)))
            except (ValueError, OSError):
                self.events.put(("image", (url, b"")))
        session.close()

    def _image_received(self, url, blob):
        self.image_waiting.discard(url)
        try:
            with Image.open(io.BytesIO(blob)) as source:
                picture = ImageTk.PhotoImage(ImageOps.contain(source.convert("RGBA"), (112, 112), Image.Resampling.LANCZOS), master=self.root)
                large = ImageTk.PhotoImage(ImageOps.contain(source.convert("RGBA"), (180, 180), Image.Resampling.LANCZOS), master=self.root)
        except (OSError, ValueError, tk.TclError):
            self.image_failed.add(url)
            self._status("Часть картинок Steam не загрузилась. «Обновить инвентарь» повторит загрузку.")
            return
        self.images[url] = picture
        self.large_images[url] = large
        for row in self.inventory:
            if row.get("icon_url") == url:
                aid = str(row.get("asset_id"))
                label = self.item_labels.get(aid)
                if label is not None and label.winfo_exists():
                    label.configure(image=picture)
                if aid == self.selected_asset:
                    self.item_icon.configure(image=large)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.root.withdraw()

        def finish():
            try:
                self.engine.close()
            except Exception:
                pass
            self.events.put(("closed", None))
        threading.Thread(target=finish, daemon=True).start()
        # Close the window even if a request is still waiting for a response.
        self.root.after(200, self.root.destroy)


def main():
    from engine import SellerEngine
    parser = argparse.ArgumentParser(description="Backpack Seller · TF2")
    parser.add_argument("--demo", action="store_true", help="Open a local demonstration without network access.")
    parser.add_argument("--data-dir", type=Path, help="Separate local data directory.")
    parser.add_argument("--self-check", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.self_check:
        from runtime_check import run
        return run(args.self_check)
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    data = args.data_dir or base / ("demo-data" if args.demo else "data")
    root = tk.Tk()
    events = queue.Queue()
    try:
        engine = SellerEngine(data, on_event=lambda kind, payload=None: events.put((kind, payload)), demo=args.demo)
    except Exception as error:
        root.withdraw()
        messagebox.showerror("Backpack Seller", str(error) if isinstance(error, (ValueError, RuntimeError)) else "Не удалось открыть программу.", parent=root)
        root.destroy()
        return 1
    App(root, engine, events)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
