"""English translations of the app's Russian messages.

Translate complete messages only. Item names and user text inside templates
must stay unchanged.
"""
from __future__ import annotations

import re
import threading


LANGUAGES = {"ru": "Русский", "en": "English"}
_language = "ru"
_lock = threading.RLock()


def set_language(language):
    if not isinstance(language, str) or language not in LANGUAGES:
        raise ValueError("Unsupported language")
    global _language
    with _lock:
        _language = language


def get_language():
    with _lock:
        return _language


CATALOG = {
    "Проверка пройдена.": "Validation passed.",
    "Проверка не пройдена.": "Validation failed.",
    "Вещи и оплата совпадают с объявлением.": "Items and payment match your listing.",
    "Обмен выполняется вручную в Steam.": "Handle this trade manually in Steam.",
    "Не удалось сверить объявление backpack.tf. Проверьте условия вручную.": "The backpack.tf listing could not be verified. Check the terms manually.",
    "Инвентарь": "Inventory", "Объявления": "Listings", "Предложения": "Trade offers",
    "Настройки": "Settings", "Шаблон описания": "Description template", "Журнал": "Activity log", "ДЕМО": "DEMO",
    "Язык": "Language", "Русский": "Русский", "Английский": "English",
    "Тема": "Theme", "Тема оформления": "Theme", "Оформление": "Appearance",
    "Светлая": "Light", "Тёмная": "Dark", "Темная": "Dark",
    "Светлая тема": "Light theme", "Тёмная тема": "Dark theme", "Темная тема": "Dark theme",
    "Интерфейс": "Interface", "Внешний вид": "Appearance", "Основные": "General",
    "Сохранить": "Save", "Сохранение настроек…": "Saving settings…",
    "Сохранено": "Saved", "Настройки сохранены.": "Settings saved.",
    "Готово.": "Done.", "Обновить": "Refresh", "Сбросить": "Reset",
    "Запустить": "Start", "Стоп": "Stop", "Остановить": "Stop",
    "Запуск наблюдения…": "Starting monitoring…", "Остановка наблюдения…": "Stopping monitoring…",
    "Наблюдение запущено.": "Monitoring started.", "Включено": "Enabled", "Выключено": "Disabled",
    "Да": "Yes", "Нет": "No", "Отмена": "Cancel", "Отменить": "Cancel",
    "Принять": "Accept", "Подтвердить": "Confirm", "Закрыть": "Close",
    "●  Обмены: включены": "●  Trades: running", "●  Обмены: остановлены": "●  Trades: stopped",
    "●  Наблюдение включено": "●  Monitoring is running", "●  Остановлен": "●  Stopped",
    "Копировать": "Copy", "Вставить": "Paste", "Вырезать": "Cut", "Выделить всё": "Select all",
    "Предмет": "Item", "Предмет TF2": "TF2 item", "Цена": "Price", "Цена продажи": "Sale price",
    "Описание": "Description", "Описание объявления": "Listing description", "Состояние": "Status",
    "Время": "Time", "Событие": "Event", "Проверка": "Validation", "Покупатель SteamID": "Buyer SteamID",
    "Предложение": "Offer", "Предметы и оплата": "Items and payment", "Ваши предметы": "Your items",
    "Покупатель предлагает": "Buyer offers", "• Нет предметов": "• No items", "Нет предметов": "No items",
    "Выставлен": "Listed", "Выставлено": "Listed", "Не выставлен": "Not listed",
    "Новое": "New", "Ожидает решения": "Awaiting review", "Принимается": "Accepting",
    "Обмен завершён": "Trade completed", "Завершено": "Completed", "Продано": "Sold",
    "Отклонено": "Declined", "Заблокировано": "Blocked", "Не прошло проверку": "Validation failed",
    "Сумма верна": "Payment matches", "Подтверждение Steam": "Steam confirmation",
    "Подтверждение отправлено": "Confirmation sent", "Удержание Steam": "Steam hold",
    "Нужна сверка": "Reconciliation needed", "Нужна сверка приёма": "Acceptance needs reconciliation",
    "Нужна сверка публикации": "Publication needs reconciliation", "Нужна сверка удаления": "Removal needs reconciliation",
    "Нужна сверка перевыставления": "Relisting needs reconciliation",
    "Изменение объявления": "Updating listing", "Нужна сверка изменения": "Update needs reconciliation",
    "Нужна сверка изменений": "Update needs reconciliation",
    "Приём отправлен": "Acceptance submitted", "Отказ отправлен": "Decline submitted",
    "Объявление изменено": "Listing changed", "Публикация": "Publishing", "Перевыставление": "Relisting",
    "Снятие объявления": "Removing listing", "Снято": "Removed", "Отменено": "Canceled",
    "Истекло": "Expired", "Недоступно": "Unavailable", "Ошибка": "Error",
    "Ручное решение": "Manual review", "Встречное предложение": "Counteroffer",
    "Неподдерживаемая валюта": "Unsupported currency", "Проверьте валюту на сайте": "Check currency on the website",
    "Выберите предмет": "Select an item", "Сначала выберите предмет.": "Select an item first.",
    "Обмениваемые предметы": "Tradable items", "Поиск по названию": "Search by name",
    "Фильтры инвентаря": "Inventory filters", "Показать фильтры ▾": "Show filters ▾",
    "Скрыть фильтры ▴": "Hide filters ▴", "Качество": "Quality", "Класс": "Class", "Тип": "Type",
    "Коллекция": "Collection", "Редкость": "Rarity", "Износ": "Wear", "Краска": "Paint",
    "Фильтры появятся после загрузки инвентаря.": "Filters will appear after the inventory loads.",
    "Ничего не найдено.": "Nothing found.", "Войдите в Steam.": "Sign in to Steam.",
    "Войдите в Steam и обновите инвентарь.": "Sign in to Steam and refresh the inventory.",
    "Войти в Steam": "Sign in to Steam", "Вход в Steam…": "Signing in to Steam…",
    "Обновить инвентарь": "Refresh inventory", "Загрузка инвентаря…": "Loading inventory…",
    "Загрузить мои объявления": "Load my listings", "Загрузка объявлений…": "Loading listings…",
    "Сверить с backpack.tf": "Sync with backpack.tf", "Сверка объявлений…": "Syncing listings…",
    "Сверка объявлений backpack.tf…": "Syncing backpack.tf listings…",
    "Открыть backpack.tf": "Open backpack.tf", "Открыть в Steam": "Open in Steam",
    "Открыть обмен в Steam": "Open trade in Steam", "Открыть на сайте": "Open on website",
    "Открыть сайт": "Open website", "Открыть с фильтрами": "Open with filters",
    "Опубликовать": "Publish", "Выставить": "List item", "Выставить на backpack.tf": "List on backpack.tf",
    "Опубликовать объявление": "Publish listing", "Публикация объявления…": "Publishing listing…",
    "Снять": "Remove", "Снять объявление": "Remove listing", "Снятие объявления…": "Removing listing…",
    "Снять для перевыставления": "Remove to relist", "Перевыставить": "Relist",
    "Перевыставить объявление": "Relist item", "Перевыставление объявления…": "Relisting item…",
    "Изменить цену": "Change price", "Обновить объявление": "Update listing",
    "Цена и описание": "Price and description", "Составить автоматически": "Generate description",
    "Описание не задано.": "No description provided.", "Проверьте на сайте:": "Check on the website:",
    "Стиль": "Style",
    "Счётчики Strange": "Strange counters",
    "Номер ковки": "Craft number", "Номер медали": "Medal number", "Серия ящика": "Crate series",
    "Дополнительные свойства": "Additional properties",
    "Снять выбранное объявление с backpack.tf?": "Remove the selected listing from backpack.tf?",
    "Перевыставить выбранное объявление?": "Relist the selected item?",
    "Опубликовать выбранный предмет на backpack.tf?": "Publish the selected item on backpack.tf?",
    "Проверьте цену и поля шаблона описания.": "Check the price and description template fields.",
    "Укажите целое неотрицательное число ключей.": "Enter a whole non-negative number of keys.",
    "Продажи": "Sales", "Личный chat_id": "Private chat_id", "Получить API Key": "Get API Key",
    "Получить токен": "Get token", "Проверить подключения": "Test connections",
    "Проверка подключений…": "Testing connections…", "Проверка офферов, сек.": "Offer check interval, seconds",
    "Автоматический бамп": "Automatic bump", "Автобамп": "Automatic bump", "Бамп объявлений": "Listing bumps",
    "Автоматически бампить объявления": "Automatically bump listings",
    "Автоматически поднимать объявления": "Automatically bump listings",
    "Интервал бампа, минут": "Bump interval, minutes", "Интервал, минут": "Interval, minutes",
    "Бампнуть сейчас": "Bump now", "Бамп сейчас": "Bump now", "Бампить сейчас": "Bump now",
    "Бамп объявлений…": "Bumping listings…", "Поднять объявления": "Bump listings",
    "Поднять сейчас": "Bump now", "Следующий бамп": "Next bump", "Последний бамп": "Last bump",
    "Настройте подключение backpack.tf.": "Configure the backpack.tf connection.",
    "Сначала загрузите объявления.": "Load your listings first.",
    "Нет активных объявлений для бампа.": "No active listings to bump.",
    "Объявления подняты.": "Listings bumped.", "Бамп выполнен.": "Bump completed.",
    "Выберите русский или английский язык.": "Choose Russian or English.",
    "Выберите светлую или тёмную тему.": "Choose the light or dark theme.",
    "Интервал бампа — целое число минут от 30 до 1440.": "The bump interval must be a whole number from 30 to 1440 minutes.",
    "Интервал бампа — от 30 до 1440 минут.": "The bump interval must be from 30 to 1440 minutes.",
    "Сохраните SteamID64 и backpack.tf User Token.": "Save your SteamID64 and backpack.tf User Token.",
    "Запрос бампа отправлен. Доступность бампа определяет backpack.tf.": "The bump request was submitted. backpack.tf determines bump eligibility.",
    "Объявление опубликовано заново.": "The listing was published again.",
    "Объявление перевыставлено с новыми условиями.": "The listing was relisted with new terms.",
    "backpack.tf: результат изменения требует сверки. Повторное изменение не отправлено.": "backpack.tf: the update needs reconciliation. A repeated update was not submitted.",
    "backpack.tf: новые условия объявления пока не подтверждены. Обновите список объявлений.": "backpack.tf: the new listing terms are not confirmed yet. Refresh your listings.",
    "backpack.tf: результат изменения требует сверки объявления.": "backpack.tf: the update needs listing reconciliation.",
    "Автоматический бамп включён.": "Automatic bump enabled.",
    "Автоматический бамп выключен.": "Automatic bump disabled.",
    "Не удалось выполнить действие": "Unable to complete the action",
    "Не удалось открыть программу.": "Unable to open the application.",
    "Не удалось прочитать локальные данные.": "Unable to read local data.",
    "Часть картинок Steam не загрузилась. «Обновить инвентарь» повторит загрузку.": "Some Steam images could not be loaded. Use Refresh inventory to retry.",
    "Состав предложения ещё не получен.": "The offer contents have not been received yet.",
    "Готово. Наблюдение остановлено. Подтверждения обменов выполняются вручную в Steam.": "Ready. Monitoring is stopped. Confirm trades manually in Steam.",
    "Наблюдение остановлено. Новое предложение не принято.": "Monitoring is stopped. The new offer was not accepted.",
    "Наблюдение остановлено. Уже отправленная операция продолжает сверяться при следующем запуске.": "Monitoring stopped. Submitted operations will continue to be reconciled on the next run.",
    "Ошибка обработки. Операции приостановлены; проверьте настройки и журнал.": "Processing error. Operations are paused; check the settings and activity log.",
    "Steam-сессия сохранена в защищённом хранилище.": "The Steam session was saved in protected storage.",
    "SteamID64 должен состоять из 17 цифр и начинаться с 7656119.": "SteamID64 must contain 17 digits and start with 7656119.",
    "Steam API Key: ожидаются 32 шестнадцатеричных символа.": "Steam API Key must contain 32 hexadecimal characters.",
    "Telegram user_id должен быть положительным числом.": "Telegram user_id must be a positive number.",
    "Укажите положительный chat_id личного чата Telegram.": "Enter a positive chat_id for your private Telegram chat.",
    "Интервал проверки — от 15 до 3600 секунд.": "The check interval must be between 15 and 3600 seconds.",
    "Интервал проверки — целое число от 15 до 3600 секунд.": "The check interval must be a whole number between 15 and 3600 seconds.",
    "Для другого Steam-аккаунта используйте отдельную папку данных.": "Use a separate data folder for another Steam account.",
    "В шаблоне разрешены поля {name}, {price}, {paint}.": "The template supports {name}, {price}, and {paint}.",
    "Шаблон описания слишком длинный (максимум 1200 символов).": "The description template is too long (1200 characters maximum).",
    "Описание слишком длинное (максимум 1600 символов).": "The description is too long (1600 characters maximum).",
    "Этот предмет уже выставлен на backpack.tf. Сначала снимите объявление.": "This item is already listed on backpack.tf. Remove the listing first.",
    "Предмет участвует в незавершённом обмене.": "This item is reserved by an unfinished trade.",
    "Точный предмет отсутствует в свежем обмениваемом инвентаре.": "The exact item is missing from the latest tradable inventory.",
    "Не удалось однозначно сверить объявление. Обновите список объявлений backpack.tf.": "Unable to reconcile the listing unambiguously. Refresh your backpack.tf listings.",
    "Не удалось однозначно сверить объявление. Удаление не отправлено.": "Unable to reconcile the listing unambiguously. Removal was not submitted.",
    "Объявление не найдено или предмет участвует в незавершённом обмене.": "The listing was not found, or its item is reserved by an unfinished trade.",
    "Сохраните SteamID64, Steam API Key и backpack.tf User Token.": "Save your SteamID64, Steam API Key, and backpack.tf User Token.",
    "Для уведомлений сохраните Telegram token и личный chat_id.": "Save your Telegram token and private chat_id for notifications.",
    "Для принятия предложения настройте Telegram.": "Configure Telegram before accepting offers.",
    "Не удалось расшифровать настройки. Откройте программу под прежней учётной записью Windows.": "Unable to decrypt settings. Open the application using the original Windows account.",
    "Не удалось сверить действующее объявление с backpack.tf. Обмен не принят.": "Unable to verify the active listing on backpack.tf. The trade was not accepted.",
    "Предмет уже зарезервирован другим обменом.": "The item is already reserved by another trade.",
    "Предложение уже обработано или не прошло проверку.": "The offer has already been processed or failed validation.",
    "Повторная проверка не пройдена. Обмен не принят.": "The second verification failed. The trade was not accepted.",
    "Состав обмена или условия объявления изменились. Обмен не принят.": "The trade contents or listing terms changed. The trade was not accepted.",
    "Предложение уже обрабатывается или завершено.": "The offer is already being processed or is complete.",
    "Отклонить можно только активное входящее предложение.": "Only an active incoming offer can be declined.",
    "Цена и состав совпадают": "The price and contents match",
    "Точные предметы и оплата совпадают": "The exact items and payment match",
    "Неизвестный предмет": "Unknown item", "Металлолом": "Scrap Metal", "металл": "metal",
    "Telegram: не настроен": "Telegram: not configured",
    "Telegram: уведомление сохранено и будет отправлено после восстановления связи.": "Telegram: the notification was saved and will be sent when the connection is restored.",
    "Проверка пройдена: вещи и оплата совпадают с действующим объявлением backpack.tf.": "Verified: the items and payment match the active backpack.tf listing.",
    "Программа приняла предложение. Подтвердите обмен вручную в Steam.": "The application accepted the offer. Confirm the trade manually in Steam.",
    "Обмен успешно завершён в Steam.": "The trade completed successfully in Steam.",
    "Steam сообщает об удержании обмена. Обмен ещё не завершён; программа дождётся итогового состояния.": "Steam reports a trade hold. The trade is not complete; the application will wait for the final status.",
    "Проверка с backpack.tf пройдена, но результат принятия пока не подтверждён Steam. Программа сверит состояние без повторного принятия.": "The backpack.tf check passed, but Steam has not confirmed acceptance yet. The application will reconcile the status without accepting again.",
    "Проверка с backpack.tf пройдена. Запрос принятия отправлен; ожидаем состояние Steam.": "The backpack.tf check passed. The acceptance request was submitted; waiting for Steam status.",
    "Демонстрационный режим. Сеть и реальные операции отключены.": "Demo mode. Network access and real operations are disabled.",
    "Демо: вход в Steam отключён.": "Demo: Steam sign-in is disabled.",
    "Демо: показаны примеры ваших объявлений.": "Demo: sample listings are displayed.",
    "Демонстрация: публикация отключена.": "Demo: publishing is disabled.",
    "Демонстрация: удаление отключено.": "Demo: removal is disabled.",
    "Демонстрация: реальные обмены отключены.": "Demo: real trades are disabled.",
    "Демонстрация: сетевые проверки отключены.": "Demo: network checks are disabled.",
    "Демонстрация: перевыставление отключено.": "Demo: relisting is disabled.",
    "Демонстрация: бамп отключён.": "Demo: bumping is disabled.",
    "Демо: бамп отключён.": "Demo: bumping is disabled.",
    "Сервис": "Service", "нужна авторизация": "authentication required",
    "доступ запрещён или сессия истекла": "access denied or session expired", "не найдено": "not found",
    "конфликт операции": "operation conflict", "слишком много запросов; повторите позднее": "too many requests; try again later",
    "ошибка сервера": "server error", "запрос отклонён": "request rejected",
    "аккаунт покупателя": "buyer account", "номер оффера": "offer number", "предмет": "item",
    "ответ сервера": "server response", "размер инвентаря": "inventory size", "статус оффера": "offer status",
    "закройте другой экземпляр бота с тем же токеном": "close any other bot instance using the same token",
    "проверьте токен, chat_id и запуск бота командой /start": "check the token, chat_id, and send /start to the bot",
    "Введите SteamID64 вашего аккаунта (17 цифр).": "Enter your account's SteamID64 (17 digits).",
    "Укажите Steam Web API Key в настройках.": "Enter the Steam Web API Key in Settings.",
    "Укажите Telegram Bot Token в настройках.": "Enter the Telegram Bot Token in Settings.",
    "Укажите backpack.tf User Token в настройках (не WebAPI Key).": "Enter the backpack.tf User Token in Settings (not a WebAPI Key).",
    "Укажите числовой Telegram chat_id.": "Enter a numeric Telegram chat_id.",
    "Укажите положительную цену в ключах и Refined Metal.": "Enter a positive price in keys and Refined Metal.",
    "Некорректный ID объявления.": "Invalid listing ID.", "Некорректное объявление backpack.tf.": "Invalid backpack.tf listing.",
    "Для входа установите зависимости программы (Playwright).": "Install the application dependencies (Playwright) to sign in.",
    "Окно Steam закрыто до завершения входа.": "The Steam window was closed before sign-in finished.",
    "Время ожидания входа Steam истекло (5 минут).": "Steam sign-in timed out (5 minutes).",
    "В Edge открыт другой аккаунт Steam. Войдите в указанный SteamID64.": "Edge is signed in to another Steam account. Sign in with the configured SteamID64.",
    "Не удалось открыть или сохранить вход Steam. Установите Microsoft Edge, закройте другое окно входа и повторите.": "Unable to open or save Steam sign-in. Install Microsoft Edge, close any other sign-in window, and retry.",
    "Steam: сначала выполните вход в аккаунт.": "Steam: sign in to your account first.",
    "Steam: сессия принадлежит другому аккаунту.": "Steam: the session belongs to another account.",
    "Steam: сессия содержит разные аккаунты. Выполните вход заново.": "Steam: the session contains different accounts. Sign in again.",
    "Steam: в сессии обнаружены разные аккаунты. Выполните вход заново.": "Steam: different accounts were found in the session. Sign in again.",
    "Steam: сохранённая сессия повреждена. Выполните вход заново.": "Steam: the saved session is damaged. Sign in again.",
    "Steam: сохранённая сессия недоступна. Выполните вход заново.": "Steam: the saved session is unavailable. Sign in again.",
    "Steam: сессия истекла или принадлежит другому аккаунту; войдите заново.": "Steam: the session expired or belongs to another account; sign in again.",
    "Steam: не удалось проверить сессию. Войдите в Steam заново.": "Steam: unable to verify the session. Sign in to Steam again.",
    "Steam: сессия и API доступны.": "Steam: the session and API are available.",
    "Steam API: ответ не содержит данных. Проверьте API Key.": "Steam API: the response contains no data. Check the API Key.",
    "Steam: инвентарь закрыт или временно недоступен; неполные данные не загружены.": "Steam: the inventory is private or temporarily unavailable; incomplete data was not loaded.",
    "Steam: некорректный ответ инвентаря.": "Steam: invalid inventory response.",
    "Steam: инвентарь изменился при загрузке. Обновите список ещё раз.": "Steam: the inventory changed while loading. Refresh the list again.",
    "Steam: страницы инвентаря пересекаются. Обновите список ещё раз.": "Steam: inventory pages overlap. Refresh the list again.",
    "Steam: получен неполный инвентарь. Обновите список позднее.": "Steam: an incomplete inventory was received. Refresh the list later.",
    "Steam: не удалось дочитать все страницы инвентаря.": "Steam: unable to read all inventory pages.",
    "Steam: превышен предел страниц инвентаря; неполные данные не используются.": "Steam: the inventory page limit was exceeded; incomplete data is not used.",
    "Steam: не удалось дочитать предложения обмена.": "Steam: unable to read all trade offers.",
    "Steam: повтор страницы предложений, загрузка остановлена.": "Steam: a trade-offer page was repeated; loading stopped.",
    "Steam: предложение не найдено.": "Steam: the offer was not found.",
    "Steam: принимать можно только активное входящее предложение.": "Steam: only active incoming offers can be accepted.",
    "Steam: принятие не подтверждено. Проверьте состояние оффера.": "Steam: acceptance was not confirmed. Check the offer status.",
    "Steam: отклонение не подтверждено. Проверьте состояние оффера.": "Steam: the decline was not confirmed. Check the offer status.",
    "backpack.tf: запрос отклонён. Проверьте токен, доступность предмета и лимит объявлений.": "backpack.tf: the request was rejected. Check your token, item availability, and listing limit.",
    "backpack.tf: некорректное объявление.": "backpack.tf: invalid listing.",
    "backpack.tf: ответ не содержит ID объявления.": "backpack.tf: the response contains no listing ID.",
    "backpack.tf: объявление не опубликовано активно. Обновите список объявлений.": "backpack.tf: the listing is not active. Refresh your listings.",
    "backpack.tf: ответ не содержит списка объявлений.": "backpack.tf: the response contains no listings.",
    "backpack.tf: не удалось подтвердить полноту списка объявлений.": "backpack.tf: unable to confirm that all listings were received.",
    "backpack.tf: некорректная страница объявлений.": "backpack.tf: invalid listings page.",
    "backpack.tf: не удалось дочитать полный список объявлений.": "backpack.tf: unable to read the complete listings list.",
    "backpack.tf: повтор страницы объявлений; загрузка остановлена.": "backpack.tf: a listings page was repeated; loading stopped.",
    "backpack.tf: превышен предел страниц объявлений.": "backpack.tf: the listings page limit was exceeded.",
    "backpack.tf: токен принадлежит другому Steam-аккаунту.": "backpack.tf: the token belongs to another Steam account.",
    "backpack.tf: токен доступен, объявления прочитаны.": "backpack.tf: the token is valid and listings were read.",
    "backpack.tf: получено другое объявление; проверка отменена.": "backpack.tf: a different listing was received; verification canceled.",
    "Telegram: некорректный список обновлений.": "Telegram: invalid update list.",
    "Telegram: токен бота доступен.": "Telegram: the bot token is valid.",
    "Ключи: введите целое неотрицательное число": "Keys: enter a whole non-negative number",
    "Металл: используйте точную цену, например 15 или 1.33 ref": "Metal: enter an exact price, for example 15 or 1.33 ref",
    "Металл: допустимы целые ref и дроби .11, .22, .33, .44, .55, .66, .77, .88": "Metal: use whole ref and fractions .11, .22, .33, .44, .55, .66, .77, .88",
    "Допустимые доли ref: .11, .22, .33, .44, .55, .66, .77, .88": "Allowed ref fractions: .11, .22, .33, .44, .55, .66, .77, .88",
    "Слишком большая цена": "The price is too large", "Цена должна быть больше нуля": "The price must be greater than zero",
    "Неверная цена": "Invalid price", "Неверное количество металла": "Invalid metal amount",
    "Steam: неверный ответ инвентаря": "Steam: invalid inventory response",
    "Steam: неверный список предметов": "Steam: invalid item list",
    "Неверная структура предложения или объявлений": "Invalid offer or listing structure",
    "Не загружены объявления": "No listings have been loaded", "Неверные или дублирующиеся объявления": "Invalid or duplicate listings",
    "Предложение не является активным входящим обменом": "The offer is not an active incoming trade",
    "Steam вернул неверное предложение": "Steam returned an invalid offer",
    "Steam не подтвердил аккаунт покупателя": "Steam did not confirm the buyer account",
    "Не указан точный ID предложения": "The exact offer ID is missing",
    "Нужны продаваемые предметы и оплата с обеих сторон": "The trade must contain sale items and payment on both sides",
    "Неверный предмет в предложении": "Invalid item in the offer",
    "В предложении есть предмет другой игры или инвентаря": "The offer contains an item from another game or inventory",
    "Пропущенный или повторяющийся экземпляр предмета": "Missing or duplicate item instance",
    "Пропавший предмет или неподдерживаемое количество": "Missing item or unsupported quantity",
    "Покупатель запрашивает предмет без активного объявления": "The buyer requests an item without an active listing",
    "В объявлении неверная или нулевая цена": "The listing price is invalid or zero",
    "Описание валюты не соответствует предмету": "The currency description does not match the item",
    "Описание валюты не соответствует экземпляру": "The currency description does not match the item instance",
    "Steam не предоставил достоверное описание валюты": "Steam did not provide a trusted currency description",
    "Оплата содержит необмениваемый предмет": "The payment contains an untradable item",
    "Оплата содержит нестандартную валюту или неполное описание": "The payment contains unsupported currency or an incomplete description",
    "Программа с этой папкой данных уже запущена.": "The application is already running with this data folder.",
    "Не удалось открыть защищённое хранилище Windows.": "Unable to open Windows protected storage.",
    "Хранилище секретов требует Windows (DPAPI).": "Protected storage requires Windows (DPAPI).",
    "Нет названия предмета для открытия backpack.tf.": "No item name is available to open backpack.tf.",
    "Нет данных предмета.": "No item data is available.",
    "Недостаточно точных свойств предмета. Сверьте объявление с backpack.tf; варианты с неизвестными свойствами не сравниваются.": "Some exact item properties are unavailable. Check the listing on backpack.tf.",
    "Недостаточно данных о качестве или типе предмета.": "Item quality or type data is incomplete.",
    "Steam не вернул определение предмета. Для точного сравнения нужна сверка объявления backpack.tf.": "Steam did not return the item definition. Check the full backpack.tf listing.",
    "Steam не вернул точный тип счётчика Strange. Для сравнения сверьте полное объявление backpack.tf.": "Steam did not return the exact Strange counter type. Check the full backpack.tf listing.",
    "Steam вернул неизвестный тип Strange Part. Для сравнения сверьте полное объявление backpack.tf.": "Steam returned an unknown Strange Part type. Check the full backpack.tf listing.",
    "Для Decorated Weapon нужны полные свойства из объявления backpack.tf.": "Decorated Weapons require the full properties from the backpack.tf listing.",
    "Для дополнительных свойств нужны полные данные объявления backpack.tf.": "Additional properties require the full backpack.tf listing data.",
    "Дополнительные свойства Steam требуют сверки с полным объявлением backpack.tf.": "Additional Steam properties must be checked against the full backpack.tf listing.",
    "В API появились неизвестные свойства варианта предмета.": "The API returned unknown item variant properties.",
    "Неизвестны ограничения обмена или ковки предмета.": "The item's trading or crafting restrictions are unknown.",
    "Неизвестен полный набор Strange Parts.": "The complete set of Strange Parts is unknown.",
    "Неизвестен Unusual Effect.": "The Unusual Effect is unknown.",
    "Неизвестен Killstreak Tier.": "The Killstreak Tier is unknown.",
    "Неизвестен эффект Killstreak.": "The Killstreak effect is unknown.",
    "Не хватает Sheen или Killstreaker для точного сравнения.": "The Sheen or Killstreaker property is missing.",
    "Для рецептов, вложенных предметов и decal точное сравнение недоступно.": "Full property matching is unavailable for recipes, contained items, and decals.",
    "Составные количества предметов не сравниваются.": "Stacked item quantities are unsupported.",
    "backpack.tf не вернул точные свойства предмета.": "backpack.tf did not return exact item properties.",
    "Steam вернул неоднозначное свойство предмета.": "Steam returned an ambiguous item property.",
    "Неизвестное свойство варианта backpack.tf.": "Unknown backpack.tf item variant property.",
    "Неполное свойство варианта backpack.tf.": "Incomplete backpack.tf item variant property.",
    "Неизвестный цвет краски TF2.": "Unknown TF2 paint color.",
    "Неизвестное свойство TF2.": "Unknown TF2 property.",
    "Неизвестный атрибут TF2.": "Unknown TF2 attribute.",
    "Не удалось определить Strange Part.": "Unable to identify the Strange Part.",
    "Неизвестен счётчик Strange.": "Unknown Strange counter.",
    "Неизвестны типы счётчиков Strange.": "Unknown Strange counter types.",
    "Неизвестны дополнительные атрибуты предмета.": "Unknown additional item attributes.",
    "Неполный дополнительный атрибут предмета.": "Incomplete additional item attribute.",
    "Это не предмет TF2.": "This is not a TF2 item.",
}


