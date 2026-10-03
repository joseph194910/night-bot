"""
Reaction Role Embed Bot  (discord.py 2.x)
-----------------------------------------
Slash commands (Administrator only):
    /setup_game_roles   -> posts the styled embed + adds the reaction emojis
    /add_role_emoji     -> links a new emoji to a Role ID (live-updates the panel)
    /remove_role_emoji  -> removes an emoji <-> role mapping (live-updates the panel)

Roles are granted/removed with RAW reaction events, so they keep working on
old / uncached messages after the bot restarts.

Install:  pip install -U discord.py
Run:      python main.py
"""

import json
import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

# =============================================================================
#  CONFIG  -  edit this section manually
# =============================================================================
CONFIG = {
    # --- Default emoji -> Role ID mapping ------------------------------------
    # Unicode emoji:  "🎮": 123456789012345678
    # Custom emoji:   "<:valorant:123456789012345678>": 123456789012345678
    #                 (animated ones look like <a:name:id>)
    # NOTE: these are only used the FIRST time the bot runs. After you use
    # /add_role_emoji or /remove_role_emoji, the saved data file takes over.
    "EMOJI_ROLES": {
        "🎮": 111111111111111111,  # <- replace with a real Role ID
        "⚔️": 222222222222222222,  # <- replace with a real Role ID
        "🏎️": 333333333333333333,  # <- replace with a real Role ID
    },

    # --- Embed look ----------------------------------------------------------
    "EMBED": {
        "title": "Choose Ur Fav : IN SERVER GAME",
        "color": 0x00E1FF,  # Cyan / light blue sidebar (#00E1FF)
        "thumbnail_url": "https://example.com/your-thumbnail.png",  # top-right image
        "banner_url": "https://example.com/your-claim-ur-roles-banner.png",  # bottom banner
        # Text shown above the emoji/role list (flexible text area)
        "header_text": "React below to **claim your game roles!**\n"
                       "Remove your reaction to give the role back.\n\n",
        # Shown when no emoji has been linked yet (placeholder)
        "empty_text": "*No roles linked yet.*\n"
                      "Use `/add_role_emoji` to add your emojis and game roles.",
        "footer_text": "Click an emoji to get your role",
    },

    # --- Storage file (keeps dynamic mappings + panel message IDs) -----------
    "DATA_FILE": "reaction_roles_data.json",
}

# =============================================================================
#  INTENTS
# =============================================================================
intents = discord.Intents.default()
intents.guilds = True            # guild / role / channel info
intents.members = True           # PRIVILEGED - needed to fetch members for role changes
intents.message_content = True   # PRIVILEGED - enable in the Developer Portal
intents.reactions = True         # reaction add/remove events

bot = commands.Bot(command_prefix="!", intents=intents)

# =============================================================================
#  DATA LAYER  (in-memory + JSON persistence)
# =============================================================================
# emoji_roles: { emoji_key: {"display": "<emoji as text>", "role_id": int} }
emoji_roles: dict[str, dict] = {}
# panels: [ {"guild_id": int, "channel_id": int, "message_id": int}, ... ]
panels: list[dict] = []


def emoji_key(emoji: discord.PartialEmoji) -> str:
    """Stable lookup key: ID for custom emojis, the character for unicode ones."""
    return str(emoji.id) if emoji.id else emoji.name


def parse_emoji(text: str) -> discord.PartialEmoji:
    """Turn user text ('🎮' or '<:name:id>') into a PartialEmoji."""
    return discord.PartialEmoji.from_str(text.strip())


def save_data() -> None:
    """Write mappings and panel messages to disk."""
    with open(CONFIG["DATA_FILE"], "w", encoding="utf-8") as f:
        json.dump({"emoji_roles": emoji_roles, "panels": panels}, f, indent=2, ensure_ascii=False)


def load_data() -> None:
    """Load saved data; fall back to CONFIG['EMOJI_ROLES'] on first run."""
    global emoji_roles, panels
    if os.path.exists(CONFIG["DATA_FILE"]):
        with open(CONFIG["DATA_FILE"], "r", encoding="utf-8") as f:
            data = json.load(f)
        emoji_roles = data.get("emoji_roles", {})
        panels = data.get("panels", [])
    else:
        # First run: build runtime mapping from the manual CONFIG dictionary
        for text, role_id in CONFIG["EMOJI_ROLES"].items():
            pe = parse_emoji(text)
            emoji_roles[emoji_key(pe)] = {"display": str(pe), "role_id": int(role_id)}
        save_data()


