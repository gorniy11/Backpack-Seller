# Backpack Seller

A small Windows app for selling Team Fortress 2 items on backpack.tf. Manage your listings, check incoming Steam offers, and get trade updates in Telegram.

[Download for Windows](https://github.com/gorniy11/Backpack-Seller/releases/latest)

## MVP

Version 1.1 covers a single-account selling workflow: pick an item, list it at your price, check the incoming offer, and follow the trade in Telegram. All trades are handled manually in Steam.

- Shows your tradable TF2 inventory with item images and filters.
- Creates, edits, removes, and imports your backpack.tf sale listings.
- Opens backpack.tf with the selected item's known filters.
- Bumps eligible listings manually or on a schedule.
- Checks incoming offers against your listings and reports the result in Telegram.
- Sends offer contents and validation results to Telegram.

The app has English and Russian interfaces, plus light and dark themes. It does not compare market prices or track competing listings. You set the price yourself.

**Try it offline:** extract the Windows release and run `DEMO.cmd`. It opens a sample inventory with fictional listings, so you can try filters, item cards, languages, and themes without signing in. Publishing and trades require your own account.

## Getting started

The [wiki](https://github.com/gorniy11/Backpack-Seller/wiki) covers setup, listing descriptions, slow responses, and trade handling. A copy is kept in [wiki/Home.md](wiki/Home.md).

1. Download and extract the Windows release. Keep `_internal` beside `BackpackSeller.exe`.
2. Run `BackpackSeller.exe`. Choose **English** at the top right if needed.
3. Click **Sign in to Steam**. Microsoft Edge is required for the login window. Your tradable inventory loads after signing in; use **Refresh inventory** for later updates.
4. In **Settings**, save your SteamID64 and [backpack.tf User Token](https://next.backpack.tf/developer/).
5. Select an item, enter a price in Mann Co. Keys and Refined Metal, add a description, and click **List item**.

For an existing listing, **Relist** updates its price and description. **Remove** takes it down. **Listings → Load my listings** brings in active sales from your account.

Edit the automatic description under **Settings → Sales → Description template**, then save. Use `{name}`, `{price}`, and `{paint}` as placeholders. **Generate description** applies the saved template to the selected item.

Use **Open website** to check the item's listings on backpack.tf yourself. Some item properties do not have a supported website filter, so check the page before comparing items.

To try the interface without signing in or making network requests, run `DEMO.cmd` from the release.

## Trade offers

Add a [Steam Web API Key](https://steamcommunity.com/dev/apikey), Telegram Bot Token, and your private chat ID in **Settings**. Send `/start` to your Telegram bot, then click **Start** in the app.

Monitoring only checks incoming offers. Telegram shows whether the items and payment match your listings, the item quantities, and a link to Steam. Accept or decline the trade yourself in Steam. The app never submits trade decisions. Keep it open to receive notifications.

## Automatic bumps

Enable **Automatic bump** in **Settings** and choose an interval from 30 to 1,440 minutes. There is also a **Bump now** button under **Listings**.

backpack.tf decides which listings can be bumped. The app respects rate limits and keeps the cooldown after a restart. The site's bump API also marks your account as program-managed for 30 minutes; the app requests removal of that status when you disable automatic bumps or close it.

## Data and updates

Settings, inventory, and trade history are stored in `data` beside the executable. Credentials and Steam cookies use Windows DPAPI encryption, tied to your Windows user. Do not share this folder.

To update, close the old version, keep a backup, and copy its `data` folder beside the new executable. Language changes are in the top-right corner; themes are under **Settings → Appearance**.

## Run from source

Requires Windows, Python 3.11 or newer with Tkinter, and Microsoft Edge.

Run `install.cmd`, then `START.cmd`. For a local demo:

```powershell
.\.venv\Scripts\python.exe src/app.py --demo
```

Tests use local fixtures and mocked services; they do not submit listings or trades:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s src -v
```

Build a Windows release:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe src/build_windows.py
.\.venv\Scripts\python.exe src/package_release.py
```

Builds and release archives are written to `dist/`.

## Credits

Team Fortress 2 and the demo item images belong to Valve. Demo listings are fictional. This project is not affiliated with Valve or backpack.tf.
