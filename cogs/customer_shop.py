import discord
from discord import app_commands
from discord.ext import commands
import os
import logging
from typing import Optional, List, Dict, Any
from providers.base import StoreProvider
from database import OrderDatabase

logger = logging.getLogger(__name__)

class ProductSelect(discord.ui.Select):
    """Dropdown menu for selecting a product from the store catalog."""

    def __init__(self, products: List[Dict[str, Any]], provider: StoreProvider):
        self.products_map = {p["id"]: p for p in products}
        self.provider = provider

        options = []
        for p in products[:25]:  # Discord selects allow up to 25 items
            stock_label = f"({p['stock']} in stock)" if p['stock'] >= 0 else "(Unlimited)"
            options.append(discord.SelectOption(
                label=p["name"][:100],
                value=p["id"],
                description=f"{p['currency']} {p['price']:.2f} | {stock_label}"[:100],
                emoji="📦"
            ))

        super().__init__(
            placeholder="Select a product to view details & buy...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        selected_id = self.values[0]
        prod = self.products_map.get(selected_id)
        if not prod:
            await interaction.response.send_message("❌ Product not found.", ephemeral=True)
            return

        stock_text = f"🟢 **In Stock:** {prod['stock']} available" if prod['stock'] > 0 else (
            "♾️ **Unlimited Stock**" if prod['stock'] == -1 else "🔴 **Out of Stock**"
        )

        embed = discord.Embed(
            title=f"🛍️ {prod['name']}",
            description=prod['description'] or "No description provided.",
            color=discord.Color.blue()
        )
        embed.add_field(name="💰 Price", value=f"**{prod['currency']} {prod['price']:.2f}**", inline=True)
        embed.add_field(name="📦 Stock Status", value=stock_text, inline=True)
        embed.add_field(name="🆔 Product ID", value=f"`{prod['id']}`", inline=True)
        embed.set_footer(text="Click 'Buy Now' below to purchase via official checkout.")

        checkout_url = prod.get("url") or self.provider.get_checkout_url(prod.get("slug") or prod['id'])

        # Create interactive view with dropdown + buy button
        view = ProductView(self.products_map, self.provider, checkout_url=checkout_url, in_stock=(prod['stock'] != 0))
        await interaction.response.edit_message(embed=embed, view=view)


class BuyInDMButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="💬 Buy in DM (Crypto)",
            style=discord.ButtonStyle.success,
            custom_id="btn_trigger_buydm"
        )

    async def callback(self, interaction: discord.Interaction):
        dm_cog = interaction.client.get_cog("DM Shop & Crypto")
        if dm_cog:
            await dm_cog.buy_dm(interaction)
        else:
            await interaction.response.send_message("DM checkout service is currently unavailable.", ephemeral=True)


class ProductView(discord.ui.View):
    """View container for shop dropdown and buy button."""

    def __init__(self, products_map: Dict[str, Dict[str, Any]], provider: StoreProvider, checkout_url: Optional[str] = None, in_stock: bool = True):
        super().__init__(timeout=180)
        self.add_item(ProductSelect(list(products_map.values()), provider))

        if checkout_url:
            if in_stock:
                self.add_item(discord.ui.Button(
                    label="🛒 Buy Now (Store)",
                    style=discord.ButtonStyle.link,
                    url=checkout_url
                ))
            else:
                button = discord.ui.Button(label="Out of Stock", style=discord.ButtonStyle.secondary, disabled=True)
                self.add_item(button)

        # Button to trigger DM Checkout with Crypto
        self.add_item(BuyInDMButton())


