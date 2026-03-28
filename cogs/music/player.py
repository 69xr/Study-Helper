"""
cogs/music/player.py
Improved music system with source-aware resolution for YouTube, Spotify,
and SoundCloud plus more reliable playback startup.
"""
import discord, asyncio, re, random, time
from discord import app_commands
from discord.ext import commands
from collections import deque
from urllib.parse import urlparse
import config
from utils.helpers import music_embed, error_embed, success_embed

try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False

try:
    import nacl
    NACL_AVAILABLE = True
except ImportError:
    NACL_AVAILABLE = False

# ─────────────────────────────────────────────────────────────
#  yt-dlp options — tuned for reliable streaming
# ─────────────────────────────────────────────────────────────
YDL_BASE = {
    "format":            "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best",
    "quiet":             True,
    "no_warnings":       True,
    "default_search":    "ytsearch",
    "source_address":    "0.0.0.0",
    "noplaylist":        False,
    "extract_flat":      "in_playlist",
    "ignoreerrors":      True,
    "socket_timeout":    15,
    "retries":           3,
}

YDL_SINGLE = {
    **YDL_BASE,
    "noplaylist":   True,
    "extract_flat": False,
}

FFMPEG_OPTS = {
    "before_options": (
        "-reconnect 1 -reconnect_streamed 1 "
        "-reconnect_delay_max 5 -nostdin"
    ),
    "options": "-vn",
}

RE_SPOTIFY_TRACK    = re.compile(r"open\.spotify\.com/track/([A-Za-z0-9]+)")
RE_SPOTIFY_PLAYLIST = re.compile(r"open\.spotify\.com/playlist/([A-Za-z0-9]+)")
RE_SPOTIFY_ALBUM    = re.compile(r"open\.spotify\.com/album/([A-Za-z0-9]+)")
RE_YT_URL           = re.compile(r"(youtube\.com|youtu\.be)")
RE_SOUNDCLOUD_URL   = re.compile(r"(soundcloud\.com|snd\.sc)")


def fmt_time(seconds) -> str:
    if not seconds or seconds < 0: return "0:00"
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def progress_bar(current: int, total: int, length: int = 18) -> str:
    if not total or total <= 0: return "▬" * length
    pct    = min(1.0, current / total)
    filled = int(pct * length)
    return "▬" * filled + "🔘" + "▬" * max(0, length - filled - 1)

def source_emoji(extractor: str) -> str:
    e = (extractor or "").lower()
    if "youtube" in e:    return "🎬"
    if "spotify" in e:    return "🟢"
    if "soundcloud" in e: return "🔶"
    return "🎵"


class Track:
    __slots__ = ("url", "page_url", "stream", "title", "artist",
                 "duration", "thumbnail", "requester", "extractor", "search_query")

    def __init__(self, data: dict, requester: discord.Member, search_query: str = ""):
        self.page_url  = data.get("webpage_url") or data.get("original_url") or ""
        self.url       = self.page_url or data.get("url", "")
        self.stream    = data.get("url", "")
        self.title     = data.get("title") or "Unknown Title"
        self.artist    = (data.get("uploader") or data.get("artist") or
                          data.get("channel") or "Unknown Artist")
        self.duration  = data.get("duration") or 0
        self.thumbnail = data.get("thumbnail") or ""
        self.requester = requester
        self.extractor = data.get("extractor_key") or data.get("extractor") or "YouTube"
        self.search_query = search_query

    @property
    def duration_str(self) -> str:
        return fmt_time(self.duration)

    @property
    def display(self) -> str:
        emoji = source_emoji(self.extractor)
        return f"{emoji} [{self.title}]({self.url})" if self.url else f"{emoji} {self.title}"


