import asyncio
import aiohttp
import discord
from redbot.core import commands, Config
from datetime import datetime


class XKCD(commands.Cog):
    """Posts new XKCD comics to a channel when they're released."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567891)
        self.config.register_guild(
            comic_channel=None,  # Channel ID where comics will be posted
            last_comic_id=0,     # Track the last comic posted
            check_interval=300   # Check every 5 minutes (in seconds)
        )
        self.session = None
        self.comic_check_task = None

    async def cog_load(self):
        """Initialize the session and start the background task."""
        self.session = aiohttp.ClientSession()
        self.comic_check_task = asyncio.create_task(self.check_new_comics())

    async def cog_unload(self):
        """Clean up the session and cancel the background task."""
        if self.session:
            await self.session.close()
        if self.comic_check_task:
            self.comic_check_task.cancel()

    async def get_latest_comic(self):
        """Fetch the latest XKCD comic info from the API."""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            async with self.session.get("https://xkcd.com/info.0.json", timeout=10) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except asyncio.TimeoutError:
            print("XKCD API request timed out")
            return None
        except Exception as e:
            print(f"Error fetching XKCD comic: {e}")
            return None

    async def check_new_comics(self):
        """Background task that checks for new XKCD comics."""
        await self.bot.wait_until_ready()
        
        while not self.bot.is_closed():
            try:
                # Get all guilds that have comic channels configured
                for guild_id in await self.config.all_guilds():
                    guild = self.bot.get_guild(guild_id)
                    if not guild:
                        continue

                    comic_channel_id = await self.config.guild(guild).comic_channel()
                    if not comic_channel_id:
                        continue

                    channel = guild.get_channel(comic_channel_id)
                    if not channel:
                        continue

                    # Get the latest comic
                    latest_comic = await self.get_latest_comic()
                    if not latest_comic:
                        continue

                    latest_id = latest_comic.get("num")
                    last_posted_id = await self.config.guild(guild).last_comic_id()

                    # If there's a new comic, post it
                    if latest_id > last_posted_id:
                        embed = self.create_comic_embed(latest_comic)
                        try:
                            await channel.send(embed=embed)
                            await self.config.guild(guild).last_comic_id.set(latest_id)
                        except discord.Forbidden:
                            print(f"No permission to post in {channel.name}")
                        except Exception as e:
                            print(f"Error posting comic: {e}")

                # Check interval (default 5 minutes)
                intervals = [
                    await self.config.guild(gid).check_interval()
                    for gid in await self.config.all_guilds()
                ]
                await asyncio.sleep(min(intervals) if intervals else 300)

            except Exception as e:
                print(f"Error in comic check task: {e}")
                await asyncio.sleep(300)

    def create_comic_embed(self, comic_data):
        """Create a Discord embed for the comic."""
        embed = discord.Embed(
            title=comic_data.get("title", "XKCD Comic"),
            url=f"https://xkcd.com/{comic_data.get('num')}/",
            description=comic_data.get("alt", ""),
            color=discord.Color.blue()
        )
        embed.set_image(url=comic_data.get("img"))
        embed.set_footer(text=f"Comic #{comic_data.get('num')} - {comic_data.get('date', 'Unknown')}")
        return embed

    @commands.hybrid_group(name="xkcd", fallback="latest")
    @commands.guild_only()
    async def xkcd_group(self, ctx):
        """Post the latest XKCD comic. Typing /xkcd and picking latest runs this."""
        async with ctx.typing():
            latest = await self.get_latest_comic()
            if not latest:
                await ctx.send("❌ Couldn't fetch the latest comic. Try again later.")
                return

            embed = self.create_comic_embed(latest)
            await ctx.send(embed=embed)

    @xkcd_group.command(name="setchannel")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel where new XKCD comics will be posted."""
        await self.config.guild(ctx.guild).comic_channel.set(channel.id)
        
        # Initialize with current comic number
        latest = await self.get_latest_comic()
        if latest:
            await self.config.guild(ctx.guild).last_comic_id.set(latest.get("num"))
            await ctx.send(f"✅ Comic channel set to {channel.mention}. Will start posting from comic #{latest.get('num')} onwards.")
        else:
            await ctx.send(f"✅ Comic channel set to {channel.mention}, but couldn't fetch current comic number.")

    @xkcd_group.command(name="removechannel")
    @commands.admin_or_permissions(manage_guild=True)
    async def remove_channel(self, ctx):
        """Remove the channel for posting XKCD comics."""
        await self.config.guild(ctx.guild).comic_channel.set(None)
        await ctx.send("❌ Comic posting disabled for this server.")

    @xkcd_group.command(name="status")
    async def status(self, ctx):
        """Check the current comic posting status."""
        channel_id = await self.config.guild(ctx.guild).comic_channel()
        last_id = await self.config.guild(ctx.guild).last_comic_id()
        
        if not channel_id:
            await ctx.send("❌ No comic channel configured. Use `xkcd setchannel <channel>` to set one.")
            return
        
        channel = ctx.guild.get_channel(channel_id)
        channel_mention = channel.mention if channel else f"<deleted channel {channel_id}>"
        
        await ctx.send(
            f"📺 **XKCD Status**\n"
            f"Channel: {channel_mention}\n"
            f"Last posted comic: #{last_id}"
        )