class CustomerShopCog(commands.Cog, name="Store & Customer"):

    """Customer-facing commands for browsing stock, purchasing, and verifying orders."""

    def __init__(self, bot: commands.Bot, provider: StoreProvider, db: OrderDatabase):
        self.bot = bot
        self.provider = provider
        self.db = db

    @app_commands.command(name="stock", description="Check current stock and prices for all products.")
    async def view_stock(self, interaction: discord.Interaction):
        await interaction.response.defer()
        products = await self.provider.get_products()

        if not products:
            await interaction.followup.send("ℹ️ No products currently listed or store API is not connected.")
            return

        embed = discord.Embed(
            title="📦 Current Store Inventory",
            description="Live stock status automatically synced with our store.",
            color=discord.Color.green()
        )

        for p in products:
            if p["stock"] > 0:
                stock_str = f"🟢 `{p['stock']} in stock`"
            elif p["stock"] == -1:
                stock_str = "♾️ `Unlimited`"
            else:
                stock_str = "🔴 `Out of stock`"

            embed.add_field(
                name=f"{p['name']} ({p['currency']} {p['price']:.2f})",
                value=f"Status: {stock_str}\nProduct ID: `{p['id']}`",
                inline=False
            )

        embed.set_footer(text="Use /shop to browse interactively or /buy [product_id] to purchase.")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="shop", description="Open interactive product browser and checkout menu.")
    async def view_shop(self, interaction: discord.Interaction):
        await interaction.response.defer()
        products = await self.provider.get_products()

        if not products:
            await interaction.followup.send("ℹ️ No active products found in the store catalog.")
            return

        embed = discord.Embed(
            title="🛒 Welcome to our Auto Shop!",
            description="Select an item from the menu below to view details and proceed to checkout.",
            color=discord.Color.blurple()
        )
        embed.set_footer(text="Automated delivery & instant role assignment.")

        view = ProductView({p["id"]: p for p in products}, self.provider)
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="buy", description="Get an instant checkout link for a product.")
    @app_commands.describe(product_id="The Product ID from /stock or /shop")
    async def buy_product(self, interaction: discord.Interaction, product_id: str):
        await interaction.response.defer(ephemeral=True)
        product = await self.provider.get_product(product_id)

        if not product:
            await interaction.followup.send(f"❌ Product `{product_id}` not found on the store.", ephemeral=True)
            return

        checkout_url = product.get("url") or self.provider.get_checkout_url(product.get("slug") or product_id)
        stock_status = f"{product['stock']} available" if product['stock'] >= 0 else "Unlimited"

        embed = discord.Embed(
            title=f"💳 Checkout: {product['name']}",
            description=f"Price: **{product['currency']} {product['price']:.2f}**\nStock: **{stock_status}**\n\nClick the button below to complete your purchase safely.",
            color=discord.Color.teal()
        )

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Proceed to Checkout", style=discord.ButtonStyle.link, url=checkout_url))
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="verify", description="Verify your purchase order and claim your Customer Role.")
    @app_commands.describe(order_id="Your Order ID or Invoice ID from your purchase receipt")
    async def verify_order(self, interaction: discord.Interaction, order_id: str):
        await interaction.response.defer(ephemeral=True)
        order_id = order_id.strip()

        # 1. Check if order was already claimed in database
        claimed = self.db.is_order_claimed(order_id)
        if claimed:
            claimed_by = claimed['discord_user_id']
            await interaction.followup.send(
                f"❌ Order `{order_id}` has already been claimed on this server by <@{claimed_by}>.",
                ephemeral=True
            )
            return

        # 2. Query store provider for order verification
        order = await self.provider.get_order(order_id)
        if not order:
            await interaction.followup.send(
                f"❌ Could not find order `{order_id}`. Please double check your receipt ID.",
                ephemeral=True
            )
            return

        if not order["is_paid"]:
            await interaction.followup.send(
                f"⏳ Order `{order_id}` status is **{order['status']}** (not completed yet).\nPlease wait until payment completes and try again.",
                ephemeral=True
            )
            return

        # 3. Order is verified and paid! Record to database
        self.db.record_verified_order(
            order_id=order_id,
            discord_user_id=interaction.user.id,
            product_name=order.get("product_name", "")
        )

        # 4. Grant customer role
        customer_role_id = os.getenv("CUSTOMER_ROLE_ID", "").strip()
        role_assigned_msg = ""

        if customer_role_id.isdigit() and isinstance(interaction.user, discord.Member):
            role = interaction.guild.get_role(int(customer_role_id))
            if role:
                try:
                    await interaction.user.add_roles(role, reason=f"Verified order {order_id}")
                    role_assigned_msg = f"\n🎖️ You have been granted the **{role.name}** role!"
                except Exception as e:
                    logger.error(f"Failed to assign role to {interaction.user.id}: {e}")
                    role_assigned_msg = "\n⚠️ Could not automatically assign role. Please contact an admin."
            else:
                logger.warning(f"Configured CUSTOMER_ROLE_ID {customer_role_id} not found in guild.")

        embed = discord.Embed(
            title="🎉 Order Verified Successfully!",
            description=(
                f"**Order ID:** `{order_id}`\n"
                f"**Product:** {order['product_name']}\n"
                f"**Amount:** {order['currency']} {order['total']:.2f}\n"
                f"**Status:** Confirmed Paid ✅"
                f"{role_assigned_msg}"
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text="Thank you for your purchase!")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="terms", description="View store Terms of Service & Refund Policy.")
    async def view_terms(self, interaction: discord.Interaction):
        domain = os.getenv("SHOPPEX_STORE_DOMAIN", "vampire-martt.myshoppex.io")
        embed = discord.Embed(
            title="📜 Terms of Service & Store Policies",
            description=(
                "**1. Digital Goods Delivery**\n"
                "All items are digital products delivered automatically upon payment confirmation via Shoppex.\n\n"
                "**2. Replacement & Warranty Policy**\n"
                "• Report defective/invalid items within **24 hours** with valid video/screenshot proof.\n"
                "• Validated issues will receive an instant replacement from stock.\n\n"
                "**3. Role Claims & Verification**\n"
                "• Orders can only be claimed once via `/verify [order_id]`.\n"
                "• Sharing order IDs to grant unauthorized roles is prohibited.\n\n"
                "**4. No Abuse / Chargebacks**\n"
                "Fraudulent chargebacks or bot abuse will lead to an immediate ban and store blacklist."
            ),
            color=discord.Color.dark_theme()
        )
        embed.set_footer(text=f"Store: {domain} | Vampire Martt")

        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Visit Official Store",
            style=discord.ButtonStyle.link,
            url=f"https://{domain}"
        ))
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    provider = bot.provider
    db = bot.db
    await bot.add_cog(CustomerShopCog(bot, provider, db))