class MusicState:
    def __init__(self):
        self.queue:          deque[Track]           = deque()
        self.current:        Track | None           = None
        self.vc:             discord.VoiceClient | None = None
        self.loop:           bool                   = False
        self.loop_queue:     bool                   = False
        self.shuffle:        bool                   = False
        self.volume:         float                  = 0.5
        self.started_at:     float                  = 0.0
        self.pause_start:    float                  = 0.0
        self.paused_elapsed: float                  = 0.0
        self.np_message:     discord.Message | None = None
        self.text_channel:   discord.TextChannel | None = None

    @property
    def position(self) -> int:
        if self.started_at <= 0: return 0
        if self.pause_start > 0:
            return int(self.pause_start - self.started_at - self.paused_elapsed)
        return int(time.monotonic() - self.started_at - self.paused_elapsed)

    def is_playing(self) -> bool:
        return self.vc is not None and self.vc.is_playing()

    def is_paused(self) -> bool:
        return self.vc is not None and self.vc.is_paused()

    def on_pause(self):
        if self.pause_start == 0:
            self.pause_start = time.monotonic()

    def on_resume(self):
        if self.pause_start > 0:
            self.paused_elapsed += time.monotonic() - self.pause_start
            self.pause_start = 0

    def reset_timing(self):
        self.started_at      = time.monotonic()
        self.pause_start     = 0
        self.paused_elapsed  = 0


