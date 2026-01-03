import random
from redbot.core import commands

class TeamMaker(commands.Cog):
    """Interactive team maker"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def maketeams(self, ctx):
        """
        Interactively create teams.
        The bot will ask:
        - number of players
        - number of teams
        - names of each player
        """

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        # Ask for number of players
        await ctx.send("How many players?")
        try:
            msg = await ctx.bot.wait_for("message", timeout=60, check=check)
            num_players = int(msg.content)
        except:
            return await ctx.send("Cancelled or invalid input.")

        # Ask for number of teams
        await ctx.send("How many teams?")
        try:
            msg = await ctx.bot.wait_for("message", timeout=60, check=check)
            num_teams = int(msg.content)
        except:
            return await ctx.send("Cancelled or invalid input.")

        if num_teams > num_players:
            return await ctx.send("You cannot have more teams than players.")

        # Collect player names
        players = []
        await ctx.send(f"Please enter **{num_players}** player names, one per message.")

        for i in range(num_players):
            await ctx.send(f"Name {i+1}:")
            try:
                msg = await ctx.bot.wait_for("message", timeout=60, check=check)
                players.append(msg.content)
            except:
                return await ctx.send("Timed out while waiting for names.")

        # Shuffle and split into teams
        random.shuffle(players)
        teams = [[] for _ in range(num_teams)]

        for i, player in enumerate(players):
            teams[i % num_teams].append(player)

        # Build output message
        output = ""
        for i, team in enumerate(teams, start=1):
            output += f"**Team {i}:**\n" + "\n".join(team) + "\n\n"

        await ctx.send(output)
