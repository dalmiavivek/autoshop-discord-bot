import discord
from discord import app_commands
from discord.ext import commands
import os
import logging
from typing import Optional, List
from providers.base import StoreProvider
from dataxbase import OrderDatabase

logger = logging.getLogger(__name__)

def is_admin():
    """Custom check to ensure command caller is a bot admin."""
    async def predicate(interaction: discord.Interaction) -> bool:
        # Check administrator server permission
        if interaction.user.guild_permissions.administrator:
            return True

        # Check configured admin user IDs
        admin_ids_raw = os.getenv("ADMIN_USER_IDS", "")
        admin_ids = [int(i.strip()) for i in admin_ids_raw.split(",") if i.strip().isdigit()]
        if interaction.user.id in admin_ids:
            return True

        # Check configured admin role
        admin_role_id = os.getenv("ADMIN_ROLE_ID", "").strip()
        if admin_role_id.isdigit() and isinstance(interaction.user, discord.Member):
            role_ids = [r.id for r in interaction.user.roles]
            if int(admin_role_id) in role_ids:
                return True

        await interaction.response.send_message("❌ **Access Denied**: You do not have permission to use admin stock commands.", ephemeral=True)
        return False
    return app_commands.check(predicate)


class AddStockModal(discord.ui.Modal, title="Add Product Stock"):
    """Interactive modal allowing admins to paste multi-line serials directly in Discord."""
    serials_input = discord.ui.TextInput(
        label="Serials / Accounts / Keys (one per line)",
        style=discord.TextStyle.paragraph,
        placeholder="KEY1-ABC-XYZ\nKEY2-DEF-UVW\nuser:pass",
        required=True,
        max_length=4000
    )

    def __init__(self, provider: StoreProvider, db: OrderDatabase, product_id: str, product_name: str):
        super().__init__()
        self.provider = provider
        self.db = db
        self.product_id = product_id
        self.product_name = product_name

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        lines = [line.strip() for line in self.serials_input.value.splitlines() if line.strip()]

        if not lines:
            await interaction.followup.send("❌ No valid serials were provided.", ephemeral=True)
            return

        result = await self.provider.add_stock(self.product_id, lines)
        if result["success"]:
            added = result["added_count"]
            self.db.record_restock(self.product_id, self.product_name, added, interaction.user.id)

            embed = discord.Embed(
                title="✅ Stock Added Successfully",
                description=f"Added **{added}** item(s) to **{self.product_name}** (`{self.product_id}`).\nInventory is now updated on your shop.",
                color=discord.Color.green()
            )
            embed.set_footer(text=f"Stock synced by {interaction.user.display_name}")
            await interaction.followup.send(embed=embed, ephemeral=True)

            # Restock broadcast
            await self._send_restock_announcement(interaction.client, self.product_name, added)
        else:
            await interaction.followup.send(f"❌ Failed to add stock: {result['message']}", ephemeral=True)

    async def _send_restock_announcement(self, client: discord.Client, product_name: str, quantity: int):
        restock_channel_id = os.getenv("RESTOCK_CHANNEL_ID", "").strip()
        if restock_channel_id.isdigit():
            channel = client.get_channel(int(restock_channel_id))
            if channel:
                announce_embed = discord.Embed(
                    title="🎉 Restock Alert!",
                    description=f"**{product_name}** has just been restocked with **+{quantity}** units!\nUse `/shop` or `/buy` to purchase now.",
                    color=discord.Color.gold()
                )
                try:
                    await channel.send(embed=announce_embed)
                except Exception as e:
                    logger.error(f"Failed to send restock alert to channel: {e}")


