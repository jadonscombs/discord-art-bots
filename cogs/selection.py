import discord
from discord.ext import commands, tasks
import emojis
from enum import Enum, auto
import argparse
import json
import os
import pickle
import sys
import traceback
from typing import Optional
from cogs.globalcog import GlobalCog
from utils.async_utils import react_success, react_fail


# (short?)hand for selection.py scopes
class RR_SCOPES(Enum):
    maps = 1
    links = 2
    all = 3

    @classmethod
    def has_value(cls, value):
        return value in cls.__members__


class ReactionRoleLinks:
    """
    Self-caching helper class for the <Selection> class.

    Stores message links.
    """

    def __init__(self):
        self.default_link = {}
        self.links = {}
        self.filename = "reaction_role_links.pickle"

    # dict overload for retrieving by key/index
    def __getitem__(self, key):
        return self.links[key]

    def __contains__(self, key):
        return key in self.links

    def add_link(self, gid, link: discord.Message, default: bool = False):
        entry = "{}-{}".format(link.channel.id, link.id)
        if default:
            self.default_link[gid] = entry

        else:
            if gid not in self.links:
                self.links[gid] = []
            if entry not in self.links[gid]:
                self.links[gid].insert(0, entry)

    def pop_link(self, gid, default: bool = False):
        if default:
            self.default_link[gid] = None
        else:
            try:
                self.links[gid].pop()
            except (IndexError, KeyError):
                pass

    def get_default_link(self, gid: str):
        if gid not in self.default_link:
            self.default_link[gid] = None

        return self.default_link[gid]

    def clear_default_link(self, gid, all: bool = False):
        if all:
            for k in self.default_link:
                self.default_link[k] = None
        else:
            self.default_link[gid] = None

    def link_exists(self, gid, channel_id, msg_id):
        """
        Return True if msg link with ID=<msg_id> exists in cache or default slot.
        """
        if gid in self.links or gid in self.default_link:
            entry = f"{channel_id}-{msg_id}"
            try:
                return entry in self.links[gid] or entry in self.default_link[gid]
            except KeyError:
                pass
            except:
                pass

        return False

    def save(self, path: str = None):
        if path:
            path = os.path.join(path, self.filename)
        else:
            path = self.filename

        s = {"default_link": self.default_link, "links": self.links}

        with open(path, "wb") as f:
            pickle.dump(s, f, protocol=pickle.HIGHEST_PROTOCOL)

    def load(self, path: str = None):
        if path:
            path = os.path.join(path, self.filename)
        else:
            path = self.filename

        if not os.path.isfile(path):
            return

        with open(path, "rb") as f:
            data = pickle.load(f)

        self.default_link = data["default_link"]
        self.links = data["links"]
        return self


