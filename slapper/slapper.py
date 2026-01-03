from redbot.core import commands
from redbot.core.bot import Red
import discord

class Slapper(commands.Cog):
    """Slap command cog."""

    def __init__(self, bot: Red):
        self.bot = bot

    @commands.hybrid_command(name="slap", description="Slap someone with a large trout.")
    async def slap(self, ctx: commands.Context, user: discord.Member):
        invoker = ctx.author.mention
        target = user.mention
        await ctx.send(f"{invoker} slaps {target} with a large trout!")

async def setup(bot: Red):
    await bot.add_cog(Slapper(bot))
