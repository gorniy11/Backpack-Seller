"""Translations must leave item names and user text unchanged."""
import unittest

from i18n import CATALOG, LANGUAGES, get_language, set_language, translate


class LocalizationTests(unittest.TestCase):
    def tearDown(self):
        set_language("ru")

    def test_only_supported_languages_are_selected(self):
        self.assertEqual(set(LANGUAGES), {"ru", "en"})
        set_language("en")
        self.assertEqual(get_language(), "en")
        self.assertEqual(translate("Настройки"), "Settings")
        for value in ("de", "EN", "", None, 1):
            with self.assertRaises(ValueError):
                set_language(value)
        self.assertEqual(get_language(), "en")

    def test_russian_is_the_unchanged_source(self):
        message = "Предложение #123\n\nВаши предметы:\n• Шляпа, подаренная другом × 1"
        self.assertEqual(translate(message, "ru"), message)
        self.assertEqual(translate(None, "ru"), "")

    def test_static_controls_cover_all_new_user_flows(self):
        expected = {
            "Инвентарь": "Inventory", "Объявления": "Listings", "Предложения": "Trade offers",
            "Светлая": "Light", "Тёмная": "Dark", "Выставить на backpack.tf": "List on backpack.tf",
            "Снять объявление": "Remove listing", "Перевыставить": "Relist",
            "Автоматический бамп": "Automatic bump", "Интервал бампа, минут": "Bump interval, minutes",
            "Бампнуть сейчас": "Bump now", "Открыть backpack.tf": "Open backpack.tf",
            "Проверить подключения": "Test connections", "Копировать": "Copy", "Вставить": "Paste",
            "Нужна сверка изменений": "Update needs reconciliation",
        }
        for source, destination in expected.items():
            self.assertEqual(translate(source, "en"), destination)

    def test_dynamic_listing_messages_preserve_item_names_and_price(self):
        message = "Объявление опубликовано: Моя русская шляпа · 1 Mann Co. Key + 15 Refined Metal."
        self.assertEqual(translate(message, "en"),
                         "Listing published: Моя русская шляпа · 1 Mann Co. Key + 15 Refined Metal.")
        self.assertEqual(translate("Объявление снято: Настройки.", "en"), "Listing removed: Настройки.")
        self.assertEqual(translate("Объявление перевыставлено: The Team Captain · 2 Mann Co. Key.", "en"),
                         "Listing relisted: The Team Captain · 2 Mann Co. Key.")

    def test_offer_summary_translates_structure_without_translating_item_values(self):
        source = ("Предложение #12345\n\nВаши предметы:\n• Настройки × 1\n"
                  "• Шляпа друга (Paint Color: Pink as Hell) × 2\n\nПокупатель предлагает:\n"
                  "• Mann Co. Supply Crate Key × 1\n• Refined Metal × 15")
        result = translate(source, "en")
        self.assertIn("Trade offer #12345", result)
        self.assertIn("Your items:", result)
        self.assertIn("Buyer offers:", result)
        self.assertIn("• Настройки × 1", result)
        self.assertIn("• Шляпа друга (Paint Color: Pink as Hell) × 2", result)
        self.assertEqual(result.count("\n"), source.count("\n"))

    def test_telegram_acceptance_notice_has_no_untranslated_program_structure(self):
        source = ("Проверка пройдена: вещи и оплата совпадают с действующим объявлением backpack.tf.\n"
                  "Сверенная цена: 1 Mann Co. Key + 15 Refined Metal\n"
                  "Программа приняла предложение. Подтвердите обмен вручную в Steam.\n\n"
                  "Предложение #123\n\nВаши предметы:\n• Team Captain × 1\n\n"
                  "Покупатель предлагает:\n• Refined Metal × 15")
        result = translate(source, "en")
        self.assertFalse(any("\u0400" <= char <= "\u04ff" for char in result), result)
        self.assertIn("Confirm the trade manually in Steam.", result)
        self.assertIn("Verified price:", result)

    def test_rejected_notice_translates_known_reason_and_preserves_composition(self):
        source = ("Обмен не принят. Цена не совпадает: нужно 1 Mann Co. Key, предложено 15 Refined Metal\n\n"
                  "Ваши предметы:\n• Team Captain × 1")
        result = translate(source, "en")
        self.assertIn("Trade not accepted. Price mismatch: required 1 Mann Co. Key, offered 15 Refined Metal", result)
        self.assertIn("Your items:", result)

    def test_http_status_and_safe_error_hints_are_localized(self):
        self.assertEqual(translate("Steam: HTTP 429, слишком много запросов; повторите позднее.", "en"),
                         "Steam: HTTP 429, too many requests; try again later.")
        self.assertEqual(translate("backpack.tf: HTTP 503, ошибка сервера.", "en"),
                         "backpack.tf: HTTP 503, server error.")
        self.assertEqual(translate("Некорректный числовой размер инвентаря.", "en"),
                         "Invalid numeric inventory size.")

    def test_multiline_log_preserves_line_endings_and_unknown_user_content(self):
        source = "Steam: соединение и авторизация подтверждены\r\nTelegram: не настроен\r\n"
        self.assertEqual(translate(source, "en"),
                         "Steam: connection and authentication confirmed\r\nTelegram: not configured\r\n")
        for value in ("Моя собственная подпись", "Literal {name}: Компания", "https://example.test/Настройки", "abc:my-password"):
            self.assertEqual(translate(value, "en"), value)

    def test_import_counts_and_numeric_inventory_counts_are_translated(self):
        self.assertEqual(translate("Объявления загружены. Активных: 14. Новых: 12. С неподдерживаемой ценой: 2.", "en"),
                         "Listings loaded. Active: 14. New: 12. Unsupported prices: 2.")
        self.assertEqual(translate("51 из 100", "en"), "51 of 100")
        self.assertEqual(translate("Загружен инвентарь: 51 обмениваемых предметов.", "en"),
                         "Inventory loaded: 51 tradable items.")
        self.assertEqual(translate("Текущая цена: 1 Mann Co. Key + 15 Refined Metal", "en"),
                         "Current price: 1 Mann Co. Key + 15 Refined Metal")

    def test_catalog_values_are_english_except_the_native_language_name(self):
        for source, destination in CATALOG.items():
            if source != "Русский":
                self.assertFalse(any("\u0400" <= char <= "\u04ff" for char in destination), (source, destination))


if __name__ == "__main__":
    unittest.main()
