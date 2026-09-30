import discord
from discord.ext import commands
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class CloseTicketModal(discord.ui.Modal, title="Confirm Close Ticket"):
    reason_input = discord.ui.TextInput(
        label="Closing Reason",
        placeholder="Order fulfilled / Completed",
        required=False,
        max_length=200
    )

    def __init__(self, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.reason_input.value or "Order Completed"
        await interaction.response.send_message(f"🔒 Ticket is being closed by {interaction.user.mention} (Reason: {reason}). Channel will delete in 5 seconds...", ephemeral=False)
        try:
            import asyncio
            await asyncio.sleep(5)
            await self.channel.delete(reason=f"Closed by {interaction.user.name}: {reason}")
        except Exception as e:
            logger.error(f"Failed to delete ticket channel: {e}")


class TicketActionView(discord.ui.View):
    """View with staff actions inside the ticket channel."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, custom_id="btn_close_ticket")
    async def close_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Allow buyer or admins/staff to close
        is_staff = interaction.user.guild_permissions.administrator
        admin_ids_raw = os.getenv("ADMIN_USER_IDS", "")
        if str(interaction.user.id) in admin_ids_raw.split(","):
            is_staff = True

        staff_role_id = os.getenv("STAFF_ROLE_ID", "").strip() or os.getenv("ADMIN_ROLE_ID", "").strip()
        if staff_role_id.isdigit() and isinstance(interaction.user, discord.Member):
            if int(staff_role_id) in [r.id for r in interaction.user.roles]:
                is_staff = True

        if not is_staff and not interaction.channel.name.startswith(f"order-{interaction.user.name[:10].lower()}"):
            await interaction.response.send_message("❌ Only staff or the order buyer can close this ticket.", ephemeral=True)
            return

        modal = CloseTicketModal(interaction.channel)
        await interaction.response.send_modal(modal)


async def create_order_ticket(
    guild: discord.Guild,
    buyer: discord.User,
    invoice: Dict[str, Any],
    delivery_info: str = ""
) -> Optional[discord.TextChannel]:
    """
    Creates a private order ticket channel in the configured category
    with strict permissions for buyer and staff only.
    """
    try:
        # 1. Resolve Category
        category_id_str = os.getenv("TICKET_CATEGORY_ID", "").strip()
        category: Optional[discord.CategoryChannel] = None

        if category_id_str.isdigit():
            category = guild.get_channel(int(category_id_str))

        if not category or not isinstance(category, discord.CategoryChannel):
            # Fallback: search by name or create category
            for cat in guild.categories:
                if "ORDER" in cat.name.upper() or "TICKET" in cat.name.upper():
                    category = cat
                    break

            if not category:
                category = await guild.create_category("🛒 ORDERS & TICKETS")

        # 2. Configure Overwrites
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            buyer: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
                embed_links=True
            )
        }

        # Add Staff Role overwrite if configured
        staff_role_id = os.getenv("STAFF_ROLE_ID", "").strip() or os.getenv("ADMIN_ROLE_ID", "").strip()
        if staff_role_id.isdigit():
            staff_role = guild.get_role(int(staff_role_id))
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True
                )

        # 3. Create Channel
        short_id = invoice["invoice_id"][-4:]
        clean_name = f"order-{buyer.name[:10]}-{short_id}".lower().replace(" ", "-")
        channel = await guild.create_text_channel(
            name=clean_name,
            category=category,
            overwrites=overwrites,
            topic=f"Order Ticket for {buyer.name} | Order ID: {invoice['invoice_id']}"
        )

        # 4. Post Welcome Embed
        token = invoice.get("token", "CRYPTO")
        crypto_amt = invoice.get("expected_crypto_amount", 0.0)
        fiat_amt = invoice.get("fiat_amount", 0.0)
        fiat_curr = invoice.get("fiat_currency", "USD")
        txid = invoice.get("txid", "")

        tx_link = f"[{txid[:16]}...]({invoice.get('explorer_url', '')})" if txid else "Confirmed On-Chain ✅"

        embed = discord.Embed(
            title=f"🎉 Order Confirmed! [#{invoice['invoice_id']}]",
            description=f"Welcome {buyer.mention}! Your crypto payment has been received and verified on the blockchain.",
            color=discord.Color.green()
        )
        embed.add_field(name="📦 Product", value=f"**{invoice['product_name']}**", inline=False)
        embed.add_field(name="💰 Amount Paid", value=f"**{crypto_amt} {token}** (~{fiat_curr} {fiat_amt:.2f})", inline=True)
        embed.add_field(name="🔗 Blockchain TXID", value=tx_link, inline=True)
        embed.add_field(name="📥 Receiving Address", value=f"`{invoice['deposit_address']}`", inline=False)

        forward_payout = invoice.get("forward_payout_address", "")
        if forward_payout:
            embed.add_field(name="📤 Forward Destination Payout", value=f"`{forward_payout}`", inline=False)

        if delivery_info:
            embed.add_field(name="📋 Delivery & Instructions", value=delivery_info, inline=False)
        else:
            embed.add_field(name="📋 Fulfillment", value="A staff member will assist you or deliver your items shortly!", inline=False)

        embed.set_footer(text="Staff: Click 'Close Ticket' below when the order is fulfilled.")

        view = TicketActionView()
        staff_role_id = os.getenv("STAFF_ROLE_ID", "").strip() or os.getenv("ADMIN_ROLE_ID", "").strip()
        staff_ping = f" <@&{staff_role_id}>" if staff_role_id.isdigit() else ""
        await channel.send(
            content=f"🔔 {buyer.mention}{staff_ping} Order Ticket Created! Staff has been notified.",
            embed=embed,
            view=view
        )

        return channel
    except Exception as e:
        logger.error(f"Error creating ticket channel: {e}", exc_info=True)
        return None


class TicketsCog(commands.Cog, name="Tickets"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Register persistent view for ticket action buttons
        self.bot.add_view(TicketActionView())


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketsCog(bot))

