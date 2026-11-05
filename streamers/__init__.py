from .streamers import Streamers


async def setup(bot):
    await bot.add_cog(Streamers(bot))
