import random
from redbot.core import commands

class TeamMaker(commands.Cog):
    """My custom cog"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def teamshuffle(self, ctx, *names):
        """
        Shuffle 10 names into two teams.
        Usage: [p]teamshuffle name1 name2 name3 ... name10
        """
        names = list(names)

        if len(names) != 10:
            await ctx.send("Please provide exactly **10 names**.")
            return

        random.shuffle(names)

        team1 = names[:5]
        team2 = names[5:]

        msg = (
            "**Team 1:**\n" +
            "\n".join(team1) +
            "\n\n**Team 2:**\n" +
            "\n".join(team2)
        )

        await ctx.send(msg)
