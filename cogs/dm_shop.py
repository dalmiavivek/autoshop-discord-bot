import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import uuid
import logging
from typing import Dict, Any, List, Optional

from providers.base import StoreProvider
from database import OrderDatabase
from providers.crypto_tracker import (
    get_crypto_price,
    calculate_invoice_crypto_amount,
    get_qr_code_url,
    check_incoming_blockchain_tx
)
from cogs.tickets import create_order_ticket

logger = logging.getLogger(__name__)

class InvoiceRefreshView(discord.ui.View):
    """View shown in DM with 'Refresh Status' button."""

    def __init__(self, bot: commands.Bot, invoice_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.invoice_id = invoice_id
        self.add_item(discord.ui.Button(
            label="🔄 Refresh Status",
            style=discord.ButtonStyle.primary,
            custom_id=f"btn_refresh:{invoice_id}"
        ))



class DMCryptoTokenSelect(discord.ui.View):
    """View to select crypto payment currency (LTC, USDT, BTC, SOL)."""

    def __init__(self, bot: commands.Bot, product: Dict[str, Any], guild_id: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.product = product
        self.guild_id = guild_id

    async def _handle_token_choice(self, interaction: discord.Interaction, token: str):
        await interaction.response.defer()
        db: OrderDatabase = self.bot.db

        # 1. Resolve Admin Address for selected token
        crypto_entry = db.get_crypto_address(token)
        deposit_address = ""
        if crypto_entry and crypto_entry.get("address"):
            deposit_address = crypto_entry["address"]
        else:
            # Fallback to environment variables
            env_key = f"PAYOUT_{token.upper()}_ADDRESS"
            deposit_address = os.getenv(env_key, "").strip()

        if not deposit_address:
            await interaction.followup.send(
                f"⚠️ The store admin has not configured a receiving address for **{token}** yet.\n"
                f"Please choose another payment method or ask an admin to run `/setcrypto`.",
                ephemeral=True
            )
            return

        # 2. Calculate live crypto price and exact amount with micro-offset
        fiat_amount = float(self.product.get("price", 0.0))
        fiat_currency = self.product.get("currency", "USD")

        crypto_price = await get_crypto_price(token, fiat=fiat_currency)
        seed = int(interaction.user.id % 1000)
        expected_crypto = calculate_invoice_crypto_amount(fiat_amount, crypto_price, seed, token)

        # 3. Create Invoice in Database
        invoice_id = f"INV-{uuid.uuid4().hex[:8].upper()}"
        db.create_crypto_invoice(
            invoice_id=invoice_id,
            discord_user_id=interaction.user.id,
            guild_id=self.guild_id,
            product_id=self.product["id"],
            product_name=self.product["name"],
            token=token,
            expected_crypto_amount=expected_crypto,
            fiat_amount=fiat_amount,
            fiat_currency=fiat_currency,
            deposit_address=deposit_address
        )

        qr_url = get_qr_code_url(token, deposit_address, expected_crypto)

        # 4. Render Invoice Embed
        embed = discord.Embed(
            title=f"🧾 Crypto Invoice: {self.product['name']}",
            description=(
                f"Please send the exact amount of **{token}** to the address below.\n"
                f"Payment status is monitored **24/7 in real time**."
            ),
            color=discord.Color.gold()
        )
        embed.add_field(name="💰 Exact Amount to Send", value=f"```{expected_crypto} {token}``` *(~{fiat_currency} {fiat_amount:.2f})*", inline=False)
        embed.add_field(name=f"📥 Receiving {token} Address (Tap to Copy)", value=f"```{deposit_address}```", inline=False)
        embed.add_field(name="⏳ Status", value="`Waiting for blockchain payment...`", inline=True)
        embed.add_field(name="🆔 Invoice ID", value=f"`{invoice_id}`", inline=True)
        embed.set_image(url=qr_url)
        embed.set_footer(text="After sending, click 'Refresh Status' below or wait for auto-detection.")

        view = InvoiceRefreshView(self.bot, invoice_id)
        await interaction.followup.send(embed=embed, view=view)

    @discord.ui.button(label="Litecoin (LTC)", style=discord.ButtonStyle.success, emoji="🪙")
    async def btn_ltc(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_token_choice(interaction, "LTC")

    @discord.ui.button(label="USDT (TRC-20)", style=discord.ButtonStyle.primary, emoji="💵")
    async def btn_usdt(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_token_choice(interaction, "USDT")

    @discord.ui.button(label="Bitcoin (BTC)", style=discord.ButtonStyle.secondary, emoji="₿")
    async def btn_btc(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_token_choice(interaction, "BTC")

    @discord.ui.button(label="Solana (SOL)", style=discord.ButtonStyle.secondary, emoji="🟣")
    async def btn_sol(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_token_choice(interaction, "SOL")



class DMProductDropdown(discord.ui.Select):
    def __init__(self, bot: commands.Bot, products: List[Dict[str, Any]], guild_id: int):
        self.bot = bot
        self.products_map = {p["id"]: p for p in products}
        self.guild_id = guild_id

        options = []
        for p in products[:25]:
            options.append(discord.SelectOption(
                label=p["name"][:100],
                value=p["id"],
                description=f"{p['currency']} {p['price']:.2f}"[:100],
                emoji="🛍️"
            ))

        super().__init__(
            placeholder="Select product to buy in DM...",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        prod = self.products_map.get(self.values[0])
        if not prod:
            await interaction.response.send_message("❌ Product not found.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"💳 Select Crypto Payment Token for {prod['name']}",
            description=f"Price: **{prod['currency']} {prod['price']:.2f}**\n\nChoose the cryptocurrency you would like to pay with:",
            color=discord.Color.blurple()
        )
        view = DMCryptoTokenSelect(self.bot, prod, self.guild_id)
        await interaction.response.send_message(embed=embed, view=view)


class DMShopCog(commands.Cog, name="DM Shop & Crypto"):
    """Handles buying directly via DMs, crypto invoices, and automated ticket generation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.refresh_invoices_task.start()

    def cog_unload(self):
        self.refresh_invoices_task.cancel()

    @app_commands.command(name="buydm", description="Buy products directly in your private DMs with crypto.")
    async def buy_dm(self, interaction: discord.Interaction):
        provider: StoreProvider = self.bot.provider
        products = await provider.get_products()

        if not products:
            await interaction.response.send_message("❌ No active products available in the shop.", ephemeral=True)
            return

        guild_id = interaction.guild_id or int(os.getenv("GUILD_ID", "0") or 0)

        # Send in DM
        try:
            embed = discord.Embed(
                title="🛍️ Private DM Checkout",
                description="Select a product below to generate your unique crypto payment invoice.",
                color=discord.Color.purple()
            )
            view = discord.ui.View()
            view.add_item(DMProductDropdown(self.bot, products, guild_id))

            await interaction.user.send(embed=embed, view=view)
            if interaction.guild:
                await interaction.response.send_message("📩 I've sent you a direct message to continue checkout!", ephemeral=True)
            else:
                await interaction.response.send_message("Please select an item above.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Could not DM you. Please enable 'Allow direct messages from server members' in your privacy settings.", ephemeral=True)

    @tasks.loop(seconds=25)
    async def refresh_invoices_task(self):
        """24/7 background task that automatically monitors and refreshes blockchain payments."""
        db: OrderDatabase = self.bot.db
        pending_invoices = db.get_pending_crypto_invoices()

        for inv in pending_invoices:
            try:
                tx_info = await check_incoming_blockchain_tx(
                    token=inv["token"],
                    address=inv["deposit_address"],
                    expected_amount=inv["expected_crypto_amount"]
                )

                if tx_info and tx_info.get("found"):
                    txid = tx_info.get("txid", "")
                    if txid and db.is_txid_used(txid):
                        logger.warning(f"Skipping txid {txid} because it was already processed for another invoice.")
                        continue

                    logger.info(f"Payment detected on blockchain for invoice {inv['invoice_id']}!")
                    db.update_invoice_status(inv["invoice_id"], "PAID", txid=txid)
                    await self.fulfill_paid_invoice(inv, tx_info)

            except Exception as e:
                logger.error(f"Error checking pending invoice {inv['invoice_id']}: {e}")

    @refresh_invoices_task.before_loop
    async def before_refresh(self):
        await self.bot.wait_until_ready()

    async def manual_refresh_invoice(self, interaction: discord.Interaction, invoice_id: str):
        """Allows buyer to manually refresh payment status on demand in DM."""
        await interaction.response.defer(ephemeral=True)
        db: OrderDatabase = self.bot.db
        inv = db.get_crypto_invoice(invoice_id)

        if not inv:
            await interaction.followup.send("❌ Invoice not found.", ephemeral=True)
            return

        if inv["status"] == "PAID":
            channel_link = f"<#{inv['ticket_channel_id']}>" if inv.get("ticket_channel_id") else "your server"
            await interaction.followup.send(f"✅ **Payment already confirmed!** Your order ticket is active in {channel_link}.", ephemeral=True)
            return

        tx_info = await check_incoming_blockchain_tx(
            token=inv["token"],
            address=inv["deposit_address"],
            expected_amount=inv["expected_crypto_amount"]
        )

        if tx_info and tx_info.get("found"):
            txid = tx_info.get("txid", "")
            if txid and db.is_txid_used(txid):
                await interaction.followup.send("⚠️ This transaction was already processed for another invoice.", ephemeral=True)
                return

            db.update_invoice_status(inv["invoice_id"], "PAID", txid=txid)
            await interaction.followup.send(f"🎉 **Payment Detected on Blockchain!** TXID: `{txid[:16]}...` Creating your order ticket...", ephemeral=True)
            await self.fulfill_paid_invoice(inv, tx_info)
        else:
            await interaction.followup.send(
                f"⏳ **Still waiting for blockchain payment...**\n"
                f"Amount: `{inv['expected_crypto_amount']} {inv['token']}`\n"
                f"Address: `{inv['deposit_address']}`\n\n"
                f"*Transactions usually take 1-3 minutes to confirm on the network.*",
                ephemeral=True
            )

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Global interaction listener to handle DM Buy and Refresh buttons across bot restarts."""
        if interaction.type == discord.InteractionType.component:
            custom_id = interaction.data.get("custom_id", "")
            if custom_id == "btn_trigger_buydm":
                if not interaction.response.is_done():
                    await self.buy_dm(interaction)
            elif custom_id.startswith("btn_refresh:"):
                invoice_id = custom_id.split(":", 1)[1]
                if not interaction.response.is_done():
                    await self.manual_refresh_invoice(interaction, invoice_id)

    async def fulfill_paid_invoice(self, invoice: Dict[str, Any], tx_info: Dict[str, Any]):
        """Creates the ticket in the server, sends confirmation DM to the buyer, and logs payout."""
        db: OrderDatabase = self.bot.db
        guild_id = invoice.get("guild_id") or int(os.getenv("GUILD_ID", "0") or 0)
        guild = self.bot.get_guild(guild_id)

        buyer = self.bot.get_user(invoice["discord_user_id"])
        if not buyer:
            try:
                buyer = await self.bot.fetch_user(invoice["discord_user_id"])
            except Exception:
                buyer = None

        # Fetch product delivery instructions from store
        provider: StoreProvider = self.bot.provider
        product = await provider.get_product(invoice["product_id"])
        delivery_text = ""
        if product:
            delivery_text = product.get("description", "")

        # Attach forward payout address from admin configuration
        inv_data = dict(invoice)
        inv_data["txid"] = tx_info.get("txid", "")
        inv_data["explorer_url"] = tx_info.get("explorer_url", "")
        crypto_entry = db.get_crypto_address(invoice["token"])
        if crypto_entry and crypto_entry.get("payout_forward_address"):
            inv_data["forward_payout_address"] = crypto_entry["payout_forward_address"]

        # 1. Create Server Ticket Channel
        ticket_channel = None
        if guild and buyer:
            ticket_channel = await create_order_ticket(guild, buyer, inv_data, delivery_text)
            if ticket_channel:
                db.update_invoice_status(invoice["invoice_id"], "PAID", ticket_channel_id=ticket_channel.id)

        # 2. Assign Customer Role in Guild
        customer_role_id = os.getenv("CUSTOMER_ROLE_ID", "").strip()
        if guild and buyer and customer_role_id.isdigit():
            member = guild.get_member(buyer.id)
            if member:
                role = guild.get_role(int(customer_role_id))
                if role:
                    try:
                        await member.add_roles(role, reason=f"Crypto Payment Invoice {invoice['invoice_id']}")
                    except Exception as e:
                        logger.error(f"Could not assign customer role to {buyer.id}: {e}")

        # 3. Notify Buyer in DM
        if buyer:
            try:
                channel_str = ticket_channel.mention if ticket_channel else "your Discord server"
                dm_embed = discord.Embed(
                    title="🎉 Payment Confirmed!",
                    description=(
                        f"Your payment of **{invoice['expected_crypto_amount']} {invoice['token']}** for **{invoice['product_name']}** has been verified!\n\n"
                        f"🎫 **Order Ticket Created:** {channel_str}\n"
                        f"🔗 **TXID:** [{tx_info.get('txid', '')[:16]}...]({tx_info.get('explorer_url', '')})\n\n"
                        f"Please head over to {channel_str} to complete delivery."
                    ),
                    color=discord.Color.green()
                )
                await buyer.send(embed=dm_embed)
            except Exception as e:
                logger.error(f"Failed to send DM confirmation: {e}")

        # 4. Optional: Post to Admin/Staff Payout Audit Log Channel
        payout_log_channel_id = os.getenv("PAYOUT_LOG_CHANNEL_ID", "").strip()
        if guild and payout_log_channel_id.isdigit():
            log_chan = guild.get_channel(int(payout_log_channel_id))
            if log_chan:
                forward_dest = inv_data.get("forward_payout_address") or "None (kept at deposit address)"
                log_embed = discord.Embed(
                    title="💰 Crypto Payment Verified & Order Ticket Created",
                    description=(
                        f"**Buyer:** {buyer.mention if buyer else invoice['discord_user_id']} (`{invoice['discord_user_id']}`)\n"
                        f"**Product:** {invoice['product_name']}\n"
                        f"**Amount Paid:** `{invoice['expected_crypto_amount']} {invoice['token']}` (~{invoice['fiat_currency']} {invoice['fiat_amount']:.2f})\n"
                        f"**Ticket:** {ticket_channel.mention if ticket_channel else 'N/A'}\n"
                        f"**TXID:** [{tx_info.get('txid', '')[:20]}...]({tx_info.get('explorer_url', '')})\n"
                        f"**Deposit Address:** `{invoice['deposit_address']}`\n"
                        f"**Forward Payout Destination:** `{forward_dest}`"
                    ),
                    color=discord.Color.gold()
                )
                try:
                    await log_chan.send(embed=log_embed)
                except Exception as e:
                    logger.error(f"Failed to send log to payout channel: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(DMShopCog(bot))