class Selection(commands.Cog, GlobalCog):
    """
    Module (primarily) for Role Select and other interactive components.
    """

    def __init__(self, bot):
        self.bot = bot

        # rr_map[guild_id] entries form: <emoji_id> : <role_name>
        # NOTE:
        #   emoji is used as key so that multiple emojis can be
        #   mapped to the same role, for flexibility reasons and other cases
        self.rr_map = dict()

        self.rr_links = ReactionRoleLinks()
        self.filename = "role_emoji_mappings.pickle"

        # data loading operations
        self.load_rr_mappings()
        self.load_rr_links()

    # load reaction-role <emoji:role> mappings
    def load_rr_mappings(self, path: Optional[str] = None):
        if path:
            path = os.path.join(path, self.filename)
        else:
            path = self.filename

        try:
            if not os.path.isfile(path):
                return

            # using a temp var., so None is not assigned to
            # <self.rr_map> if exception occurs.
            with open(path, "rb") as f:
                _ = pickle.load(f)
            self.rr_map = _

        except:
            traceback.print_exc()

    # save reaction-role <emoji:role> mappings
    def save_rr_mappings(self, path: Optional[str] = None):
        if path:
            path = os.path.join(path, self.filename)
        else:
            path = self.filename

        with open(path, "wb") as f:
            pickle.dump(self.rr_map, f, protocol=pickle.HIGHEST_PROTOCOL)

    # load reaction-role message links (IDs at least)
    def load_rr_links(self):
        try:
            self.rr_links.load()
        except:
            traceback.print_exc()

    # save reaction-role message links (IDs at least)
    def save_rr_links(self):
        try:
            self.rr_links.save()
        except:
            traceback.print_exc()

    # helper method for role adding/removing
    async def role_action_helper(self, payload, action: str = "add"):
        """
        Helper method for the reaction add/remove listeners.

        <action> should be "add" or "remove".
        """
        # user must not be bot
        if payload.user_id == self.bot.user.id:
            return

        # action must be valid
        if action not in {"add", "remove"}:
            return

        # ensure "member" is accessible (normally payload.member is not
        # accessible if a "RawReactionActionRemove" event occurs)
        if action == "remove":
            guild = self.bot.get_guild(payload.guild_id)
            member = guild.get_member(payload.user_id)
        else:
            member = payload.member

        # if the reaction wasn't on a currently registered message link, ignore it
        if not self.rr_links.link_exists(
            payload.guild_id, payload.channel_id, payload.message_id
        ):
            return

        # transform emoji real quick
        emoji_str = str(list(emojis.get(f"{payload.emoji}"))[0])

        # otherwise, check reaction and attempt to give associated role (if any)
        if emoji_str in self.rr_map[payload.guild_id]:
            guild = self.bot.get_guild(payload.guild_id)
            role_name = self.rr_map[payload.guild_id][emoji_str]

            role = discord.utils.get(guild.roles, name=role_name)

            # ensure "adminstrator" permission is not present within role
            if role.permissions.administrator:
                return

            if action == "add":
                await member.add_roles(role)
            elif action == "remove":
                await member.remove_roles(role)

    # looping task: save links and mappings every X minutes
    @tasks.loop(minutes=5.0)
    async def save_links_and_mappings(self):
        self.rr_links.save()
        self.save_rr_mappings()

    # core logic for reaction-role + other user-interactive functionality
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """
        This listener allows members to "subscribe" to a role.
        """
        await self.role_action_helper(payload, action="add")

    # core logic for reaction-role + other user-interactive functionality
    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        """
        This listener compliments <on_raw_reaction_add()> so that users can "unsubscribe" from a target role.
        """
        await self.role_action_helper(payload, action="remove")

    # ("rr" is "reaction role")
    @commands.group("rr")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def role_react(self, ctx):
        """
        [ADMIN-ONLY] TOOL/UTILITY!

        Reaction-Role (RR) command group. For initial/startup use:
            - set messages to monitor reactions with `!rr addlink`
            - map an emoji to a @role with `!rr map`
            - add RR reactions for users to click with `!rr addreact`

        RECOMMENDED: see descriptions & usage for all `!rr`-based commands.
        """

        if ctx.invoked_subcommand is None:
            pass

    # !rr map <emoji> <role>
    @role_react.command("map")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def rr_map(self, ctx, emoji, role: discord.Role):
        """
        Map the specified <emoji> to the specified <role>.

        This allows the bot to know what role to give when users click an emoji on a
        reaction-role link being monitored (hint: use the `!rr addlink` command)
        """

        # add guild entry if it doesn't exist
        if ctx.guild.id not in self.rr_map:
            self.rr_map[ctx.guild.id] = dict()

        # ensure role is not an admin role
        if role.permissions.administrator:
            raise commands.CommandError("Admin role not allowed.")

        # properly convert emoji
        emoji = list(emojis.get(emoji))[0]
        if emoji is None:
            raise commands.CommandError(
                "Supplied emoji could not be properly converted."
            )

        # add <emoji:role> entry (within guild entry)
        self.rr_map[ctx.guild.id].update({str(emoji): role.name})

        # save mapping to json file
        self.save_rr_mappings()

        await react_success(ctx)

    @role_react.command("list")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def rr_list(self, ctx, options: Optional[str]):
        """
        Return list of current {emoji : role} mappings for the guild.

        Specify "-c" option to only return the NUMBER of current mappings.

        Usage:
        !rr list
        !rr list -c
        """
        if ctx.guild.id not in self.rr_map or len(self.rr_map[ctx.guild.id]) == 0:
            return

        # if the "-c" (count-only) option is specified, only return count
        if options is not None and "-c" in options:
            count = len(self.rr_map[ctx.guild.id])
            return await ctx.reply(f"Active emoji-role mappings: {count}")

        # create skeleton embed
        rr_map_embed = discord.Embed(
            title="Current Reaction-Role Mappings", colour=discord.Colour.blurple()
        )

        if self.rr_map is None:
            raise commands.CommandError("No emoji-role mappings found/registered.")

        # add a field for every mapped role found
        for emoji_str in self.rr_map[ctx.guild.id]:
            emoji = list(emojis.get(emojis.encode(emoji_str)))[0]
            if emoji is None:
                raise commands.CommandError(
                    "Error while iterating through emoji-role pairs."
                )

            rolename = self.rr_map[ctx.guild.id][emoji_str]

            rr_map_embed.add_field(
                name="\u2800",
                value="{}: **{}**".format(emojis.decode(emoji), rolename),
                inline=False,
            )

        await ctx.send(embed=rr_map_embed)

    @role_react.command("linkcount", aliases=["lc"])
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def rr_linkcount(self, ctx):
        """
        Returns the number of actively monitored interaction/reaction-role links.

        Usage:
        !rr linkcount
        !rr lc
        """
        if ctx.guild.id not in self.rr_links or self.rr_links[ctx.guild.id] is None:
            return await ctx.reply("Active reaction-role links monitored: 0")

        count = len(self.rr_links[ctx.guild.id])
        if (
            ctx.guild.id in self.rr_links.default_link
            and self.rr_links.default_link[ctx.guild.id] is not None
        ):
            count += 1

        await ctx.reply(f"Active reaction-role links monitored: {count}")

    # !rr poplink
    # (for freeing up space)
    @role_react.command("poplink")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def rr_poplink(self, ctx, N: int = 1, options: Optional[str] = None):
        """
        Remove the <N> oldest (placed at end of list) reaction-role message links from the cache.

        If no arguments supplied, only 1 link will be popped.

        May be useful if you want to manually clear the cache to make room for more reaction-role links.

        Specify the "-d" flag at end of command if you want to remove the default reaction-role msg assigned.

        Usage:
        !rr poplink
        !rr poplink 1
        !rr poplink 5
        !rr poplink 1 -d
        """

        gid = ctx.guild.id

        # remove entry/entries
        if (options is not None) and ("-d" in options.split()):
            self.rr_links.clear_default_link(gid)
        elif N == 1:
            self.rr_links.pop_link(gid)
        elif N > 1:
            for _ in range(min(N, len(self.rr_links[gid]))):
                self.rr_links.pop_link(gid)

        # save updated links to file
        self.save_rr_links()

    @role_react.command("addlink")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def rr_addlink(self, ctx, link: discord.Message, options: str = None):
        """
        Add a message link for the bot to monitor reaction-role reactions.

        Automatically pops the oldest message link in cache if capacity exceeded.

        Add a DEFAULT message link to monitor for reactions by specifying the "-d" flag.

        Usage:
        !rr addlink <message_id or message_link>
        !rr addlink <message_id or message_link> -d

        """
        gid = ctx.guild.id

        if options is None:
            default_set = False
        else:
            default_set = True if ("-d" in options.split()) else False
        self.rr_links.add_link(ctx.guild.id, link, default_set)

        # save updated links to file
        self.save_rr_links()

        await react_success(ctx)

    @role_react.command("addreact")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def rr_addreact(self, ctx, emoji, msg: discord.Message):
        """
        Attach an <emoji> to the specified <msg>, so users may click the reaction and self-assign a role.

        Usage:
        !rr addreact :paintbrush: 023805712532155
        !rr addreact :paintbrush: https://discord.com/channels/111/222/333
        """
        # emoji = list(emojis.get(emoji))[0]
        await msg.add_reaction(str(emoji))

    @role_react.command("save")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def save(self, ctx, scope: str = "all"):
        """
        Allow manual saving of reaction-role mappings and/or message link data.

        <scope>: "maps", "links" or "all"
        """

        if not RR_SCOPES.has_value(scope):
            return

        scope = RR_SCOPES[scope]

        if scope == RR_SCOPES.all:
            self.save_rr_links()
            self.save_rr_mappings()

        elif scope == RR_SCOPES.links:
            self.save_rr_links()

        elif scope == RR_SCOPES.maps:
            self.save_rr_mappings()

        await react_success(ctx)

    @role_react.command("load")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def load(self, ctx, scope: str = "all"):
        """
        Manually load currently saved reaction-role mappings and/or message link data.

        <scope>: "maps", "links" or "all"
        """

        if not RR_SCOPES.has_value(scope):
            return

        scope = RR_SCOPES[scope]

        if scope == RR_SCOPES.all:
            self.load_rr_links()
            self.load_rr_mappings()

        elif scope == RR_SCOPES.links:
            self.load_rr_links()

        elif scope == RR_SCOPES.maps:
            self.load_rr_mappings()

        await react_success(ctx)


def setup(bot):
    bot.add_cog(Selection(bot))
