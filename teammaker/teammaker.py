import random
from redbot.core import commands

class TeamMaker(commands.Cog):
    """Interactive team maker with emoji opt-in"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def reactteams(self, ctx):
        """
        Create teams by having users react with 👍 to join.
        Then the bot asks how many teams to make.
        """

        def check_author(m):
            return m.author == ctx.author and m.channel == ctx.channel

        # Ask for number of teams
        await ctx.send("How many teams do you want?")
        try:
            msg = await ctx.bot.wait_for("message", timeout=60, check=check_author)
            num_teams = int(msg.content)
        except:
            return await ctx.send("Invalid input or timed out.")

        if num_teams < 1:
            return await ctx.send("You need at least 1 team.")

        # Ask users to react to join
        join_msg = await ctx.send(
            "React with 👍 to join the game!\n"
            "You have **30 seconds** to react."
        )
        await join_msg.add_reaction("👍")

        # Wait 30 seconds (we don't care about reaction events)
        try:
            await ctx.bot.wait_for("message", timeout=30, check=lambda m: False)
        except:
            pass  # This timeout is expected

        # Fetch updated message with reactions
        join_msg = await ctx.channel.fetch_message(join_msg.id)

        # Collect users who reacted
        players = []
        for reaction in join_msg.reactions:
            if reaction.emoji == "👍":
                async for user in reaction.users():
                    if not user.bot:
                        players.append(user.name)

        # Remove duplicates
        players = list(dict.fromkeys(players))

        if len(players) == 0:
            return await ctx.send("No players joined.")

        if num_teams > len(players):
            return await ctx.send("More teams than players is not allowed.")

        # Shuffle and split into teams
        random.shuffle(players)
        teams = [[] for _ in range(num_teams)]

        for i, player in enumerate(players):
            teams[i % num_teams].append(player)

        # Build output
        output = f"**Players joined:** {len(players)}\n\n"
        for i, team in enumerate(teams, start=1):
            output += f"**Team {i}:**\n" + "\n".join(team) + "\n\n"

        await ctx.send(output)
