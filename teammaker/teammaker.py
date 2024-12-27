from redbot.core import commands

class teamMaker(commands.Cog):
    """teammaker cog"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def teamshuffle(self, ctx):
        """This does stuff!"""
        # Your code will go here
        await ctx.send("I can do stuff!")
