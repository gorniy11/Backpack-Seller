# Backpack Seller

A Windows desktop app for TF2 sale listings on backpack.tf.

## Setup

Download the latest Windows ZIP from [Releases](https://github.com/gorniy11/Backpack-Seller/releases), extract it, and run BackpackSeller.exe. Keep the _internal folder beside the executable. Use DEMO.cmd for an offline preview.

Sign in to Steam from the app. Microsoft Edge is required for the login window. Add your SteamID64 and backpack.tf User Token in Settings. Inventory refresh is manual after the initial login.

## Listings

Select an item, enter a price in keys and refined metal, and click List item. Relist updates the price and description. Remove takes the listing down. Load my listings imports your own active listings. Open website opens the selected item's known filters.

## Description template

Settings → Sales → Description template controls Generate description. Supported placeholders are `{name}`, `{price}`, and `{paint}`. Save settings before generating a description. Existing listing descriptions are edited in the item's description field and submitted with Relist.

Example: `Selling {name} for {price}. {paint} Send a trade offer.`

## Slow responses

Version 1.1 allows up to 90 seconds for a listing write and 60 seconds for a read, with a separate connection timeout. Temporary read failures can be retried once. Writes are never automatically replayed. If a response is lost, the app checks your own listings to recover the result. If the site is still unavailable, the listing remains awaiting reconciliation; refresh your listings before trying again. A timeout is not proof that the site rejected the listing.

## Trade offers and Telegram

Configure Steam API Key, Telegram Bot Token, and your personal chat ID. Send /start to your bot, then click Start. Monitoring checks the exact items and your listing price. Telegram receives the result and item quantities. All trades are manual; accept or decline them in Steam. Keep the app open while monitoring.

## Bumps and local data

Automatic bumps are optional, with a 30–1440 minute interval. backpack.tf determines eligibility and rate limits. Its bump endpoint marks the account as program-managed for 30 minutes. Settings and session data are stored in the data folder and encrypted using Windows DPAPI where applicable. Do not share that folder.

## Source

All Python files, including build scripts and tests, live in src. Install with install.cmd, then run START.cmd. Run tests with `python -m unittest discover -s src`. Build with `python src/build_windows.py` and package with `python src/package_release.py`.
