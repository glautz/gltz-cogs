import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

import aiohttp
import discord
from redbot.core import Config, commands

log = logging.getLogger(__name__)

ATOM_NS = "http://www.w3.org/2005/Atom"
MEDIA_NS = "http://search.org/rss/media/"
YT_NS = "http://www.youtube.com/xml/schemas/2015"


class Streamers(commands.Cog):
    """Posts when Twitch/YouTube channels go live. React to a live post to get pinged the next time they go live."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567892)
        self.config.register_guild(
            post_channel=None,  # Channel ID where live announcements are posted
            streamers={},       # "platform:target" -> display name
            subscribers={},     # "platform:target" -> [user IDs]
            last_live={},       # "platform:target" -> last posted live ID
            posts={},           # message ID -> streamer key, for reaction subscriptions
        )
        self.config.register_global(
            twitch_client_id=None,
            twitch_client_secret=None,
            twitch_token=None,
            twitch_token_expiry=0,
        )
        self.session = None
        self.live_check_task = None
        self._no_creds_warned = False

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        self.live_check_task = asyncio.create_task(self.check_live_streams())

    async def cog_unload(self):
        if self.session:
            await self.session.close()
        if self.live_check_task:
            self.live_check_task.cancel()

    async def get_twitch_token(self):
        client_id = await self.config.twitch_client_id()
        client_secret = await self.config.twitch_client_secret()
        if not client_id or not client_secret:
            return None
        token = await self.config.twitch_token()
        expiry = await self.config.twitch_token_expiry()
        if token and time.time() < expiry:
            return token
        async with self.session.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            timeout=10,
        ) as resp:
            if resp.status != 200:
                log.warning("Twitch token request failed: %s", resp.status)
                await self.config.twitch_token.set(None)
                return None
            data = await resp.json()
        token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        await self.config.twitch_token.set(token)
        await self.config.twitch_token_expiry.set(time.time() + expires_in - 60)
        return token

    async def get_twitch_live(self, login):
        token = await self.get_twitch_token()
        if not token:
            if not self._no_creds_warned:
                self._no_creds_warned = True
                log.warning("Twitch credentials not set. Use `streamers twitchcreds <client_id> <client_secret>`.")
            return None
        client_id = await self.config.twitch_client_id()
        headers = {"Client-Id": client_id, "Authorization": f"Bearer {token}"}
        async with self.session.get(
            "https://api.twitch.tv/helix/streams",
            params={"user_login": login},
            headers=headers,
            timeout=10,
        ) as resp:
            if resp.status == 401:
                await self.config.twitch_token.set(None)
                return None
            if resp.status != 200:
                log.warning("Twitch API request failed for %s: %s", login, resp.status)
                return None
            data = (await resp.json()).get("data", [])
        if not data:
            return None
        item = data[0]
        thumb = item.get("thumbnail_url", "").replace("{width}", "640").replace("{height}", "360")
        return {
            "id": item["id"],
            "title": item.get("title", ""),
            "game": item.get("game_name", ""),
            "url": item.get("url", f"https://twitch.tv/{login}"),
            "thumbnail": thumb,
            "platform": "twitch",
        }

    async def get_youtube_live(self, channel_id):
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        async with self.session.get(url, timeout=10) as resp:
            if resp.status != 200:
                return None
            text = await resp.text()
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return None
        for entry in root.findall(f"{{{ATOM_NS}}}entry"):
            group = entry.find(f"{{{MEDIA_NS}}}group")
            if group is None:
                continue
            keywords = group.find(f"{{{MEDIA_NS}}}keywords")
            if keywords is None or not keywords.text:
                continue
            if keywords.text.strip().lower() != "live":
                continue
            video_id = entry.find(f"{{{YT_NS}}}videoId")
            title = entry.find(f"{{{ATOM_NS}}}title")
            link = entry.find(f"{{{ATOM_NS}}}link")
            thumb = group.find(f"{{{MEDIA_NS}}}thumbnail")
            vid = video_id.text if video_id is not None else ""
            return {
                "id": vid,
                "title": title.text if title is not None else "",
                "game": "",
                "url": link.get("href") if link is not None else f"https://www.youtube.com/watch?v={vid}",
                "thumbnail": thumb.get("url") if thumb is not None else None,
                "platform": "youtube",
            }
        return None

    async def create_live_embed(self, display, live):
        color = discord.Color.purple() if live["platform"] == "youtube" else discord.Color.blue()
        embed = discord.Embed(title=f"{display} is live!", url=live["url"], color=color)
        if live["title"]:
            embed.description = live["title"]
        if live["game"]:
            embed.add_field(name="Playing", value=live["game"], inline=False)
        if live.get("thumbnail"):
            embed.set_thumbnail(url=live["thumbnail"])
        embed.set_footer(text="Twitch" if live["platform"] == "twitch" else "YouTube")
        return embed

    async def check_live_streams(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                for guild_id, data in (await self.config.all_guilds()).items():
                    guild = self.bot.get_guild(guild_id)
                    if not guild or not data["post_channel"]:
                        continue
                    channel = guild.get_channel(data["post_channel"])
                    if not channel:
                        continue
                    conf = self.config.guild(guild)
                    for key, display in data["streamers"].items():
                        platform, target = key.split(":", 1)
                        if platform == "twitch":
                            live = await self.get_twitch_live(target)
                        else:
                            live = await self.get_youtube_live(target)
                        last = data["last_live"].get(key)
                        if not live:
                            if last:
                                data["last_live"][key] = None
                                await conf.last_live.set(data["last_live"])
                            continue
                        if last == live["id"]:
                            continue
                        subs = [uid for uid in data["subscribers"].get(key, []) if guild.get_member(uid)]
                        content = " ".join(f"<@{uid}>" for uid in subs)
                        embed = await self.create_live_embed(display, live)
                        try:
                            msg = await channel.send(content=content or None, embed=embed)
                        except discord.Forbidden:
                            log.warning("No permission to post in %s", channel.name)
                            continue
                        data["last_live"][key] = live["id"]
                        await conf.last_live.set(data["last_live"])
                        posts = {str(msg.id): key, **data["posts"]}
                        posts = dict(list(posts.items())[-100:])
                        data["posts"] = posts
                        await conf.posts.set(posts)
            except Exception:
                log.exception("Error in live check task")
            await asyncio.sleep(60)

    def normalize_target(self, platform, target):
        platform = platform.lower().strip()
        target = target.strip()
        if platform == "twitch":
            login = target.lower()
            if not re.fullmatch(r"[a-z0-9_]{3,25}", login):
                return None, None
            return platform, login
        if platform == "youtube":
            if target.startswith("UC") and len(target) == 24:
                return platform, target
            parsed = urlparse(target)
            qs = parse_qs(parsed.query)
            if qs.get("channel_id"):
                return platform, qs["channel_id"][0]
            for part in parsed.path.split("/"):
                if part.startswith("UC") and len(part) == 24:
                    return platform, part
            return None, None
        return None, None

    async def get_youtube_title(self, channel_id):
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        async with self.session.get(url, timeout=10) as resp:
            if resp.status != 200:
                return channel_id
            text = await resp.text()
        try:
            root = ET.fromstring(text)
            title = root.find(f"{{{ATOM_NS}}}title")
            return title.text if title is not None and title.text else channel_id
        except ET.ParseError:
            return channel_id

    async def get_twitch_display(self, login):
        token = await self.get_twitch_token()
        if not token:
            return login
        client_id = await self.config.twitch_client_id()
        headers = {"Client-Id": client_id, "Authorization": f"Bearer {token}"}
        async with self.session.get(
            "https://api.twitch.tv/helix/users",
            params={"login": login},
            headers=headers,
            timeout=10,
        ) as resp:
            if resp.status == 401:
                await self.config.twitch_token.set(None)
            elif resp.status == 200:
                data = (await resp.json()).get("data", [])
                if data:
                    return data[0].get("display_name", login)
        return login

    @commands.hybrid_group(name="streamers", fallback="status")
    @commands.guild_only()
    async def streamers_group(self, ctx):
        """Show the live-notifier status."""
        conf = self.config.guild(ctx.guild)
        channel_id = await conf.post_channel()
        streamers = await conf.streamers()
        subscribers = await conf.subscribers()
        creds = await self.config.twitch_client_id()
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        lines = [
            "**Streamers status**",
            f"Post channel: {channel.mention if channel else 'not set (`streamers channel <channel>`!)'}",
            f"Twitch API: {'configured' if creds else 'not set (owner: `streamers twitchcreds <id> <secret>`!)'}",
        ]
        if not streamers:
            lines.append("No streamers tracked. Add one with `streamers add twitch <login>`.")
        for key, display in streamers.items():
            platform, target = key.split(":", 1)
            if platform == "twitch":
                live = await self.get_twitch_live(target)
            else:
                live = await self.get_youtube_live(target)
            state = "🔴 LIVE" if live else "offline"
            lines.append(f"- **{display}** ({platform}): {state} — {len(subscribers.get(key, []))} subscriber(s)")
        await ctx.send("\n".join(lines))

    @streamers_group.command(name="add")
    @commands.admin_or_permissions(manage_guild=True)
    async def add_streamer(self, ctx, platform: str, target: str):
        """Add a Twitch login (e.g. glautz) or YouTube channel ID (UC...). React to the bot's live posts to get pinged when they're live."""
        platform, target = self.normalize_target(platform, target)
        if not platform:
            await ctx.send("❌ Platform must be `twitch` (login) or `youtube` (channel ID, UC...).")
            return
        conf = self.config.guild(ctx.guild)
        streamers = await conf.streamers()
        key = f"{platform}:{target}"
        if key in streamers:
            await ctx.send(f"✅ {streamers[key]} is already tracked.")
            return
        if platform == "twitch":
            display = await self.get_twitch_display(target)
        else:
            display = await self.get_youtube_title(target)
        streamers[key] = display
        await conf.streamers.set(streamers)
        await ctx.send(
            f"✅ Now tracking **{display}** ({platform}). "
            "React to the live announcement post to get pinged next time they go live."
        )

    @streamers_group.command(name="remove")
    @commands.admin_or_permissions(manage_guild=True)
    async def remove_streamer(self, ctx, platform: str, target: str):
        """Stop tracking a streamer."""
        platform, target = self.normalize_target(platform, target)
        if not platform:
            await ctx.send("❌ Platform must be `twitch` (login) or `youtube` (channel ID, UC...).")
            return
        conf = self.config.guild(ctx.guild)
        key = f"{platform}:{target}"
        streamers = await conf.streamers()
        if key not in streamers:
            await ctx.send(f"❌ {key} is not tracked in this server.")
            return
        display = streamers.pop(key)
        subscribers = await conf.subscribers()
        subscribers.pop(key, None)
        last_live = await conf.last_live()
        last_live.pop(key, None)
        await conf.streamers.set(streamers)
        await conf.subscribers.set(subscribers)
        await conf.last_live.set(last_live)
        await ctx.send(f"✅ Stopped tracking **{display}**.")

    @streamers_group.command(name="list")
    async def list_streamers(self, ctx):
        """List tracked streamers and subscriber counts."""
        streamers = await self.config.guild(ctx.guild).streamers()
        subscribers = await self.config.guild(ctx.guild).subscribers()
        if not streamers:
            await ctx.send("No streamers tracked. Add one with `streamers add twitch <login>`.")
            return
        lines = ["**Tracked streamers**"]
        for key, display in streamers.items():
            lines.append(f"- **{display}** ({key.split(':', 1)[0]}) — {len(subscribers.get(key, []))} subscriber(s)")
        await ctx.send("\n".join(lines))

    @streamers_group.command(name="channel")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_post_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel where live announcements are posted."""
        await self.config.guild(ctx.guild).post_channel.set(channel.id)
        await ctx.send(f"✅ Live announcements will be posted in {channel.mention}.")

    @streamers_group.command(name="test")
    @commands.admin_or_permissions(manage_guild=True)
    async def test_live(self, ctx, platform: str, target: str):
        """Post a live announcement in the post channel right now, to test reactions/pings."""
        platform, target = self.normalize_target(platform, target)
        if not platform:
            await ctx.send("❌ Platform must be `twitch` (login) or `youtube` (channel ID, UC...).")
            return
        conf = self.config.guild(ctx.guild)
        key = f"{platform}:{target}"
        streamers = await conf.streamers()
        if key not in streamers:
            await ctx.send(f"❌ {key} is not tracked. Add it with `streamers add` first.")
            return
        channel_id = await conf.post_channel()
        channel = ctx.guild.get_channel(channel_id) if channel_id else None
        if not channel:
            await ctx.send("❌ No post channel set. Use `streamers channel <channel>` first.")
            return
        if platform == "twitch":
            live = await self.get_twitch_live(target)
            if not live:
                live = {
                    "id": "test",
                    "title": "Test live post (not actually live)",
                    "game": "",
                    "url": f"https://twitch.tv/{target}",
                    "thumbnail": "",
                    "platform": "twitch",
                }
        else:
            live = await self.get_youtube_live(target)
            if not live:
                live = {
                    "id": "test",
                    "title": "Test live post (not actually live)",
                    "game": "",
                    "url": f"https://www.youtube.com/{target}",
                    "thumbnail": "",
                    "platform": "youtube",
                }
        subs = [uid for uid in (await conf.subscribers()).get(key, []) if ctx.guild.get_member(uid)]
        content = " ".join(f"<@{uid}>" for uid in subs)
        embed = await self.create_live_embed(streamers[key], live)
        msg = await channel.send(content=content or None, embed=embed)
        posts = {str(msg.id): key, **(await conf.posts())}
        posts = dict(list(posts.items())[-100:])
        await conf.posts.set(posts)
        await ctx.send(f"✅ Posted a test announcement in {channel.mention}. React to it to subscribe for pings.")

    @streamers_group.command(name="twitchcreds")
    @commands.is_owner()
    async def set_twitch_creds(self, ctx, client_id: str, client_secret: str):
        """Set Twitch app credentials (owner only). Create an app at dev.twitch.tv/console, add the bot as an integration, then use its Client ID/Secret."""
        await self.config.twitch_client_id.set(client_id)
        await self.config.twitch_client_secret.set(client_secret)
        await self.config.twitch_token.set(None)
        await ctx.send("✅ Twitch credentials saved.")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        await self.handle_reaction(payload, add=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        await self.handle_reaction(payload, add=False)

    async def handle_reaction(self, payload, add):
        guild = self.bot.get_guild(payload.guild_id)
        if not guild or payload.user_id == self.bot.user.id:
            return
        conf = self.config.guild(guild)
        posts = await conf.posts()
        key = posts.get(str(payload.message_id))
        if not key:
            return
        if payload.channel_id != await conf.post_channel():
            return
        streamers = await conf.streamers()
        if key not in streamers:
            return
        subscribers = await conf.subscribers()
        lst = subscribers.get(key, [])
        if add:
            if payload.user_id not in lst:
                lst.append(payload.user_id)
                subscribers[key] = lst
                await conf.subscribers.set(subscribers)
        elif payload.user_id in lst:
            lst.remove(payload.user_id)
            subscribers[key] = lst
            await conf.subscribers.set(subscribers)
