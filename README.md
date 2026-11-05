# Backpack Seller

A small Windows app for selling Team Fortress 2 items on backpack.tf. Manage your listings, check incoming Steam offers, and get trade updates in Telegram.

[Download for Windows](https://github.com/gorniy11/Backpack-Seller/releases/latest)

## Getting started

1. Download and extract the Windows release. Keep `_internal` beside `BackpackSeller.exe`.
2. Run `BackpackSeller.exe`. Choose **English** at the top right if needed.
3. Click **Sign in to Steam**. Microsoft Edge is required for the login window. Your tradable inventory loads after signing in; use **Refresh inventory** for later updates.
4. In **Settings**, save your SteamID64 and [backpack.tf User Token](https://next.backpack.tf/developer/).
5. Select an item, enter a price in Mann Co. Keys and Refined Metal, add a description, and click **List item**.

For an existing listing, **Relist** updates its price and description. **Remove** takes it down. **Listings → Load my listings** brings in active sales from your account.

Use **Open website** to check the item's listings on backpack.tf yourself. Some item properties do not have a supported website filter, so check the page before comparing items.

To try the interface without signing in or making network requests, run `DEMO.cmd` from the release.

## Trade offers

Add a [Steam Web API Key](https://steamcommunity.com/dev/apikey), Telegram Bot Token, and your private chat ID in **Settings**. Send `/start` to your Telegram bot, then click **Start** in the app.

**Starting offer monitoring allows the app to accept matching offers.** Before accepting, it checks the exact items and the current prices of your own listings. Keys and metal are checked separately: an offer for a listing priced at 1 key and 15 refined must contain that payment.

Telegram receives the offer contents and result. If Steam asks for confirmation, complete it in Steam; some incoming trades finish without that step. Offers that fail validation are left untouched, with the reason sent to Telegram. A trade on hold is not reported as completed.

Monitoring starts off each time you open the app. Keep the app open while using it. There is no SDA integration or automatic Steam confirmation.

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
.\.venv\Scripts\python.exe app.py --demo
```

Tests use local fixtures and mocked services; they do not submit listings or trades:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Build a Windows release:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe build_windows.py
.\.venv\Scripts\python.exe package_release.py
```

Builds and release archives are written to `dist/`.

## Credits

Team Fortress 2 and the demo item images belong to Valve. Demo listings are fictional. This project is not affiliated with Valve or backpack.tf.
