import discord
from discord.ext import commands
from cogs.globalcog import GlobalCog
import emojis
import random
import traceback
import typing
from utils.async_utils import react_success, react_fail
from utils.sync_utils import stream_started


class Fun(commands.Cog, GlobalCog):
    """Miscellaneous fun/novelty commands."""

    def __init__(self, bot):
        self.bot = bot
        self.acc = GlobalCog.accessor_mirror

    # - - - - - - - - - - - -
    # STARBOARD COMMAND [TODO]
    # - - - - - - - - - - - -

    @commands.command("streamnotifs")
    @commands.guild_only()
    @commands.cooldown(3, 5, commands.BucketType.user)
    @GlobalCog.set_clearance(1)
    async def streamnotifs(self, ctx, choice: str):
        """
        Enable/Disable notifications for when someone in the server goes LIVE (default = off)

        <choice>:   on/off
        """
        if (len(choice) > 4) or choice.lower() not in ("on", "off"):
            return

        try:
            role = self.acc.fetch_role(
                "streamnotif", str(ctx.guild.id), ctx.message.guild
            )
            if role:
                if choice == "on":
                    await ctx.author.add_roles(role)
                else:
                    await ctx.author.remove_roles(role)
                await react_success(ctx)

        except:
            traceback.print_exc()

    @commands.command("star", aliases=["givestar", "givecoffee", "coffee"])
    @commands.guild_only()
    @commands.cooldown(1, 43200, commands.BucketType.member)
    @GlobalCog.set_clearance(1)
    async def give_star(self, ctx, recipient: discord.Member):
        """
        Gives the <recipient> a little bundle of points. Can only be used once per X hours.

        <recipient>:    an @mention, userID, or the format RandomUser#2531
        """
        # side note: 12 hours = (12 * 3600) seconds = 43200 seconds
        try:
            default_points_award = 25

            # getting target user (the <recipient>)
            if recipient == "self":
                return await react_fail(ctx)

            if recipient == self.bot.user:
                msg = (
                    "Oh, thank you! :smiling_face_with_3_hearts: "
                    "But I cannot accept, I am just a bot :yum:"
                )
                return await ctx.reply(msg)

            # give points to <recipient> now
            self.acc.ub_addpoints(
                None,
                None,
                "Used the 'star' command (cooldown 12hrs).",
                bank_amount=default_points_award,
                member=recipient,
            )

            # react w/emoji to confirm
            await ctx.message.add_reaction(list(emojis.get(emojis.encode(":gift:")))[0])
        except:
            traceback.print_exc()
            await react_fail(ctx)
            ctx.command.reset_cooldown(ctx)

    @commands.command("gift")
    @commands.guild_only()
    @commands.cooldown(1, 120, commands.BucketType.user)
    @GlobalCog.set_clearance(1)
    async def give_gift(self, ctx, recipient: discord.Member, amount: float, *, gift):
        """
        Give <recipient> a gift of your choice!

        Example usage:
            >>gift @Saul 2 :chicken:
            >>gift UserName#8821 5 kisses
            >>gift @Alice 49 icecream
        """
        try:
            # temporary disable/public notif. of command's status
            raise commands.CommandError("Command not available yet. Coming soon!")

            if recipient.bot:
                return

            # just return; points cannot be directly gifted yet
            if gift.lower() in ("points", "point"):
                embed = discord.Embed(
                    description="Point gifting not available yet. Wait for it in a future update!",
                    colour=discord.Colour.red(),
                )
                reply = await ctx.reply(embed=embed)

            await react_success(ctx)

        except:
            traceback.print_exc()
            await react_fail(ctx)
            ctx.command.reset_cooldown(ctx)

            
    @commands.command("roll")
    @commands.guild_only()
    @commands.cooldown(10, 9, commands.BucketType.user)
    @GlobalCog.set_clearance(1)
    async def roll(self, ctx, sides: typing.Optional[int] = 6):
        """
        Roll dice, return a number (default: 6-sided). Sides can be [1 - 500].

        Usage:
        !roll
        !roll 3
        !roll 48
        """

        # max_sides = 500
        if abs(sides) < 500:
            num = random.randint(1, abs(sides))
            await ctx.reply(f"You rolled {num}")


    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        prev: discord.VoiceState,
        curr: discord.VoiceState
    ):
        """
        Event handler for voice channel activity based actions.
        """

        # ====== logic for notifying users when someone goes LIVE ======

        # proceed if user started streaming AND they did not channel hop
        if not stream_started(prev, curr):
            return
            
        # see if the @streamnotif role exists;
        # discord.utils.get(...) evaluates to None if results set is empty
        notif_role = discord.utils.get(member.guild.roles, name="streamnotif")
        if notif_role is None:
            raise RuntimeError(
                "[on_voice_state_update][error] "
                "no '@streamnotif' role has been found. cannot ping. exiting."
            )
        
        # check if the "stream_text" channel/designation zone is set (REQUIRED)
        uda = self.bot.get_cog("UserDataAccessor")
        if not uda.designation_is_set(
            str(member.guild.id),
            "stream_text"
        ):
            raise RuntimeError(
                "[on_voice_state_update][error] "
                "no '@streamnotif' role has been found. cannot ping. exiting."
            )
            
        # check if user went LIVE recently; if yes, return
        # only notify @streamnotif if it's been a while since user was last live;
        # NOTE:
        # check_went_live_interval() will update a user's "last_went_live"
        # attribute upon checking
        #
        if not uda.check_went_live_interval(
            member, min_interval_sec=300
        ):
            return
        
        # get designated 'stream_text' channel
        channel_id = uda.get_designation_channel_id(
            str(member.guild.id), "stream_text"
        )
        
        if channel_id is None or channel_id in {"", "n/a"}:
            raise RuntimeError(
                "[on_voice_state_update][error] "
                "channel ID for 'stream_text' zone could not be found."
            )
        
        # get first ID in the results set
        channel_id = channel_id.split(",")[0]
        channel = member.guild.get_channel(int(channel_id))

        # send the notification message and tag @streamnotif users
        notif_msg = (
            f"**{member.name}** just started streaming. "
            f"Come watch! :partying_face:"
        )
        await channel.send(f"{notif_role.mention} {notif_msg}")
            
            
def setup(bot):
    bot.add_cog(Fun(bot))
    print("[fun] cog loaded!")


if __name__ == "__main__":
    try:
        print("Loading fun cog!")
    except:
        traceback.print_exc()
