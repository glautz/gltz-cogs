from .slapper import SlapPer


async def setup(bot):
    await bot.add_cog(SlapPer(bot))