# Match whole messages so item names inside template fields are left alone.
_TEMPLATE_SPECS = [
    ("{0} из {1}", "{0} of {1}", ()),
    ("Не удалось выполнить действие ({0}).", "Unable to complete the action ({0}).", ()),
    ("Загружен инвентарь: {0} обмениваемых предметов.", "Inventory loaded: {0} tradable items.", ()),
    ("Объявление опубликовано: {0} · {1}.", "Listing published: {0} · {1}.", ()),
    ("Объявление снято: {0}.", "Listing removed: {0}.", ()),
    ("Объявление перевыставлено: {0} · {1}.", "Listing relisted: {0} · {1}.", ()),
    ("Объявление обновлено: {0} · {1}.", "Listing updated: {0} · {1}.", ()),
    ("Объявления загружены. Активных: {0}. Новых: {1}.", "Listings loaded. Active: {0}. New: {1}.", ()),
    ("Объявления загружены. Активных: {0}. Новых: {1}. С неподдерживаемой ценой: {2}.", "Listings loaded. Active: {0}. New: {1}. Unsupported prices: {2}.", ()),
    ("Предложение #{0}", "Trade offer #{0}", ()),
    ("Обмен #{0} успешно завершён в Steam.", "Trade #{0} completed successfully in Steam.", ()),
    ("Steam #{0}: отправлен отказ.", "Steam #{0}: decline submitted.", ()),
    ("Steam #{0}: результат операции требует сверки. Повтор приёма отключён.", "Steam #{0}: the operation needs reconciliation. Repeated acceptance is disabled.", ()),
    ("{0}: соединение и авторизация подтверждены", "{0}: connection and authentication confirmed", ()),
    ("{0}: HTTP {1}, {2}.", "{0}: HTTP {1}, {2}.", (2,)),
    ("{0}: получен некорректный ответ.", "{0}: invalid response received.", ()),
    ("{0}: неожиданный формат ответа.", "{0}: unexpected response format.", ()),
    ("{0}: соединение не удалось. Проверьте сеть и повторите проверку.", "{0}: connection failed. Check your network and retry.", ()),
    ("Некорректный {0}.", "Invalid {0}.", (0,)),
    ("Некорректный числовой {0}.", "Invalid numeric {0}.", (0,)),
    ("Telegram: запрос отклонён; {0}.", "Telegram: request rejected; {0}.", (0,)),
    ("Цена не совпадает: нужно {0}, предложено {1}", "Price mismatch: required {0}, offered {1}", ()),
    ("Сверенная цена: {0}", "Verified price: {0}", ()),
    ("Текущая цена: {0}", "Current price: {0}", ()),
    ("• Металлолом × {0}", "• Scrap Metal × {0}", ()),
    ("Бамп выполнен. Объявлений: {0}.", "Bump completed. Listings: {0}.", ()),
    ("Объявления подняты: {0}.", "Listings bumped: {0}.", ()),
    ("Бамп объявлений выполнен: {0}.", "Listings bumped: {0}.", ()),
    ("backpack.tf: повторите бамп через {0} сек.", "backpack.tf: retry the bump in {0} seconds.", ()),
    ("backpack.tf: следующий бамп доступен через {0} сек.", "backpack.tf: the next bump is available in {0} seconds.", ()),
    ("Бамп недоступен. Повторите через {0} сек.", "Bumping is unavailable. Retry in {0} seconds.", ()),
]


