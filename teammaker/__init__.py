from .teammaker import TeamMaker


async def setup(bot):
    await bot.add_cog(TeamMaker(bot))
