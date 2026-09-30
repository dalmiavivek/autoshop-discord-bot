# 🛒 Auto Buy & Live Stock Sync Discord Bot (Shoppex / SellAuth)

A high-performance Discord Auto Shop Bot built with Python (`discord.py`) that bridges your Discord community directly with your **[Shoppex.io](https://shoppex.io)** or **[SellAuth](https://sellauth.com)** store.

---

## ⚡ Key Capabilities

1. **Two-Way Stock Sync (Discord ➔ Store)**:
   - Run `/addstock` directly inside Discord (via popup modal, pasted text, or uploading a `.txt` file).
   - The bot communicates with your store's API in real-time, automatically appending keys/serials and removing duplicates.
   - Instantly announces restocks in your designated `#restock-alerts` channel.
2. **Interactive Customer Shopping**:
   - `/stock`: Clean live inventory table displaying available stock counts, prices, and status.
   - `/shop`: Interactive Discord UI with select dropdown menus and clickable **"Buy Now"** checkout buttons.
   - `/buy [product_id]`: Instant direct checkout link generator.
3. **Automated Order Verification & Role Assignment**:
   - `/verify [order_id]`: Checks the purchase status via your store's API.
   - Confirms payment and automatically grants the customer a **Customer Role** on your Discord server.
   - Prevents duplicate claims using a local SQLite database (`orders.db`).

---

## 📋 Prerequisites

- **Python 3.10+** (Tested on Python 3.14)
- A Discord Bot Token from the [Discord Developer Portal](https://discord.com/developers/applications)
- An API Key from **Shoppex** or **SellAuth**

---

## 🚀 Quick Setup & Installation

### Step 1: Open Terminal & Navigate to Project
```bash
cd /Users/vivekdalmia/.gemini/antigravity/scratch/autoshop-discord-bot
```

### Step 2: Create a Virtual Environment & Install Dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 3: Configure Environment Variables
Create your `.env` configuration file from `.env.example`:
```bash
cp .env.example .env
```
Open `.env` in your text editor and configure your credentials:

```env
# 1. Discord Bot Token
DISCORD_TOKEN=your_bot_token_here

# 2. Permissions
# Discord User IDs who can use /addstock (comma-separated)
ADMIN_USER_IDS=123456789012345678
# Role ID for bot admins (optional)
ADMIN_ROLE_ID=
# Role ID granted to verified buyers
CUSTOMER_ROLE_ID=
# Channel where restock announcements are posted
RESTOCK_CHANNEL_ID=

# 3. Store Platform ('shoppex' or 'sellauth')
STORE_PLATFORM=shoppex

# 4. If using Shoppex:
SHOPPEX_API_KEY=your_shoppex_api_key
SHOPPEX_STORE_DOMAIN=yourstore.shoppex.io

# 5. If using SellAuth:
SELLAUTH_API_KEY=your_sellauth_api_key
SELLAUTH_SHOP_ID=your_shop_id
```

---

## 🔑 Obtaining Store API Keys

### For Shoppex:
1. Log in to your [Shoppex Dashboard](https://shoppex.io).
2. Go to **Settings** → **Developer API**.
3. Create a new API Key with the following permissions:
   - `products.read`
   - `products.write` (required for `/addstock`)
   - `orders.read` (required for `/verify`)
4. Copy the API key and paste it as `SHOPPEX_API_KEY` in `.env`.
5. Enter your store domain (e.g. `store.shoppex.io`) as `SHOPPEX_STORE_DOMAIN`.

### For SellAuth:
1. Log in to your [SellAuth Dashboard](https://sellauth.com).
2. Go to **Account** → **Developers**.
3. Copy your **Shop API Key** and **Shop ID**.
4. Set `STORE_PLATFORM=sellauth`, `SELLAUTH_API_KEY`, and `SELLAUTH_SHOP_ID` in `.env`.

---

## 🤖 Setting Up the Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**.
2. Go to the **Bot** tab:
   - Click **Reset Token** and copy your token into `DISCORD_TOKEN` in `.env`.
   - Scroll down to **Privileged Gateway Intents** and enable:
     - **Server Members Intent** (required to assign Customer roles)
     - **Message Content Intent**
3. Go to **OAuth2** → **URL Generator**:
   - Scopes: Select `bot` and `applications.commands`.
   - Bot Permissions: Select `Administrator` (or `Manage Roles`, `Send Messages`, `Embed Links`, `Attach Files`, `Use Slash Commands`).
   - Copy the generated URL and open it in your browser to invite the bot to your server.
4. **Discord Role Hierarchy**:
   - In your Discord Server Settings → **Roles**, make sure the **Bot's role is placed HIGHER than the Customer Role** so it has permission to assign it to members.

---

## 📦 How to Use the Bot

### Adding Stock from Discord to Your Store
Admins can run `/addstock`:
- **Interactive Modal**: Type `/addstock product_id:YOUR_PRODUCT_ID` and press Enter. A popup modal will appear where you can paste hundreds of serials/accounts (one per line).
- **File Upload**: Type `/addstock product_id:YOUR_PRODUCT_ID` and attach a `.txt` file containing your keys/accounts.
- **Direct Paste**: Type `/addstock product_id:YOUR_PRODUCT_ID serials:KEY-1, KEY-2, KEY-3`.

*The bot will immediately upload them to your Shoppex/SellAuth store via API and update inventory counts.*

### Checking Stock
- `/stock`: Shows an embed of all products with stock indicators (`🟢 12 in stock` or `🔴 Out of stock`).

### Customer Shop & Checkout
- `/shop`: Interactive menu with dropdown selection and dynamic "Buy Now" checkout buttons.
- `/buy [product_id]`: Direct checkout link for a specific product.

### Order Verification & Roles
- `/verify [order_id]`: Customers type their Order ID / Invoice ID received after purchase. The bot verifies the order was paid and instantly gives them the **Customer Role**.

---

## 🏃 Running the Bot

Run the bot with:
```bash
python3 bot.py
```

To run it continuously in the background on your server/Mac:
```bash
# Using PM2 (recommended)
pm2 start bot.py --name "autoshop-bot" --interpreter python3

# Or using nohup
nohup python3 bot.py > bot.log 2>&1 &
```