def _compile_template(source):
    names = re.findall(r"\{([0-9]+)\}", source)
    parts, last = [], 0
    used = set()
    for found in re.finditer(r"\{([0-9]+)\}", source):
        parts.append(re.escape(source[last:found.start()]))
        number = found.group(1)
        parts.append(r"(?P<v" + number + r">[^\r\n]*?)" if number not in used else r"(?P=v" + number + ")")
        used.add(number)
        last = found.end()
    parts.append(re.escape(source[last:]))
    return re.compile("^" + "".join(parts) + "$"), names


_TEMPLATES = [(pattern, destination, localize, names)
              for source, destination, localize in sorted(_TEMPLATE_SPECS,
                  key=lambda spec: len(re.sub(r"\{[0-9]+\}", "", spec[0])), reverse=True)
              for pattern, names in [_compile_template(source)]]


_PREFIXES = {
    "Всего предметов: ": "Total items: ",
    "Обмен не принят. ": "Trade not accepted. ",
    "Публикация объявления: ": "Publishing listing: ",
    "Снятие объявления: ": "Removing listing: ",
    "Перевыставление объявления: ": "Relisting item: ",
    "Загрузка объявлений: ": "Loading listings: ",
    "Загрузка инвентаря: ": "Loading inventory: ",
    "Проверка подключений: ": "Testing connections: ",
    "Сохранение настроек: ": "Saving settings: ",
    "Вход в Steam: ": "Steam sign-in: ",
    "Бамп объявлений: ": "Bumping listings: ",
    "Автоматический бамп: ": "Automatic bump: ",
}


