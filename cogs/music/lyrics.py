"""
cogs/music/lyrics.py
/lyrics <song> — fetches lyrics from lyrics.ovh (free, no API key needed).
Falls back to searching the current playing track.
"""
import discord, aiohttp
from discord import app_commands
from discord.ext import commands
from utils.helpers import error_embed, base_embed
import config

LYRICS_API = "https://api.lyrics.ovh/v1/{artist}/{title}"
SEARCH_API = "https://api.lyrics.ovh/suggest/{query}"


class Lyrics(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="lyrics",
                          description="Get lyrics for a song (or the currently playing track).")
    @app_commands.describe(query="Song name (e.g. 'Never Gonna Give You Up' or 'Rick Astley Never')")
    async def lyrics(self, interaction: discord.Interaction, query: str = None):
        await interaction.response.defer()

        # If no query, try to get current playing track
        if not query:
            from cogs.music.player import Music
            music_cog = self.bot.cogs.get("Music")
            if music_cog and interaction.guild_id in music_cog.states:
                state = music_cog.states[interaction.guild_id]
                if state.current:
                    query = f"{state.current.artist} {state.current.title}"
            if not query:
                await interaction.followup.send(
                    embed=error_embed("No Query",
                        "Nothing is playing. Provide a song name.\n"
                        "Example: `/lyrics Blinding Lights`"))
                return

        async with aiohttp.ClientSession() as session:
            # First search for the song
            try:
                search_url = SEARCH_API.format(query=query.replace(" ", "+"))
                async with session.get(search_url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status != 200:
                        raise Exception("Search failed")
                    data = await r.json()
                    if not data.get("data"):
                        await interaction.followup.send(
                            embed=error_embed("Not Found", f"No results for `{query}`."))
                        return
                    top = data["data"][0]
                    artist = top["artist"]["name"]
                    title  = top["title"]
            except Exception:
                # Try to split query into artist/title
                parts  = query.split(" ", 1)
                artist = parts[0]
                title  = parts[1] if len(parts) > 1 else query

            # Fetch lyrics
            try:
                lyrics_url = LYRICS_API.format(
                    artist=artist.replace("/", " "),
                    title=title.replace("/", " "))
                async with session.get(lyrics_url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status != 200:
                        await interaction.followup.send(
                            embed=error_embed("No Lyrics",
                                f"Couldn't find lyrics for **{title}** by **{artist}**.\n"
                                "Try a different search."))
                        return
                    data = await r.json()
                    lyrics = data.get("lyrics", "")
            except Exception as e:
                await interaction.followup.send(
                    embed=error_embed("API Error", f"Lyrics service unavailable. Try again later."))
                return

        if not lyrics:
            await interaction.followup.send(
                embed=error_embed("No Lyrics", f"No lyrics available for **{title}**."))
            return

        # Split into chunks of 1800 chars for embed limits
        chunks = []
        while len(lyrics) > 0:
            if len(lyrics) <= 1800:
                chunks.append(lyrics)
                break
            split = lyrics[:1800].rfind("\n")
            if split == -1: split = 1800
            chunks.append(lyrics[:split])
            lyrics = lyrics[split:].lstrip("\n")

        for i, chunk in enumerate(chunks[:3]):  # max 3 pages
            embed = discord.Embed(
                title=f"🎵 {title}" + (f" (page {i+1}/{min(len(chunks),3)})" if len(chunks) > 1 else ""),
                description=chunk,
                color=config.Colors.MUSIC)
            embed.set_author(name=f"by {artist}")
            embed.set_footer(text=f"Lyrics via lyrics.ovh • {config.FOOTER_TEXT}")
            if i == 0:
                await interaction.followup.send(embed=embed)
            else:
                await interaction.channel.send(embed=embed)

        if len(chunks) > 3:
            await interaction.channel.send(
                f"*(Lyrics too long — showing first 3 pages of {len(chunks)})*",
                delete_after=10)


async def setup(bot): await bot.add_cog(Lyrics(bot))
