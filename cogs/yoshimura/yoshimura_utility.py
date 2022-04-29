"""
Administrative / mod tools
"""

import discord
from discord.ext import commands
from cogs.globalcog import GlobalCog
from constants import roles
from typing import Iterable, List, Union, Optional
from utils.async_utils import react_success, react_fail
import argparse
import datetime
import emojis
import git
from git import Git, Repo
import subprocess
import sys
import traceback


class Utility(commands.Cog, GlobalCog):
    """
    Administrative and utility-based functionality.
    """

    def __init__(self, bot):
        self.bot = bot
        self.max_clearance_level = 25

    @commands.command("gitpull", hidden=True)
    @GlobalCog.no_points()
    @commands.guild_only()
    @commands.is_owner()
    async def gitpull(self, ctx):
        """Hard-set git pull command. Will pull from origin/master by default."""
        try:
            subprocess.run(
                "/root/discord_stuff/kaede_yoshimura/discord-EGbot/agent-auto-start.sh"
            )
            await react_success(ctx)
        except:
            traceback.print_exc()
            await react_fail(ctx)

    @commands.command("initdb", hidden=True)
    @GlobalCog.no_points()
    @commands.guild_only()
    @commands.is_owner()
    async def init_db(self, ctx, max_users=1500):
        """
        WARNING: USE THIS SPARINGLY (PREFERABLY ONCE)

        USE THIS WHEN FIRST GETTING THE DATABASE SETUP FOR
        ALL (or <max_users>) IN YOUR SERVER.

        THIS WILL SCAN <max_users> USERS FOR THE "Verified" ROLE,
        AND UPDATE THIS STATUS IN THE DATABASE.
        """

        # first check to ensure the "busy" (long_process_active) flag isn't already set
        if not self.long_process_active:
            self.long_process_active = True
        else:
            raise commands.CommandError("Blocking function in use; try later.")

        # commence main operation now
        try:
            acc = self.accessor_mirror
            add_user = acc.ADD_USER
            gid = str(ctx.guild.id)
            counter = 0
            max_users = min(max_users, 1500)  # hard-coded limit
            for member in ctx.guild.members:

                # add user to the database for this given server
                #
                # NOTE (for <except> clause):
                # - if using 'continue':    scans >= max_users; (no increment on error)
                # - if using 'pass':        scans <= max_users; (increments on error)
                if counter >= max_users:
                    break
                try:
                    acc.ADD_USER(gid, str(member.id))
                except:
                    pass
                counter += 1

            await react_success(ctx)

        except:
            traceback.print_exc()
            await react_fail(ctx)

        finally:
            self.long_process_active = False  # unset the busy flag

    @commands.command("setval", aliases=["set"], hidden=True)
    @GlobalCog.no_points()
    @GlobalCog.set_clearance(9)
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def setval(
        self, ctx, user: Union[str, discord.Member], attr: str, val, *, table="udata"
    ):
        """
        Set a particular attribute to a specific value.

        If <user> == "all", apply value to attribute for all
        users in the guild specified by <ctx>.

        If <user> == "column," apply value to entire column

        <user> format: Name#0000, userID, @mention, "all", or "column"
        """
        try:
            # only these tables allow value-setting
            if table not in ["udata", "unverified_users", "server_stats", "blacklist"]:
                return

            self.set_flag("NO_POINTS", True)
            mirror = self.accessor_mirror
            gid, uid = str(ctx.guild.id), str(ctx.author.id)
            cmd = ""

            if (user is None) or (not mirror.is_numeric_attr(attr)):
                return

            # quickly checking if val out of bounds
            try:
                if val < 0.0 or val > 5e5:
                    return
            except:
                pass

            # connect and execute an update
            with mirror.connect(gid) as conn:
                cur = conn.cursor()

                # CASE 1: if user == 'all', apply change to all users
                if user == "all":
                    userlist = ctx.guild.members
                    cmd = "UPDATE " + table + " SET {} = {} WHERE id={}"
                    execute = cur.execute
                    cfmt = cmd.format

                    for u in userlist:
                        execute(cfmt(attr, val, str(u.id)))

                # CASE 2: updating an entire column
                elif user == "column":
                    cmd = "UPDATE {} SET ? = ?".format(table)
                    cur.execute(cmd, (attr, val))

                # CASE 3: if user is a specific user
                else:
                    convert_class = commands.MemberConverter()
                    user = await convert_class.convert(ctx, user)

                    # tmp = ctx.guild.get_member(user)
                    # if tmp and not tmp.bot: user = str(tmp.id)
                    # else: user = mirror.validate_gamertag(user, gid, uid)

                    if user is not None:
                        cmd = "UPDATE {} SET {} = {} WHERE id={}".format(
                            table, attr, val, str(user.id)
                        )
                        cur.execute(cmd)

                conn.commit()
                await react_success(ctx)
        except:
            traceback.print_exc()
            await react_fail(ctx)

    # --- THIS COMMAND IS COMMENTED OUT UNTIL IT'S MORE SECURE ---
    # @commands.command('addcolumn', hidden=True)
    # @commands.guild_only()
    # @commands.is_owner()
    # async def add_column(self, ctx, colname, coltype, table='udata'):
    # '''
    # Admin command to add a column to user data database.

    # IMPORTANT: use ">>setval" command to set custom default value for new column
    # '''
    # try:
    # self.set_flag('NO_POINTS', True)
    # mirror = GlobalCog.accessor_mirror
    # mirror.ADD_COL(colname, coltype, table=table)
    # await self.react_success(ctx)

    # except: traceback.print_exc()

    @commands.group("dzone")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def dzone(self, ctx):
        """
        Parent command for designation zone-related commands.
        """
        if ctx.invoked_subcommand is None:
            pass

    @dzone.command("list")
    @GlobalCog.no_points()
    @GlobalCog.set_clearance(7)
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def dzone_list(self, ctx, options: Optional[str] = None):
        """
        Informational command; list all predefined designation zones.

        Flags (space-separated):
            -r  :   only list zones registered for the server
            -n  :   show number of channels registered per zone
            -i  :   show registered #channel-names per listed zone

        NOTE (about flags):
            "-r" determines # zones listed. All other args come after.

        Formatting:
            "
            [zone name] [#channels]
            [channel mentions]
            "

        Usage:
        !dzone list
        !dzone list -r
        !dzone list -rn
        !dzone list -i
        !dzone list -n
        !dzone list -inr
        """

        # get the UDA (UserDataAccessor) cog
        uda = self.bot.get_cog("UserDataAccessor")

        # restrict this command to bot_operator_zone only
        if not uda.is_channel(
            "bot_operator_zone", str(ctx.guild.id), str(ctx.channel.id)
        ):
            raise commands.CommandError(
                (
                    "Command only allowed in a designated "
                    "**bot operator channel**. "
                    "Use `!setzone bot_operator_zone` to designate a bot "
                    "operator channel, then try `!dzone list` again in that channel."
                )
            )

        parser = argparse.ArgumentParser()
        parser.add_argument("-r", action="store_true", dest="registered")
        parser.add_argument("-n", action="store_true", dest="n_channels")
        parser.add_argument("-i", action="store_true", dest="identities")

        if options:
            options = options.split(" ")
        args = parser.parse_args(options)
        gid = str(ctx.guild.id)
        zone_list, channels_list, n_list, fmt_list, = (
            [],
            [],
            [],
            [],
        )

        # checking for "-r" flag -- listing zone names
        if args.registered:
            zone_list = []

            for zone_name in uda.zones[gid]:
                if uda.zones[gid][zone_name] not in {"", "n/a", None}:
                    zone_list.append(zone_name)
        else:
            zone_list = [z for z in uda.zones[gid]]

        for zone in zone_list:

            # get channel IDs listed per zone (for convenience)
            ids = (uda.zones[gid][zone] or "").split(",")

            # CHECK: "-i" flag -- get channel mentions
            if args.identities:

                # convert channel IDs
                for i, id_ in enumerate(ids):
                    try:
                        ids[i] = int(id_)
                    except ValueError:
                        ids[i] = 0

                # fetch channel mentions
                mentions = []
                gch = self.bot.get_channel
                for id_ in ids:
                    channel = gch(id_)
                    mentions.append(channel.mention if channel else "( )")

                # PER ZONE: create mentions string (then add to channels_list)
                channels_list.append(",".join(mentions))

            # CHECK: "-n" flag -- get num. channels per zone
            if args.n_channels:
                n_list.append(len(ids))

            # formatting string (then add to fmt_list)
            s = f"- **`{zone}`**"
            if args.n_channels:
                s += f" (channels found: {len(ids)})"
            if args.identities:
                s += f"\nchannel names: {mentions}"
            fmt_list.append(s)

        # rejoin fmt_list entries into string
        output_str = "\n\n".join(fmt_list)

        # prepare embed and send
        embed = discord.Embed(
            title="Currently Found Zones",
            description=output_str,
            colour=discord.Colour.green(),
        )
        await ctx.send(embed=embed)

    @dzone.command("set", aliases=["setzone"])
    @GlobalCog.no_points()
    @GlobalCog.set_clearance(7)
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def dzone_set(
        self, ctx, zone_name: str, text_channel: Optional[discord.TextChannel] = None
    ):
        """
        Zone tool to help set [designation zones].

        Use "!dzone list" to see what zones can be set.

        If <text_channel> is None, then <ctx.channel.id> is used.
        """

        # get the UDA (UserDataAccessor) cog
        uda = self.bot.get_cog("UserDataAccessor")

        if zone_name in uda.zones[str(ctx.guild.id)]:
            CL = uda.check_clearance(str(ctx.guild.id), str(ctx.author.id))

            # only admins with CL7+ can set the "introductions" zone.
            # NOTE: this limit applies even if the
            #       "@GlobalCog.set_clearance(...)" required level changes.
            if zone_name in {"introductions", "rules"} and (CL < 7):
                raise commands.CommandError(
                    "You must have CL7 or higher to set the "
                    '"introductions" or "rules" zone.'
                )

            if CL < 6:
                raise commands.CommandError(
                    "You must have CL6 or higher to set designation zones."
                )

            # all other zones can be set by those with CL6+
            try:
                if text_channel is None:
                    text_channel = ctx.channel
                uda.set_designation(str(ctx.guild.id), zone_name, str(text_channel.id))
                await react_success(ctx)
            except:
                traceback.print_exc()
                await react_fail(ctx)

    @dzone.command("clear")
    @GlobalCog.no_points()
    @GlobalCog.set_clearance(7)
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def dzone_clear(
        self, ctx, zone_name: str, channel_id: Union[discord.TextChannel, str, None]
    ):
        """
        Zone tool to clear registered entries for a specific zone (`y!dzone list`).

        If NO channel_id or #channel_mention is given, the current channel is used.

        Parameters:
            zone_name: (str)
                Name of zone you want to update
            channel_id: [optional](#channel-mention, ID, or nothing)
                Channel ID that the zone(s) will remove an entry for.
                Can also be "all" to target ALL channels for the given zone(s).

        To remove one (1) channel entry from (1) zone:
            `y!dzone clear ZONE_NAME CHANNEL`
            `y!dzone clear stream_text`  (CHANNEL = current ch.)
            `y!dzone clear ZONE_NAME #channel_mention

        To remove one (1) channel entry from ALL zones:
            `y!dzone clear all CHANNEL_ID`

        To remove ALL channel entries from (1) zone:
            `y!dzone clear ZONE_NAME all`  (CHANNEL_ID = "all")

        To remove ALL channel entries from ALL zones (careful!):
            `y!dzone clear all all`
        """

        uda = self.bot.get_cog("UserDataAccessor")
        is_valid_name = uda.get_designation_channel_id(
            str(ctx.guild.id), zone_name.lower()
        )

        # check if <zone_name> is valid
        if zone_name.lower() != "all" and not is_valid_name:
            raise commands.CommandError("Invalid zone name.")

        # check/parse <channel_id> arg
        if channel_id is not None:

            # if <channel_id> isn't "all", process further
            if not (isinstance(channel_id, str) and channel_id == "all"):

                # try converting to TextChannel
                try:
                    converter = commands.TextChannelConverter()
                    channel = await converter.convert(ctx, channel_id)
                    channel_id = channel.id
                except commands.CommandError:
                    raise commands.CommandError("Invalid channel argument.")
        else:
            channel_id = ctx.channel.id

        # now iterating/updating zone entry/entries (below)
        channel_id = str(channel_id)
        gid = str(ctx.guild.id)

        # ALL zones specified
        if zone_name == "all":

            # clear ALL entries for ALL zones
            if channel_id == "all":
                for zone in uda.zones[gid]:
                    uda.set_designation(gid, zone, "", overwrite=True)

            else:
                # remove the specified channel ID for ALL zones if it's found
                for zone in uda.zones[gid]:
                    uda.remove_designation(gid, zone_name, channel_id)

        # one (1) zone specified
        else:

            # clear ALL entries for one (1) zone
            if channel_id == "all":
                uda.set_designation(gid, zone_name, "", overwrite=True)

            # clear one (1) entry for one (1) zone
            else:
                uda.remove_designation(
                    gid, zone_name, channel_id, is_channel_bypass=True
                )

        await react_success(ctx)

    # dzone add
    @dzone.command("addzone")
    @GlobalCog.no_points()
    @GlobalCog.set_clearance(7)
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def dzone_addzone(self, ctx, zone_name: str, options: Optional[str] = None):
        """
        Zone tool to add a new zone category (e.g. "introductions", "rules").

        Flags:
            -L <N>  :   N = number of channels allowed in this zone

        Usage:
        !dzone addzone MY_NEW_ZONE
        !dzone addzone MY_NEW_ZONE -L 7
        """

        uda = self.bot.get_cog("UserDataAccessor")

        # route 1: options were specified
        if options is not None:
            parser = argparse.ArgumentParser()
            parser.add_argument("-L", dest="limit", type=int, default=1)

            options = options.split(" ")
            args = parser.parse_args(options)

            # add specified zone <zone_name>
            uda.add_designation_category(str(ctx.guild.id), zone_name, limit=args.limit)

        # route 2: (default) no options specified
        else:
            uda.add_designation_category(str(ctx.guild.id), zone_name)

        await react_success(ctx)

    @dzone.command("refresh")
    @GlobalCog.no_points()
    @GlobalCog.set_clearance(7)
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def dzone_refresh(self, ctx):
        """
        Zone tool to manually reload/refresh all zones for the guild if needed.
        """
        uda = self.bot.get_cog("UserDataAccessor")
        uda.load_zone_entries(str(ctx.guild.id))
        await react_success(ctx)

    @commands.command("grant_self_clearance", hidden=True)
    @GlobalCog.no_points()
    @commands.guild_only()
    @commands.is_owner()
    async def grant_self_clearance(self, ctx, level: float):
        """
        Admin command to grant bot owner arbitrary clearance level
        """
        try:
            if level >= 0 and level <= self.max_clearance_level:
                gid = str(ctx.guild.id)
                with self.accessor_mirror.connect(gid) as conn:
                    cur = conn.cursor()
                    cmd = "UPDATE udata SET clearance=? WHERE id=?"
                    cur.execute(cmd, (level, str(ctx.author.id)))
                    conn.commit()
                await react_success(ctx)
            else:
                await react_fail(ctx)

        except:
            traceback.print_exc()
            await react_fail(ctx)

    @commands.command("giveclearance", aliases=["gclr"])
    @GlobalCog.no_points()
    @GlobalCog.set_clearance(9)
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def give_clearance(
        self, ctx, level: float, member: discord.Member, force=None
    ):
        """
        Give clearance to another user. Normally, <level> must be greater than <member>'s
        current clearance level. <member> must also be verified.

        <level>:    must be LESS than your own clearance level
        <member>:   must be an @mention/userID/User#0123. will not work on yourself.
        <force>:    specify "-f" or "--force" (without quotations) to override all restrictions

        Usage:
        !giveclearance 3 UserName#5433
        !gc 3 UserName#5433
        !gc 5.0 @Kirakira -f
        """
        # cannot self-assign
        if member.id == ctx.author.id:
            return

        # get clearance data and close DB connection afterwards
        acc = self.accessor_mirror
        author_clearance, user_clearance = None, None
        with acc.connect(str(ctx.guild.id)) as conn:
            cur = conn.cursor()

            # retrieve YOUR clearance level
            cur.execute("SELECT clearance FROM udata where id=?", (str(ctx.author.id),))
            author_clearance = cur.fetchone()
            if author_clearance:
                author_clearance = float(author_clearance[0])
            else:
                raise commands.CommandError(
                    "Requester's clearance level could not be retrieved."
                )

            # if YOUR clearance level  <=  <level>: return
            if author_clearance <= level:
                return

            # retrieve USER's clearance level
            cur.execute("SELECT clearance FROM udata where id=?", (str(member.id),))
            user_clearance = cur.fetchone()
            if user_clearance:
                user_clearance = float(user_clearance[0])
            else:
                raise commands.CommandError(
                    "Requester's clearance level could not be retrieved."
                )

            # checking to ensure target user is "Verified":
            verif_role = discord.utils.get(ctx.guild.roles, name=roles.VERIFIED_MEMBER)
            if verif_role is not None:
                if (user_clearance < 1) and (verif_role not in member.roles):
                    raise commands.CommandError(
                        "Error: target user unverified. Clearance can only be given to Verified members."
                    )
            else:
                raise commands.CommandError("The 'Verified' role could not be found.")

            # (edge case) deny clearance PROMOTION if user is unverified and has a CL >= 1
            if (
                (verif_role not in member.roles)
                and (user_clearance >= 1)
                and (level > user_clearance)
            ):
                raise commands.CommandError(
                    "Action denied. Please contact an admin as "
                    "the target user is **unverified**, but has a (CL)earance "
                    "**greater than 0**, which is not allowed for **unverified** users.\n\n"
                    "Tip: use `!verify_status <userid>` to see target user's (CL)earance."
                )

            # (normal)  if user's clearance level  >=  <level>: return
            # (force)   needs to be "-f" or "--force" to force demotion of clearance
            if user_clearance >= level:
                if (force is None) or (force not in ("-f", "--force")):
                    return

            # do not allow a multi-level clearance grant unless *force* enabled
            if level - user_clearance > 1:
                if (force is None) or (force not in ("-f", "--force")):
                    return

            # proceed with granting clearance
            cur.execute(
                "UPDATE udata SET clearance=? WHERE id=?", (level, str(member.id))
            )
            conn.commit()
        await react_success(ctx)

    @commands.command("resetstats", hidden=True)
    @GlobalCog.no_points()
    @commands.guild_only()
    @GlobalCog.set_clearance(9)
    async def reset_user_stats(self, ctx, user: discord.Member):
        """
        Command to reset a SINGLE user's stats to initial values
        """
        try:
            self.set_flag("NO_POINTS", True)
            mirror = GlobalCog.accessor_mirror
            gid = str(ctx.guild.id)
            uid = str(ctx.author.id)
            status_string = "unverified"

            if user is not None:
                with mirror.connect(gid) as conn:
                    cur = conn.cursor()

                    # first determine if user was verified
                    cur.execute("SELECT member_status FROM udata WHERE id=?", (user,))
                    status = str(cur.fetchone()[0])
                    if status and (status == "verified"):
                        status_string = "verified"

                    # delete user from the table(s)
                    cur.execute("DELETE FROM udata WHERE id=?", (user,))
                    conn.commit()

                # re-add user to <udata> table
                mirror.ADD_USER(gid, user)

                # re-set user's clearance level (CL) and member_status
                with mirror.connect(gid) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT clearance FROM udata WHERE id=?", (user,))
                    clearance = int(cur.fetchone()[0])
                    cmd = "UPDATE udata SET clearance=?, member_status=? WHERE id=?"
                    cur.execute(cmd, (1, status_string, uid))
                    conn.commit()
        except:
            traceback.print_exc()
            await react_fail(ctx)

    @commands.command("deleteuser", hidden=True)
    @GlobalCog.no_points()
    @commands.guild_only()
    @GlobalCog.set_clearance(7)
    async def delete_user(self, ctx, userid, unverify: bool = False):
        """
        Delete all database records for the specified user.

        Set <unverify> true if you want to remove user's "Verified" role as well.

        Usage:
        !deleteuser 86739392159063
        !deleteuser 86739392159063 True
        """
        try:
            mirror = self.accessor_mirror
            status = mirror.DELETE_USER(str(ctx.guild.id), str(userid))
            if unverify:
                role = discord.utils.get(ctx.guild.roles, name=roles.VERIFIED_MEMBER)
                member = ctx.guild.get_member(int(userid))
                await member.remove_roles(role)
            await react_success(ctx)
        except:
            traceback.print_exc()
            await react_fail(ctx)

    @commands.command("displaytable", hidden=True)
    @commands.guild_only()
    @GlobalCog.no_points()
    @GlobalCog.set_clearance(9)
    # @commands.is_owner()
    async def displaytable(self, ctx, destination="", table="udata"):
        """
        Print current sqlite db in console (to check stats).

        Currently only allowed in [bot-operator zones].

        Usage:
        !displaytable
        !displaytable -h

        Add "--here" or "-h" to display in discord
        """
        try:
            # retrieving and printing specified table data to console
            acc = self.accessor_mirror
            data = acc.print_table(str(ctx.guild.id), "N/A", table)
            if data:
                print("----------------")
                print(f"\nCURRENT TABLE:\n{data}\n")
                print("----------------")

            # send back to discord if user wants to see it in chat
            if (destination in ("--here", "-h")) and data:
                if acc.is_channel(
                    "bot_operator_zone", str(ctx.guild.id), str(ctx.channel.id)
                ):
                    await ctx.reply(data)
                else:
                    await react_fail(ctx)

                    e = discord.Embed(
                        description="This command is only allowed in a **bot_operator_zone**",
                        colour=discord.Colour.red(),
                    )

                    reply = await ctx.reply(embed=e)

        except:
            traceback.print_exc()
            await react_fail(ctx)


""" ======================= COGLOADING + MAIN ====================== """


def setup(bot):
    bot.add_cog(Utility(bot))
    print("[utility] cog loaded!")


if __name__ == "__main__":
    print("[utility] cog loaded!")