def _english(text, depth=0):
    if depth > 5 or not text:
        return text
    if text in CATALOG:
        return CATALOG[text]
    # An item name can look like a translated phrase; keep captured text unchanged.
    for pattern, destination, localize, names in _TEMPLATES:
        matched = pattern.fullmatch(text)
        if matched:
            values = {int(number): matched.group("v" + number) for number in names}
            for number in localize:
                values[number] = _english(values[number], depth + 1)
            return destination.format(*(values.get(number, "") for number in range(max(values, default=-1) + 1)))
    for source, destination in _PREFIXES.items():
        if text.startswith(source):
            return destination + _english(text[len(source):], depth + 1)
    if "\n" in text or "\r" in text:
        return "".join(_english(line.rstrip("\r\n"), depth + 1) + line[len(line.rstrip("\r\n")):]
                       for line in text.splitlines(keepends=True))
    stripped = text.strip()
    if stripped != text and stripped:
        start = len(text) - len(text.lstrip())
        end = len(text.rstrip())
        return text[:start] + _english(stripped, depth + 1) + text[end:]
    if text.endswith(":") and text[:-1] in CATALOG:
        return CATALOG[text[:-1]] + ":"
    return text


def translate(text, language=None):
    """Translate known app messages and leave other text unchanged."""
    language = get_language() if language is None else language
    if not isinstance(language, str) or language not in LANGUAGES:
        raise ValueError("Unsupported language")
    text = "" if text is None else str(text)
    return _english(text) if language == "en" else text


t = translate