class StockAdminCog(commands.Cog, name="Stock Administration"):
    """Commands for managing store inventory and synchronization."""

    def __init__(self, bot: commands.Bot, provider: StoreProvider, db: OrderDatabase):
        self.bot = bot
        self.provider = provider
        self.db = db

    @app_commands.command(name="addstock", description="[Admin] Add stock/serials to your Shoppex/SellAuth store in real-time.")
    @app_commands.describe(
        product_id="The Product ID from your store",
        serials="Optional: paste comma/space separated keys or leave empty for modal",
        file="Optional: upload a .txt file containing keys/accounts line by line"
    )
    @is_admin()
    async def add_stock(
        self,
        interaction: discord.Interaction,
        product_id: str,
        serials: Optional[str] = None,
        file: Optional[discord.Attachment] = None
    ):
        # 1. Fetch product to verify ID and get title
        product = await self.provider.get_product(product_id)
        product_name = product["name"] if product else product_id

        # 2. If a file was uploaded (.txt)
        if file:
            await interaction.response.defer(ephemeral=True)
            if not file.filename.endswith(('.txt', '.csv')):
                await interaction.followup.send("❌ Please upload a valid `.txt` or `.csv` file.", ephemeral=True)
                return

            try:
                content_bytes = await file.read()
                text = content_bytes.decode("utf-8", errors="ignore")
                lines = [l.strip() for l in text.splitlines() if l.strip()]
            except Exception as e:
                await interaction.followup.send(f"❌ Could not read uploaded file: {e}", ephemeral=True)
                return

            if not lines:
                await interaction.followup.send("❌ The uploaded file contained no items.", ephemeral=True)
                return

            result = await self.provider.add_stock(product_id, lines)
            if result["success"]:
                added = result["added_count"]
                self.db.record_restock(product_id, product_name, added, interaction.user.id)
                embed = discord.Embed(
                    title="✅ File Stock Uploaded",
                    description=f"Added **{added}** item(s) from `{file.filename}` to **{product_name}**.\nStore inventory updated automatically!",
                    color=discord.Color.green()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                await self._send_restock_announcement(product_name, added)
            else:
                await interaction.followup.send(f"❌ Failed to update stock: {result['message']}", ephemeral=True)
            return

        # 3. If serials argument was directly provided
        if serials:
            await interaction.response.defer(ephemeral=True)
            lines = [s.strip() for s in serials.replace(",", "\n").splitlines() if s.strip()]
            if not lines:
                await interaction.followup.send("❌ No valid serials found in input.", ephemeral=True)
                return

            result = await self.provider.add_stock(product_id, lines)
            if result["success"]:
                added = result["added_count"]
                self.db.record_restock(product_id, product_name, added, interaction.user.id)
                embed = discord.Embed(
                    title="✅ Stock Added",
                    description=f"Added **{added}** item(s) to **{product_name}**.\nStore inventory updated automatically!",
                    color=discord.Color.green()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                await self._send_restock_announcement(product_name, added)
            else:
                await interaction.followup.send(f"❌ Failed to update stock: {result['message']}", ephemeral=True)
            return

        # 4. If neither serials nor file provided, open interactive Modal
        modal = AddStockModal(self.provider, self.db, product_id, product_name)
        await interaction.response.send_modal(modal)

    async def _send_restock_announcement(self, product_name: str, quantity: int):
        restock_channel_id = os.getenv("RESTOCK_CHANNEL_ID", "").strip()
        if restock_channel_id.isdigit():
            channel = self.bot.get_channel(int(restock_channel_id))
            if channel:
                announce_embed = discord.Embed(
                    title="🎉 Restock Alert!",
                    description=f"**{product_name}** has just been restocked with **+{quantity}** units!\nUse `/shop` or `/buy` to purchase now.",
                    color=discord.Color.gold()
                )
                try:
                    await channel.send(embed=announce_embed)
                except Exception as e:
                    logger.error(f"Failed to send restock alert: {e}")

    @app_commands.command(name="sync", description="[Admin] Synchronize slash commands with Discord.")
    @is_admin()
    async def sync_commands(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            guild_id = os.getenv("GUILD_ID", "").strip()
            if guild_id.isdigit():
                guild = discord.Object(id=int(guild_id))
                self.bot.tree.copy_global_to(guild=guild)
                synced = await self.bot.tree.sync(guild=guild)
                await interaction.followup.send(f"✅ Synced {len(synced)} command(s) to test server ({guild_id}).", ephemeral=True)
            else:
                synced = await self.bot.tree.sync()
                await interaction.followup.send(f"✅ Synced {len(synced)} command(s) globally.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Sync failed: {e}", ephemeral=True)

    @app_commands.command(name="setcrypto", description="[Admin] Set receiving and forward payout crypto addresses for DM shop.")
    @app_commands.describe(
        token="Crypto Currency (LTC, USDT, BTC, SOL)",
        address="The receiving address where customers send payment",
        forward_payout_address="Optional: separate destination payout address"
    )
    @app_commands.choices(token=[
        app_commands.Choice(name="Litecoin (LTC)", value="LTC"),
        app_commands.Choice(name="Tether (USDT-TRC20)", value="USDT"),
        app_commands.Choice(name="Bitcoin (BTC)", value="BTC"),
        app_commands.Choice(name="Solana (SOL)", value="SOL")
    ])
    @is_admin()
    async def set_crypto(
        self,
        interaction: discord.Interaction,
        token: app_commands.Choice[str],
        address: str,
        forward_payout_address: Optional[str] = None
    ):
        await interaction.response.defer(ephemeral=True)
        token_val = token.value.upper()
        clean_addr = address.strip()
        forward_addr = (forward_payout_address or "").strip()

        self.db.set_crypto_address(
            token=token_val,
            address=clean_addr,
            network=token.name,
            payout_forward_address=forward_addr
        )

        embed = discord.Embed(
            title="✅ Crypto Address Configured",
            description=f"Updated receiving configuration for **{token.name}** (`{token_val}`).",
            color=discord.Color.green()
        )
        embed.add_field(name="📥 Receiving Address", value=f"`{clean_addr}`", inline=False)
        if forward_addr:
            embed.add_field(name="📤 Forward Destination Payout", value=f"`{forward_addr}`", inline=False)
        embed.set_footer(text="Customers can now purchase using this crypto token in DMs via /buydm.")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="cryptolist", description="[Admin] List all configured crypto receiving and payout addresses.")
    @is_admin()
    async def list_crypto(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        addresses = self.db.get_all_crypto_addresses()

        if not addresses:
            await interaction.followup.send("ℹ️ No crypto addresses configured yet. Use `/setcrypto` to add one.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🪙 Configured Store Crypto Addresses",
            description="Active receiving and forward payout addresses for DM shop orders.",
            color=discord.Color.gold()
        )

        for a in addresses:
            fwd = f"\n➡️ Forward to: `{a['payout_forward_address']}`" if a.get('payout_forward_address') else ""
            embed.add_field(
                name=f"💎 {a['token']} ({a.get('network', a['token'])})",
                value=f"📥 Receiving: `{a['address']}`{fwd}",
                inline=False
            )

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    provider = bot.provider
    db = bot.db
    await bot.add_cog(StockAdminCog(bot, provider, db))