def _build_queue_embed(state: MusicState, guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(title="📋 Queue", color=config.Colors.MUSIC)
    if state.current:
        pos = state.position
        bar = progress_bar(pos, state.current.duration)
        embed.add_field(
            name="▶ Now Playing",
            value=(f"{state.current.display}\n"
                   f"by **{state.current.artist}**\n"
                   f"`{fmt_time(pos)}` {bar} `{state.current.duration_str}`"),
            inline=False)
    if state.queue:
        total = sum(t.duration or 0 for t in state.queue)
        lines = []
        for i, t in enumerate(list(state.queue)[:15], 1):
            lines.append(f"`{i}.` {t.display} `{t.duration_str}` — {t.requester.mention}")
        if len(state.queue) > 15:
            lines.append(f"*…and {len(state.queue)-15} more tracks*")
        embed.add_field(
            name=f"Up Next — {len(state.queue)} tracks • {fmt_time(total)}",
            value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Queue", value="Empty! Use `/play` to add tracks.", inline=False)
    flags = []
    if state.loop:       flags.append("🔂 Track Loop")
    if state.loop_queue: flags.append("🔁 Queue Loop")
    if state.shuffle:    flags.append("🔀 Shuffle")
    if flags: embed.set_footer(text="  •  ".join(flags))
    return embed


class NowPlayingView(discord.ui.View):
    def __init__(self, cog: "Music", guild_id: int):
        super().__init__(timeout=None)
        self.cog      = cog
        self.guild_id = guild_id
        self._sync_styles()

    def _state(self) -> MusicState | None:
        return self.cog.states.get(self.guild_id)

    def _sync_styles(self):
        state = self._state()
        for child in self.children:
            if not isinstance(child, discord.ui.Button): continue
            cid = child.custom_id or ""
            if "loop_track" in cid:
                child.style = discord.ButtonStyle.success if (state and state.loop) else discord.ButtonStyle.secondary
            elif "loop_queue" in cid:
                child.style = discord.ButtonStyle.success if (state and state.loop_queue) else discord.ButtonStyle.secondary
            elif "shuffle" in cid:
                child.style = discord.ButtonStyle.success if (state and state.shuffle) else discord.ButtonStyle.secondary

    # ── Row 0: main transport ──────────────────────────────
    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=0, custom_id="np_prev")
    async def prev_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        state = self._state()
        if not state or not state.vc: return await interaction.response.defer()
        # Restart current track by stopping (loop will replay it)
        old_loop   = state.loop
        state.loop = True
        state.vc.stop()
        state.loop = old_loop
        await interaction.response.defer()

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.primary, row=0, custom_id="np_pause")
    async def pause_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        state = self._state()
        if not state or not state.vc: return await interaction.response.defer()
        if state.vc.is_playing():
            state.vc.pause(); state.on_pause()
            btn.emoji = discord.PartialEmoji.from_str("▶️")
        elif state.vc.is_paused():
            state.vc.resume(); state.on_resume()
            btn.emoji = discord.PartialEmoji.from_str("⏸️")
        await interaction.response.edit_message(view=self)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.primary, row=0, custom_id="np_skip")
    async def skip_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        state = self._state()
        if not state or not state.vc: return await interaction.response.defer()
        state.loop = False
        state.vc.stop()
        await interaction.response.defer()

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, row=0, custom_id="np_vdown")
    async def vol_down_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        state = self._state()
        if not state: return await interaction.response.defer()
        state.volume = max(0.0, round(state.volume - 0.1, 2))
        if state.vc and state.vc.source: state.vc.source.volume = state.volume
        await interaction.response.send_message(
            embed=success_embed("🔉 Volume", f"**{int(state.volume*100)}%**"),
            ephemeral=True, delete_after=3)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, row=0, custom_id="np_vup")
    async def vol_up_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        state = self._state()
        if not state: return await interaction.response.defer()
        state.volume = min(1.5, round(state.volume + 0.1, 2))
        if state.vc and state.vc.source: state.vc.source.volume = state.volume
        await interaction.response.send_message(
            embed=success_embed("🔊 Volume", f"**{int(state.volume*100)}%**"),
            ephemeral=True, delete_after=3)

    # ── Row 1: modes + stop + queue ───────────────────────
    @discord.ui.button(emoji="🔂", style=discord.ButtonStyle.secondary, row=1, custom_id="np_loop_track")
    async def loop_track_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        state = self._state()
        if not state: return await interaction.response.defer()
        state.loop = not state.loop
        if state.loop: state.loop_queue = False
        self._sync_styles()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            embed=success_embed("🔂 Track Loop", "Enabled ✅" if state.loop else "Disabled ❌"),
            ephemeral=True, delete_after=3)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, row=1, custom_id="np_loop_queue")
    async def loop_queue_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        state = self._state()
        if not state: return await interaction.response.defer()
        state.loop_queue = not state.loop_queue
        if state.loop_queue: state.loop = False
        self._sync_styles()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            embed=success_embed("🔁 Queue Loop", "Enabled ✅" if state.loop_queue else "Disabled ❌"),
            ephemeral=True, delete_after=3)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=1, custom_id="np_shuffle")
    async def shuffle_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        state = self._state()
        if not state: return await interaction.response.defer()
        state.shuffle = not state.shuffle
        if state.shuffle:
            q = list(state.queue); random.shuffle(q); state.queue = deque(q)
        self._sync_styles()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            embed=success_embed("🔀 Shuffle", "Enabled ✅" if state.shuffle else "Disabled ❌"),
            ephemeral=True, delete_after=3)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=1, custom_id="np_stop")
    async def stop_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        state = self._state()
        if not state or not state.vc: return await interaction.response.defer()
        state.queue.clear(); state.loop = state.loop_queue = False; state.current = None
        if state.vc.is_playing() or state.vc.is_paused(): state.vc.stop()
        await state.vc.disconnect(); state.vc = None
        try:
            await interaction.response.edit_message(
                embed=discord.Embed(description="⏹️ **Stopped** — queue cleared.", color=discord.Color.red()),
                view=None)
        except Exception:
            await interaction.response.defer()

    @discord.ui.button(emoji="📋", style=discord.ButtonStyle.secondary, row=1, custom_id="np_queue")
    async def queue_btn(self, interaction: discord.Interaction, btn: discord.ui.Button):
        state = self._state()
        embed = _build_queue_embed(state, interaction.guild) if state else discord.Embed(description="No queue.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self.states: dict[int, MusicState] = {}

    def get_state(self, guild_id: int) -> MusicState:
        if guild_id not in self.states:
            self.states[guild_id] = MusicState()
        return self.states[guild_id]

    def _looks_like_url(self, query: str) -> bool:
        try:
            parsed = urlparse(query)
        except Exception:
            return False
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _search_query_for_source(self, query: str) -> str:
        query = query.strip()
        if query.lower().startswith("sc:"):
            return f"scsearch1:{query[3:].strip()}"
        if query.lower().startswith("yt:"):
            return f"ytsearch1:{query[3:].strip()}"
        if RE_SOUNDCLOUD_URL.search(query):
            return query
        if self._looks_like_url(query):
            return query
        return f"ytsearch1:{query}"

    # ── Spotify helpers ────────────────────────────────────
    def _spotify_track_query(self, url: str) -> str:
        try:
            with yt_dlp.YoutubeDL({**YDL_SINGLE, "quiet": True}) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    title  = info.get("title", "")
                    artist = info.get("artist") or info.get("uploader") or ""
                    if title:
                        return f"ytsearch1:{artist} {title}".strip()
        except Exception:
            pass
        return f"ytsearch1:{url}"

    def _spotify_playlist_queries(self, url: str) -> list[str]:
        queries = []
        try:
            with yt_dlp.YoutubeDL({**YDL_BASE, "extract_flat": True, "quiet": True}) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and "entries" in info:
                    for entry in info["entries"][:config.MAX_QUEUE_SIZE]:
                        if not entry: continue
                        title  = entry.get("title", "")
                        artist = entry.get("artist") or entry.get("uploader") or ""
                        if title:
                            queries.append(f"ytsearch:{artist} {title}".strip())
        except Exception:
            pass
        return queries or [url]

    # ── Core fetch ─────────────────────────────────────────
    async def fetch_tracks(self, query: str, requester: discord.Member) -> list[Track] | str:
        if not YTDLP_AVAILABLE:
            return []

        loop = asyncio.get_event_loop()

        if RE_SPOTIFY_TRACK.search(query):
            yt_query = await loop.run_in_executor(None, self._spotify_track_query, query)
            return await loop.run_in_executor(None, self._fetch_single, yt_query, requester)

        if RE_SPOTIFY_PLAYLIST.search(query) or RE_SPOTIFY_ALBUM.search(query):
            queries = await loop.run_in_executor(None, self._spotify_playlist_queries, query)
            return await self._fetch_many_queries(queries, requester)

        if (RE_YT_URL.search(query) and "list=" in query) or (RE_SOUNDCLOUD_URL.search(query) and "/sets/" in query):
            return await loop.run_in_executor(None, self._fetch_playlist, query, requester)

        query = self._search_query_for_source(query)
        return await loop.run_in_executor(None, self._fetch_single, query, requester)

    async def _fetch_many_queries(self, queries: list[str], requester: discord.Member) -> list[Track]:
        if not queries:
            return []

        sem = asyncio.Semaphore(5)

        async def runner(q: str):
            async with sem:
                return await asyncio.get_event_loop().run_in_executor(None, self._fetch_single, q, requester)

        results = await asyncio.gather(*(runner(q) for q in queries[:config.MAX_QUEUE_SIZE]), return_exceptions=True)
        tracks: list[Track] = []
        for res in results:
            if isinstance(res, list):
                tracks.extend(res)
        return tracks

    def _fetch_single(self, query: str, requester: discord.Member) -> list[Track] | str:
        try:
            with yt_dlp.YoutubeDL(YDL_SINGLE) as ydl:
                info = ydl.extract_info(query, download=False)
                if not info:
                    return []
                if "entries" in info:
                    entries = [e for e in info["entries"] if e]
                    if not entries: return []
                    info = entries[0]
                    url  = info.get("webpage_url") or info.get("url", "")
                    if url:
                        try: info = ydl.extract_info(url, download=False) or info
                        except Exception: pass
                return [Track(info, requester, search_query=query)]
        except Exception as e:
            if "drm" in str(e).lower(): return "drm"
            return []

    def _fetch_playlist(self, url: str, requester: discord.Member) -> list[Track]:
        tracks = []
        try:
            with yt_dlp.YoutubeDL({**YDL_BASE, "extract_flat": True}) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info or "entries" not in info: return []
                entries = [e for e in info["entries"] if e][:config.MAX_QUEUE_SIZE]
            with yt_dlp.YoutubeDL(YDL_SINGLE) as ydl:
                for entry in entries:
                    try:
                        eurl = entry.get("webpage_url") or entry.get("url", "")
                        if not eurl: continue
                        full = ydl.extract_info(eurl, download=False)
                        if full: tracks.append(Track(full, requester, search_query=eurl))
                    except Exception:
                        continue
        except Exception:
            pass
        return tracks

    def _refresh_track_stream(self, track: Track) -> str | None:
        query = track.page_url or track.url or track.search_query
        if not query:
            return track.stream or None
        try:
            with yt_dlp.YoutubeDL(YDL_SINGLE) as ydl:
                info = ydl.extract_info(query, download=False)
                if info and "entries" in info:
                    entries = [e for e in info["entries"] if e]
                    if entries:
                        info = entries[0]
                if not info:
                    return None
                track.page_url = info.get("webpage_url") or track.page_url
                track.url = track.page_url or track.url
                track.stream = info.get("url") or track.stream
                track.title = info.get("title") or track.title
                track.artist = info.get("uploader") or info.get("artist") or info.get("channel") or track.artist
                track.duration = info.get("duration") or track.duration
                track.thumbnail = info.get("thumbnail") or track.thumbnail
                track.extractor = info.get("extractor_key") or info.get("extractor") or track.extractor
                return track.stream or None
        except Exception:
            return track.stream or None
        return None

    # ── Playback engine ────────────────────────────────────
    async def play_next(self, guild_id: int):
        state = self.get_state(guild_id)
        if not state.vc or not state.vc.is_connected():
            return

        if state.loop and state.current:
            track = state.current
        elif state.queue:
            track = state.queue.popleft()
            if state.loop_queue and state.current:
                state.queue.append(state.current)
        else:
            state.current = None
            if state.np_message:
                try:
                    await state.np_message.edit(
                        embed=discord.Embed(
                            description="✅ **Queue finished.** Add more with `/play`!",
                            color=config.Colors.MUSIC),
                        view=None)
                except Exception:
                    pass
            return

        state.current = track
        state.reset_timing()

        try:
            refreshed = await asyncio.get_event_loop().run_in_executor(None, self._refresh_track_stream, track)
            if refreshed:
                track.stream = refreshed
            src = discord.FFmpegPCMAudio(
                track.stream, executable=config.FFMPEG_PATH, **FFMPEG_OPTS)
            src = discord.PCMVolumeTransformer(src, volume=state.volume)

            def _after(err):
                if err: print(f"[Music] {err}")
                asyncio.run_coroutine_threadsafe(
                    self.play_next(guild_id), self.bot.loop)

            state.vc.play(src, after=_after)
            await self._send_now_playing(state, track)

        except Exception as e:
            ch = state.text_channel
            if ch:
                await ch.send(embed=error_embed("Playback Error",
                    f"Skipping **{track.title}**.\n`{e}`"), delete_after=8)
            await self.play_next(guild_id)

    async def _send_now_playing(self, state: MusicState, track: Track):
        if state.np_message:
            try: await state.np_message.delete()
            except Exception: pass
            state.np_message = None

        bar  = progress_bar(0, track.duration)
        desc = (f"**{track.title}**\nby **{track.artist}**\n\n"
                f"`0:00` {bar} `{track.duration_str}`")

        embed = discord.Embed(description=desc, color=config.Colors.MUSIC)
        embed.set_author(name="▶  Now Playing")
        if track.thumbnail:
            embed.set_image(url=track.thumbnail)

        embed.add_field(name="⏱ Duration",  value=f"`{track.duration_str}`",      inline=True)
        embed.add_field(name="📋 Queue",     value=f"`{len(state.queue)}` tracks", inline=True)
        embed.add_field(name="🔊 Volume",    value=f"`{int(state.volume*100)}%`",  inline=True)
        embed.add_field(name="👤 Requested", value=track.requester.mention,        inline=True)
        embed.add_field(name=f"{source_emoji(track.extractor)} Source",
                        value=f"[Link]({track.url})" if track.url else "—",        inline=True)

        flags = []
        if state.loop:       flags.append("🔂 Track")
        if state.loop_queue: flags.append("🔁 Queue")
        if state.shuffle:    flags.append("🔀 Shuffle")
        if flags: embed.add_field(name="⚙️ Modes", value="  ".join(flags), inline=True)

        embed.set_footer(text=config.FOOTER_TEXT)

        view = NowPlayingView(self, state.vc.guild.id if state.vc else 0)
        if state.text_channel:
            try:
                state.np_message = await state.text_channel.send(embed=embed, view=view)
            except Exception:
                state.np_message = None

    async def _connect(self, interaction: discord.Interaction) -> discord.VoiceClient | None:
        if not interaction.user.voice:
            await interaction.followup.send(
                embed=error_embed("Not in Voice", "Join a voice channel first."), ephemeral=True)
            return None

        state = self.get_state(interaction.guild_id)
        vc    = interaction.user.voice.channel

        if state.vc and state.vc.is_connected():
            if state.vc.channel.id != vc.id:
                await state.vc.move_to(vc)
            return state.vc

        try:
            state.vc = await vc.connect(timeout=30.0, reconnect=True,
                                        self_deaf=True, self_mute=False)
            return state.vc
        except discord.ClientException:
            existing = discord.utils.get(self.bot.voice_clients, guild=interaction.guild)
            if existing:
                await existing.move_to(vc)
                state.vc = existing
                return state.vc
            await interaction.followup.send(
                embed=error_embed("Voice Error", "Couldn't connect."), ephemeral=True)
            return None
        except asyncio.TimeoutError:
            await interaction.followup.send(
                embed=error_embed("Timed Out",
                    "Voice servers didn't respond.\nCheck UDP 50000–65535 is open."),
                ephemeral=True)
            return None
        except Exception as e:
            msg = str(e)
            hint = ("Run `pip install --force-reinstall PyNaCl` and restart."
                    if "4017" in msg or "encryption" in msg.lower() else msg)
            await interaction.followup.send(
                embed=error_embed("Voice Error", hint), ephemeral=True)
            return None

    # ── Slash commands ─────────────────────────────────────
    @app_commands.command(name="play",
        description="Queue music from search, YouTube, Spotify, or SoundCloud.")
    @app_commands.describe(query="Song name, YouTube URL, Spotify link, SoundCloud link, or sc:/yt: search")
    async def play(self, interaction: discord.Interaction, query: str):
        if not NACL_AVAILABLE:
            return await interaction.response.send_message(
                embed=error_embed("PyNaCl Missing", "`pip install PyNaCl`"), ephemeral=True)
        if not YTDLP_AVAILABLE:
            return await interaction.response.send_message(
                embed=error_embed("yt-dlp Missing", "`pip install yt-dlp`"), ephemeral=True)

        await interaction.response.defer()
        state              = self.get_state(interaction.guild_id)
        state.text_channel = interaction.channel

        vc = await self._connect(interaction)
        if not vc:
            return

        is_spotify  = bool(RE_SPOTIFY_TRACK.search(query) or
                           RE_SPOTIFY_PLAYLIST.search(query) or
                           RE_SPOTIFY_ALBUM.search(query))
        is_soundcloud = bool(RE_SOUNDCLOUD_URL.search(query) or query.lower().startswith("sc:"))
        is_playlist = (
            "list=" in query
            or RE_SPOTIFY_PLAYLIST.search(query)
            or RE_SPOTIFY_ALBUM.search(query)
            or (RE_SOUNDCLOUD_URL.search(query) and "/sets/" in query)
        )

        hint = ("🟢 Resolving Spotify → YouTube…" if is_spotify
                else "🟠 Resolving SoundCloud source…" if is_soundcloud
                else "📋 Loading playlist…" if is_playlist
                else f"🔍 Searching for `{query}`…")
        loading = await interaction.followup.send(embed=music_embed("⏳ Please wait", hint))

        tracks = await self.fetch_tracks(query, interaction.user)

        if tracks == "drm":
            return await loading.edit(embed=error_embed("DRM Protected",
                "Can't stream this — it's DRM-protected.\n"
                "Try searching by song name instead."))

        if not tracks:
            return await loading.edit(embed=error_embed("Not Found",
                f"Couldn't find anything for:\n`{query}`\n\n"
                "• Check the URL is public\n"
                "• Try a plain search: `Artist Song Title`\n"
                "• For SoundCloud search use `sc: artist track`"))

        for t in tracks:
            state.queue.append(t)

        if len(tracks) == 1:
            t = tracks[0]
            await loading.edit(embed=music_embed(
                "✅ Added to Queue",
                f"**{t.title}**\nby **{t.artist}** • `{t.duration_str}`",
                thumbnail=t.thumbnail))
        else:
            total = fmt_time(sum(t.duration or 0 for t in tracks))
            await loading.edit(embed=music_embed(
                "✅ Playlist Queued",
                f"Added **{len(tracks)} tracks** • Total: `{total}`",
                thumbnail=tracks[0].thumbnail))

        if not state.is_playing() and not state.is_paused():
            await self.play_next(interaction.guild_id)

    @app_commands.command(name="pause", description="Pause the current track.")
    async def pause(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if not state.vc or not state.vc.is_playing():
            return await interaction.response.send_message(
                embed=error_embed("Nothing Playing"), ephemeral=True)
        state.vc.pause(); state.on_pause()
        await interaction.response.send_message(embed=success_embed("⏸️ Paused"), ephemeral=True)

    @app_commands.command(name="resume", description="Resume the paused track.")
    async def resume(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if not state.vc or not state.vc.is_paused():
            return await interaction.response.send_message(
                embed=error_embed("Not Paused"), ephemeral=True)
        state.vc.resume(); state.on_resume()
        await interaction.response.send_message(embed=success_embed("▶️ Resumed"), ephemeral=True)

    @app_commands.command(name="skip", description="Skip the current track.")
    async def skip(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if not state.vc or not (state.vc.is_playing() or state.vc.is_paused()):
            return await interaction.response.send_message(
                embed=error_embed("Nothing Playing"), ephemeral=True)
        title = state.current.title if state.current else "Track"
        state.loop = False; state.vc.stop()
        await interaction.response.send_message(
            embed=success_embed("⏭️ Skipped", f"Skipped **{title}**."))

    @app_commands.command(name="stop", description="Stop playback, clear the queue, and disconnect.")
    async def stop(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if not state.vc:
            return await interaction.response.send_message(
                embed=error_embed("Not Connected"), ephemeral=True)
        state.queue.clear(); state.loop = state.loop_queue = False; state.current = None
        if state.vc.is_playing() or state.vc.is_paused(): state.vc.stop()
        await state.vc.disconnect(); state.vc = None
        if state.np_message:
            try: await state.np_message.edit(view=None)
            except Exception: pass
            state.np_message = None
        await interaction.response.send_message(
            embed=success_embed("⏹️ Stopped", "Disconnected and cleared the queue."))

    @app_commands.command(name="queue", description="Show the current music queue.")
    async def queue_cmd(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        await interaction.response.send_message(
            embed=_build_queue_embed(state, interaction.guild))

    @app_commands.command(name="nowplaying", description="Show the track that is playing right now.")
    async def nowplaying(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if not state.current:
            return await interaction.response.send_message(
                embed=error_embed("Nothing Playing"), ephemeral=True)
        t   = state.current
        pos = state.position
        embed = discord.Embed(
            description=(f"**{t.title}**\nby **{t.artist}**\n\n"
                         f"`{fmt_time(pos)}` {progress_bar(pos, t.duration)} `{t.duration_str}`"),
            color=config.Colors.MUSIC)
        embed.set_author(name="▶  Now Playing")
        if t.thumbnail: embed.set_thumbnail(url=t.thumbnail)
        embed.add_field(name="Requested by", value=t.requester.mention,       inline=True)
        embed.add_field(name="Volume",        value=f"`{int(state.volume*100)}%`", inline=True)
        embed.add_field(name="Queue",         value=f"`{len(state.queue)}` left",  inline=True)
        embed.set_footer(text=config.FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="volume", description="Set playback volume from 0 to 150 percent.")
    @app_commands.describe(level="Volume 0–150")
    async def volume(self, interaction: discord.Interaction,
                     level: app_commands.Range[int, 0, 150] = 50):
        state = self.get_state(interaction.guild_id)
        state.volume = level / 100
        if state.vc and state.vc.source: state.vc.source.volume = state.volume
        await interaction.response.send_message(
            embed=success_embed("🔊 Volume", f"Set to **{level}%**"), ephemeral=True)

    @app_commands.command(name="loop", description="Choose track loop, queue loop, or loop off.")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Track",  value="track"),
        app_commands.Choice(name="Queue",  value="queue"),
        app_commands.Choice(name="Off",    value="off"),
    ])
    async def loop_cmd(self, interaction: discord.Interaction, mode: str = "track"):
        state = self.get_state(interaction.guild_id)
        state.loop       = mode == "track"
        state.loop_queue = mode == "queue"
        labels = {"track": "🔂 Track loop ON", "queue": "🔁 Queue loop ON", "off": "Loop OFF"}
        await interaction.response.send_message(
            embed=success_embed(labels[mode]), ephemeral=True)

    @app_commands.command(name="shuffle", description="Toggle shuffle for the queued tracks.")
    async def shuffle_cmd(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        state.shuffle = not state.shuffle
        if state.shuffle:
            q = list(state.queue); random.shuffle(q); state.queue = deque(q)
        await interaction.response.send_message(
            embed=success_embed("🔀 Shuffle",
                "Enabled ✅ — queue randomised." if state.shuffle else "Disabled ❌"),
            ephemeral=True)

    @app_commands.command(name="remove", description="Remove one queued track by position.")
    @app_commands.describe(position="Position in queue (1 = next up)")
    async def remove(self, interaction: discord.Interaction,
                     position: app_commands.Range[int, 1, 500]):
        state = self.get_state(interaction.guild_id)
        q = list(state.queue)
        if position > len(q):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Position", f"Queue only has {len(q)} tracks."),
                ephemeral=True)
        removed = q.pop(position - 1); state.queue = deque(q)
        await interaction.response.send_message(
            embed=success_embed("🗑️ Removed",
                f"Removed **{removed.title}** from position {position}."), ephemeral=True)

    @app_commands.command(name="clearqueue", description="Clear the queue while keeping the current track.")
    async def clear(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        count = len(state.queue); state.queue.clear()
        await interaction.response.send_message(
            embed=success_embed("🗑️ Cleared", f"Removed **{count}** tracks."), ephemeral=True)

    @app_commands.command(name="join", description="Join your current voice channel.")
    async def join(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        vc = await self._connect(interaction)
        if vc:
            await interaction.followup.send(
                embed=success_embed("🎵 Joined", f"Connected to **{vc.channel.name}**."),
                ephemeral=True)

    @app_commands.command(name="leave", description="Leave the active voice channel.")
    async def leave(self, interaction: discord.Interaction):
        state = self.get_state(interaction.guild_id)
        if not state.vc:
            return await interaction.response.send_message(
                embed=error_embed("Not Connected"), ephemeral=True)
        state.queue.clear(); state.current = None
        if state.vc.is_playing() or state.vc.is_paused(): state.vc.stop()
        await state.vc.disconnect(); state.vc = None
        if state.np_message:
            try: await state.np_message.edit(view=None)
            except Exception: pass
            state.np_message = None
        await interaction.response.send_message(
            embed=success_embed("👋 Left", "Disconnected."), ephemeral=True)

    async def _auto_leave(self, guild_id: int, state: MusicState):
        """Wait 30s then leave if still empty."""
        await asyncio.sleep(30)
        if not state.vc:
            return
        non_bot = [m for m in state.vc.channel.members if not m.bot]
        if not non_bot:
            state.queue.clear()
            state.current = None
            if state.vc.is_playing() or state.vc.is_paused():
                state.vc.stop()
            try:
                await state.vc.disconnect()
            except Exception:
                pass
            state.vc = None
            if state.np_message:
                try:
                    await state.np_message.edit(
                        embed=discord.Embed(
                            description="👋 Left — everyone left the channel.",
                            color=discord.Color.greyple()),
                        view=None)
                except Exception:
                    pass
                state.np_message = None

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member,
                                    before: discord.VoiceState,
                                    after: discord.VoiceState):
        if member.bot: return
        state = self.states.get(member.guild.id)
        if not state or not state.vc: return
        vc      = state.vc
        non_bot = [m for m in vc.channel.members if not m.bot]
        if not non_bot:
            asyncio.create_task(self._auto_leave(member.guild.id, state))


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