# =============================================================================
#  EMBED BUILDER
# =============================================================================
def build_embed() -> discord.Embed:
    """Builds the styled embed from CONFIG + the current emoji/role mapping."""
    cfg = CONFIG["EMBED"]

    if emoji_roles:
        lines = [f"{d['display']}  ➜  <@&{d['role_id']}>" for d in emoji_roles.values()]
        body = cfg["header_text"] + "\n".join(lines)
    else:
        body = cfg["header_text"] + cfg["empty_text"]

    embed = discord.Embed(title=cfg["title"], description=body, color=cfg["color"])
    if cfg["thumbnail_url"]:
        embed.set_thumbnail(url=cfg["thumbnail_url"])   # top-right
    if cfg["banner_url"]:
        embed.set_image(url=cfg["banner_url"])          # bottom banner ("CLAIM UR ROLES")
    if cfg["footer_text"]:
        embed.set_footer(text=cfg["footer_text"])
    return embed


async def refresh_panels(guild: discord.Guild) -> tuple[int, list[str]]:
    """
    Re-edit every saved panel in this guild so it matches the current mapping,
    and make sure every mapped emoji is present as a reaction.
    Returns (panels_updated, list_of_problems).
    """
    updated, problems = 0, []

    for panel in list(panels):
        if panel["guild_id"] != guild.id:
            continue
        try:
            channel = guild.get_channel(panel["channel_id"]) or await guild.fetch_channel(panel["channel_id"])
            message = await channel.fetch_message(panel["message_id"])
        except (discord.NotFound, discord.Forbidden):
            # Panel was deleted or is inaccessible -> forget it
            panels.remove(panel)
            continue

        await message.edit(embed=build_embed())

        for data in emoji_roles.values():
            try:
                await message.add_reaction(parse_emoji(data["display"]))
            except discord.HTTPException:
                problems.append(f"Could not react with {data['display']} (invalid emoji?)")
        updated += 1

    save_data()
    return updated, problems


# =============================================================================
#  EVENTS
# =============================================================================
@bot.event
async def setup_hook():
    """Runs once before the bot connects: load data and sync slash commands."""
    load_data()
    await bot.tree.sync()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"Loaded {len(emoji_roles)} emoji-role mappings, {len(panels)} panel(s).")


def is_panel_message(message_id: int) -> bool:
    return any(p["message_id"] == message_id for p in panels)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """Grant the role when someone reacts. Works for uncached / old messages."""
    if payload.guild_id is None or payload.user_id == bot.user.id:
        return
    if not is_panel_message(payload.message_id):
        return

    entry = emoji_roles.get(emoji_key(payload.emoji))
    if entry is None:
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    role = guild.get_role(entry["role_id"])
    if role is None:
        print(f"[WARN] Role {entry['role_id']} not found in guild {guild.id}")
        return

    # payload.member is provided on ADD events; fall back to a fetch just in case
    member = payload.member or guild.get_member(payload.user_id)
    if member is None:
        try:
            member = await guild.fetch_member(payload.user_id)
        except discord.NotFound:
            return

    try:
        await member.add_roles(role, reason="Reaction role: reaction added")
    except discord.Forbidden:
        print(f"[ERROR] Missing permission / hierarchy to give '{role.name}'")
    except discord.HTTPException as e:
        print(f"[ERROR] Failed to add role: {e}")


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    """Remove the role when someone un-reacts. Works for uncached / old messages."""
    if payload.guild_id is None or payload.user_id == bot.user.id:
        return
    if not is_panel_message(payload.message_id):
        return

    entry = emoji_roles.get(emoji_key(payload.emoji))
    if entry is None:
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    role = guild.get_role(entry["role_id"])
    if role is None:
        return

    # payload.member is NOT provided on REMOVE events -> must look the member up
    member = guild.get_member(payload.user_id)
    if member is None:
        try:
            member = await guild.fetch_member(payload.user_id)
        except discord.NotFound:
            return  # user left the server

    try:
        await member.remove_roles(role, reason="Reaction role: reaction removed")
    except discord.Forbidden:
        print(f"[ERROR] Missing permission / hierarchy to remove '{role.name}'")
    except discord.HTTPException as e:
        print(f"[ERROR] Failed to remove role: {e}")


