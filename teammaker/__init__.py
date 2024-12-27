from .teammaker import teamMaker


async def setup(bot):
    await bot.add_cog(teamMaker(bot))
