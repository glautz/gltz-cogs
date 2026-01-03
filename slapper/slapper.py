from redbot.core import commands
from redbot.core.bot import Red
import discord

class SlapPer(commands.Cog):
    """Slap command cog."""

    def __init__(self, bot: Red):
        self.bot = bot

    @commands.command()
    async def load(self, ctx):
        """Dummy command to load slash commands (ignore)."""
        pass

    @commands.hybrid_command(name="slap", description="Slap someone with a large trout.")
    async def slap(self, ctx: commands.Context, user: discord.Member):
        """Slap a user with a large trout."""
        invoker = ctx.author.mention
        target = user.mention
        await ctx.send(f"{invoker} slaps {target} with a large trout!")