# =============================================================================
#  SLASH COMMANDS  (Administrator only)
# =============================================================================
@bot.tree.command(name="setup_game_roles", description="Send the game role embed and add its reactions.")
@app_commands.describe(channel="Channel to post in (defaults to the current channel)")
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def setup_game_roles(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    target = channel or interaction.channel
    await interaction.response.defer(ephemeral=True)

    # Make sure the bot can actually do its job in that channel
    perms = target.permissions_for(interaction.guild.me)
    if not (perms.send_messages and perms.embed_links and perms.add_reactions and perms.read_message_history):
        await interaction.followup.send(
            f"❌ I need **Send Messages, Embed Links, Add Reactions, Read Message History** in {target.mention}.",
            ephemeral=True,
        )
        return

    message = await target.send(embed=build_embed())

    # Remember this message so the raw listeners know it is a role panel
    panels.append({"guild_id": interaction.guild.id, "channel_id": target.id, "message_id": message.id})
    save_data()

    problems = []
    for data in emoji_roles.values():
        try:
            await message.add_reaction(parse_emoji(data["display"]))
        except discord.HTTPException:
            problems.append(data["display"])

    note = f"✅ Panel posted in {target.mention}."
    if problems:
        note += f"\n⚠️ Couldn't add these reactions (invalid / inaccessible emoji): {' '.join(problems)}"
    await interaction.followup.send(note, ephemeral=True)


@bot.tree.command(name="add_role_emoji", description="Link a reaction emoji to a role.")
@app_commands.describe(
    emoji="The emoji (unicode or a custom server emoji)",
    role_id="The ID of the role to give (enable Developer Mode to copy it)",
)
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def add_role_emoji(interaction: discord.Interaction, emoji: str, role_id: str):
    # Role IDs are passed as text because Discord number options can't hold full snowflakes
    if not role_id.strip().isdigit():
        await interaction.response.send_message("❌ Role ID must be a number.", ephemeral=True)
        return

    role = interaction.guild.get_role(int(role_id))
    if role is None:
        await interaction.response.send_message("❌ No role with that ID exists in this server.", ephemeral=True)
        return
    if role.is_default() or role.managed:
        await interaction.response.send_message("❌ That role can't be assigned by a bot.", ephemeral=True)
        return
    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(
            f"❌ **{role.name}** is above my highest role. Move my role higher in Server Settings → Roles.",
            ephemeral=True,
        )
        return

    pe = parse_emoji(emoji)
    emoji_roles[emoji_key(pe)] = {"display": str(pe), "role_id": role.id}
    save_data()

    await interaction.response.defer(ephemeral=True)
    updated, problems = await refresh_panels(interaction.guild)

    msg = f"✅ Linked {pe} ➜ {role.mention}. Updated **{updated}** panel(s)."
    if problems:
        msg += "\n⚠️ " + "\n⚠️ ".join(problems)
    await interaction.followup.send(msg, ephemeral=True)


@bot.tree.command(name="remove_role_emoji", description="Remove an emoji-role link.")
@app_commands.describe(emoji="The emoji whose link should be removed")
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def remove_role_emoji(interaction: discord.Interaction, emoji: str):
    pe = parse_emoji(emoji)
    key = emoji_key(pe)

    if key not in emoji_roles:
        await interaction.response.send_message(f"❌ {pe} isn't linked to any role.", ephemeral=True)
        return

    del emoji_roles[key]
    save_data()

    await interaction.response.defer(ephemeral=True)

    # Update the embed text and clear that reaction from every panel in this guild
    for panel in panels:
        if panel["guild_id"] != interaction.guild.id:
            continue
        try:
            channel = interaction.guild.get_channel(panel["channel_id"]) or await interaction.guild.fetch_channel(panel["channel_id"])
            message = await channel.fetch_message(panel["message_id"])
            await message.clear_reaction(pe)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass  # reaction/message already gone or no permission; mapping is removed anyway

    updated, problems = await refresh_panels(interaction.guild)

    msg = f"🗑️ Removed {pe}. Updated **{updated}** panel(s).\n" \
          f"Members who already have the role keep it."
    if problems:
        msg += "\n⚠️ " + "\n⚠️ ".join(problems)
    await interaction.followup.send(msg, ephemeral=True)


# =============================================================================
#  RUN
# =============================================================================
bot.run("YOUR_BOT_TOKEN_HERE")
