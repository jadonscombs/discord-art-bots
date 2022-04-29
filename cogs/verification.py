import discord
from discord.ext import commands
import typing
from cogs.globalcog import GlobalCog
from constants import roles
from utils.async_utils import react_success, react_fail
import traceback


class Verification(commands.Cog, GlobalCog):
    """
    Custom unit designed for member verification features and functionality.
    """

    def __init__(self, bot):
        self.bot = bot

        # K:V pairs. The Vs are attribute names from the "unverified_users" table;
        # attribute names are the same for all guilds;
        self.action_types = {"message": "message_pass", "reaction": "reaction_pass"}

    async def verify_if_able(
        self, gid: str, uid: str, action_type: str, attachment: str = None
    ):
        """
        If user <uid> for the guild <gid> has passed all verification prerequisites (via flags/attribs),
        then proceed to "verify" the user, which entails the following:
            - give "Verified"/"Verified Member" role
            - update "member_status" attrib. in <udata> table
            - remove user entry from <unverified_users> table

        The <action_type> variable must either be "message" or "reaction" (for now).
        """
        if action_type == "message" and (
            attachment and self.check_intro_message(attachment)
        ):
            # update user's msg flag
            self.give_credit(gid, uid, action_type)

        elif action_type == "reaction":
            # update user's reaction flag
            self.give_credit(gid, uid, action_type)

        else:
            raise Exception("Unrecognized action type '{}'".format(action_type))

        # verify user if all prerequisites fulfilled
        if self.check_verification_prereqs(gid, uid):
            guild = self.bot.get_guild(int(gid))
            role = discord.utils.get(guild.roles, name=roles.VERIFIED_MEMBER)
            member = guild.get_member(int(uid))

            # give user the "Verified" role
            await member.add_roles(role)

            # get UserDataAccessor cog currently in use
            accessor = self.bot.get_cog("UserDataAccessor")

            # update "member_status" attrib.
            accessor.update("set", "verified", "member_status", None, member=member)

            # remove user entry from "unverified_users" table
            accessor.remove_user_from_unverified(gid, uid, status_already_set=True)

    def give_credit(self, gid: str, uid: str, action_type: str):
        """
        Updates the value of an attrib. associated with <action_type> in "unverified_users" table.

        For example, currently here are the <action_type>:<attribute> associations:
            --- "message"   : "message_pass"    (attrib. in "unverified_users" table)
            --- "reaction"  : "reaction_pass"   (attrib. in "unverified_users" table)

        Return True if updating value in DB for associated <action_type> executed successfully.
        """
        # get UserDataAccessor cog currently in use
        accessor = self.bot.get_cog("UserDataAccessor")

        if action_type in self.action_types:

            # update the flag value for the associated <action_type>
            member = self.bot.get_guild(int(gid)).get_member(int(uid))

            # print( f"giving credit for {action_type}" )

            accessor.update(
                "set",
                1,
                self.action_types[action_type],
                None,
                table="unverified_users",
                member=member,
            )
            return True
        return False

    def check_intro_message(self, text: str):
        """
        Return True if provided <text> meets all criteria for a sufficient intro message.
        """
        return (len(text) > 20) and (len(text.split(" ")) > 2)

    def check_verification_prereqs(self, gid: str, uid: str):
        """
        Helper method for <verify_if_able()>.

        (13 July 2021) This will simply check the values of the "message_pass" and "reaction_pass"
        attributes for the given <uid> in the "unverified_users" table in this guild's <gid> DB.

        Return True if user <uid> of guild <gid> completed all verification prerequisites.
        """
        # get UserDataAccessor cog currently in use
        accessor = self.bot.get_cog("UserDataAccessor")

        # only proceed if first flag is true
        flag1 = accessor.get_attr("message_pass", gid, uid, table="unverified_users")
        # print( f"flag1={flag1}, type={type(flag1)}" )
        if not flag1:
            return False

        # last flag value determines if all prereqs. fulfilled
        flag2 = accessor.get_attr("reaction_pass", gid, uid, table="unverified_users")
        # print( f"flag2={flag2}, type={type(flag2)}" )
        return bool(flag2) or False

    @commands.Cog.listener()
    async def on_message(self, message):
        # get UserDataAccessor cog currently in use
        accessor = self.bot.get_cog("UserDataAccessor")

        if message.guild is not None:
            is_intro_channel = accessor.is_channel(
                "introductions", str(message.guild.id), str(message.channel.id)
            )

            # only parse msg if msg in "intro" channel AND user doesn't have "Verified" role
            if is_intro_channel and (
                discord.utils.get(message.author.roles, name=roles.VERIFIED_MEMBER)
                is None
            ):
                # check message criteria and verify if needed
                await self.verify_if_able(
                    str(message.guild.id),
                    str(message.author.id),
                    "message",
                    message.clean_content,
                )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        # get UserDataAccessor cog currently in use
        accessor = self.bot.get_cog("UserDataAccessor")

        if accessor is None:
            raise RuntimeError("UserDataAccessor instance unavailable.")

        # preparing some data
        if payload.guild_id:
            gid = str(payload.guild_id)
        if payload.member:
            member = payload.member

        # parse reaction only if (in guild context), (in "rules" zone), and (not a bot)
        # (side note: "if" indentation is based on PEP8, in case it looks wonky)
        if (
            payload.guild_id
            and accessor.is_channel(
                "rules", str(payload.guild_id), str(payload.channel_id)
            )
            and not member.bot
        ):

            # credit the reaction and verify if needed
            await self.verify_if_able(gid, str(member.id), "reaction")

    @commands.command("verify_status")
    @commands.guild_only()
    @GlobalCog.set_clearance(6)
    async def verify_status(self, ctx, uid: typing.Optional[str] = None):
        """
        Return the specified user's <uid> verification status in the DB.
        (example: returns "verified" or "unverified")

        Usage:
        !verify_status 86739392159063
        !verify_status self
        """
        try:
            # get UserDataAccessor cog currently in use
            accessor = self.bot.get_cog("UserDataAccessor")

            # get uid and verification status (from <udata>)
            gid = str(ctx.guild.id)
            if uid is None or uid == "self":
                uid = str(ctx.author.id)
            status = accessor.get_attr("member_status", gid, uid)

            # if status is "unverified," attempt to get details from <unverified_users>
            description = status
            if status == "unverified":
                has_reacted = accessor.get_attr(
                    "reaction_pass", gid, uid, table="unverified_users"
                )
                has_intro = accessor.get_attr(
                    "message_pass", gid, uid, table="unverified_users"
                )

                # if either trait is empty/null...
                if "" not in (has_reacted, has_intro):
                    description = (
                        f"agreed to rules (reaction): {bool(has_reacted)}\n"
                        f"valid introduction: {bool(has_intro)}"
                    )

            # prepare and send embed
            member = ctx.guild.get_member(int(uid))
            embed = discord.Embed(
                title=f"Verification Status ({member.name})",
                description=description,
                colour=discord.Colour.greyple(),
            )
            embed.set_thumbnail(url=member.avatar_url)
            reply = await ctx.reply(embed=embed)

        except:
            traceback.print_exc()
            raise commands.CommandError("Unknown exception occurred.")

    @commands.command("remove_from_unverified", hidden=True)
    @commands.guild_only()
    @GlobalCog.set_clearance(6)
    async def remove_from_unverified(self, ctx, user: discord.Member):
        """
        Manually remove specified <user> from [unverified_users] table.
        Will only work if user has the 'Verified' role.

        Note: <user> can be an ID, @mention, or UserTag#0101

        Usage:
        !remove_from_unverified 86739392159063
        !remove_from_unverified @Koyorin
        """
        accessor = self.bot.get_cog("UserDataAccessor")
        accessor.remove_user_from_unverified(str(ctx.guild.id), str(user.id))
        await self.react_success(ctx)

    @commands.command("unverify", aliases=["uv"], hidden=True)
    @commands.guild_only()
    @GlobalCog.set_clearance(6)
    async def unverify(self, ctx, userid: str, *, options=None):
        """
        Manually un-verify a user (via <userid>). By default, this will remove a
        user's "Verified" role in Discord and set user's "member_status"
        in "udata" table to "unverified".

        OPTIONS:
            -u      Put user (entry) in the "unverified_users" table -- effectively makes them a new member.

        Usage:
        !unverify 03892384723912
        !uv 03892384723912
        !unverify 03892384723912 -u
        """
        try:
            accessor = self.bot.get_cog("UserDataAccessor")
            role = discord.utils.get(ctx.guild.roles, name="Verified")
            member = ctx.guild.get_member(int(userid))

            if (not member) or (not role):
                raise commands.CommandError("Member or Role could not be found.")

            try:
                # remove user's "Verified" role in discord
                await member.remove_roles(role)

                # set the member status in primary userdata table
                accessor.update(
                    "set", "unverified", "member_status", None, member=member
                )
            except:
                raise commands.CommandError(
                    "Error while removing member's 'Verified' role. Aborting."
                )

            # parse <options> for extra actions to take
            if options and (options == "-u"):
                try:
                    accessor.add_user_to_unverified(str(ctx.guild.id), userid)
                except:
                    raise commands.CommandError(
                        "Error while trying to add user to 'unverified_users' table. Aborting."
                    )

            # all operations successful if this executes
            await react_success(ctx)
        except:
            raise Exception

    @commands.command("verify", aliases=["v"], hidden=True)
    @commands.guild_only()
    @GlobalCog.set_clearance(1)
    @commands.has_permissions(manage_roles=True)
    async def verify(self, ctx, member: discord.Member):
        """
        Manually invoke the verification process. The member is checked
        first before invoking the process.

        Usage:
        !verify @User64
        """
        accessor = self.bot.get_cog("UserDataAccessor")
        role = discord.utils.get(ctx.guild.roles, name=roles.VERIFIED_MEMBER)

        # just add entry in db if user not in there yet
        accessor.ADD_USER(str(ctx.guild.id), str(member.id))

        if role and (role not in member.roles):
            await member.add_roles(role)
            accessor.remove_user_from_unverified(str(ctx.guild.id), str(member.id))
            await react_success(ctx)

        elif role is None:
            raise commands.CommandError("No 'Verified' role could be found.")


def setup(bot):
    bot.add_cog(Verification(bot))
