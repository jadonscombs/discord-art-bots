import discord
from discord.ext import commands

import datetime
import asyncio
import re
import traceback
import typing
from cogs.globalcog import GlobalCog
from constants import roles
from utils.sync_utils import stream_started, stream_stopped


class PointSystem(commands.Cog, GlobalCog):
    """
    Functionality for K/Y's custom point system.
    """

    # TODO: integrate an "Achievements" system/component.

    def __init__(self, bot):
        self.bot = bot


    # EVENT LISTENER: stream points
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        prev: discord.VoiceState,
        curr: discord.VoiceState
    ):
        """
        Event handler to award points based on voice channel activity.
        """
        
        time_now = datetime.datetime.now()
        
        # proceed if user stopped streaming, otherwise return
        if not self.stream_stopped(prev, curr):
            return

        # retrieve user data accessor module
        # or raise exception if None
        uda = self.bot.get_cog("UserDataAccessor")
        if uda is None:
            raise RuntimeError(
                "[on_voice_state_update] error: UserDataAccessor "
                "could not be retrieved."
            )

        # get most recent stream "live" time, and stream "end" time
        last_went_live = uda.get_last_live_time(member)
        last_went_live = datetime.datetime.strptime(
            last_went_live, "%m/%d/%Y %H:%M:%S"
        )

        # check if time since last going live is "significant"
        # enough to give a stats update and points
        live_time_diff = time_now - last_went_live
        total_secs = live_time_diff.total_seconds()

        if total_secs > 60:
            
            # convert collected stream time to minutes
            total_mins = round(total_secs / 60, 1)
            
            # add stream time to the users' stats
            uda.update(
                "add", total_mins, "total_time_streamed", None, member=member
            )
            uda.update(
                "add", 1, "num_times_streamed", None, member=member
            )

        # award points for streaming
        uda.award_stream_points(total_secs, member)
        

    # EVENT LISTENER: on_message
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Event handler called for message events.
        """
        
        # do not proceed if action issuer is bot
        if message.author.bot:
            return
        
        # ACTION: AWARD MESSAGE POINTS
        try:

            # if unable to award art-posting or reply-to-art points,
            # award normal points
            if not (
                self.award_art_message_points(message)
                or self.award_art_reply_points(message)
            ):
                self.award_message_points(message)
        except:
            traceback.print_exc()

        # ACTION: AWARD POINTS UPON SERVER BOOST
        try:

            # - if message.type == discord.MessageType.premium_guild_subscription"
            # - award with points (and OPTIONAL--> a @role or perks)
            if message.type == discord.MessageType.premium_guild_subscription:

                # (for now) award only points in exchange for boosting
                await self.award_server_boost_points(message)

        except:
            traceback.print_exc()

    # RAW REACTION POINT AWARDING
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """
        Event handler called for reaction add events.
        """

        # do not proceed if action issuer is bot
        if self.bot.get_user(payload.user_id).bot:
            return
        
        # ACTION: AWARD REACTION POINTS
        try:
            # if unable to award art-specific reaction points to author,
            # award normal reaction points to author
            if not await self.award_art_reaction_points(payload):
                await self.award_reaction_points(payload, award_author=True)
            await asyncio.sleep(4.0)

            # award normal reaction points to "reacter"
            await self.award_reaction_points(payload)
        except:
            traceback.print_exc()

            
    async def award_server_boost_points(
        self, message: discord.Message, points: float = 45.0
    ):
        """
        Helper method to give points to the server boosting member.

        1. Send appreciation message to user
        2. (attempt to) give points to user


        Note: See <points> kwarg value for default award amount.
        """

        uda = self.bot.get_cog("UserDataAccessor")

        # get <general> channel id
        server_boost_channel = uda.get_designation_channel_id(
            str(self.bot.guild), "general"
        )

        # if no <general> zone/channel found
        if server_boost_channel in {None, ""}:
            raise RuntimeError("No #general channel ID returned or found.")

        # convert <general> channel id to discord.TextChannel
        server_boost_channel = self.bot.get_channel(int(server_boost_channel))
        if not server_boost_channel:
            raise RuntimeError("Could not retrieve #general TextChannel")

        # construct and send appreciation message -- regardless of points
        emoji_1 = ":smiling_face_with_3_hearts:"
        emoji_2 = ":dizzy:"
        thanks_msg = (
            f"Thank you so much {message.author.mention} "
            f"for boosting us!! {emoji_1}{emoji_2}"
        )
        success_msg = await server_boost_channel.send(thanks_msg)

        # fetch UDA (contains point-adding functions)
        uda = self.bot.get_cog("UserDataAccessor")
        if uda is None:
            print(
                "[point_system] ERROR: UDA is None. "
                "Could not give SERVER BOOST points."
            )
            return False

        # attempt to award user points
        resp = uda.ub_addpoints(
            None,
            None,
            "Points for boosting the server.",
            bank_amount=points,
            member=message.author,
        )

        # ERROR: if bad or nonexistent response, raise exception
        if (not resp) or (not resp.ok):
            raise RuntimeError(
                "HTTP response error while attempting to award server boost points."
            )

        # successful response: edit the bot's sent msg to
        # include wallet/points info
        msg_point_info = "\nWe added :euro:{points} to your wallet!"
        await success_msg.edit(content=f"{success_msg.content}{msg_point_info}")

        
    # ART-SHARING LOGIC -- insert into "on_message"
    #   - check: is art_gallery zone?
    #   - check: has an embed (image and/or video)?
    def award_art_message_points(self, message: discord.Message):
        """
        Award points to the author for posting artwork.

        Returns True if success, else False.
        """

        # print("in award_art_message_points()")

        uda = self.bot.get_cog("UserDataAccessor")
        if uda is None:
            print(
                "[point_system] ERROR: UDA is None. "
                "Could not give MESSAGE points."
            )
            return False

        gid = str(message.guild.id)
        chid = str(message.channel.id)
        
        # only award art points if channel is "art_zone"
        truth_table = {
            uda.is_channel("art_zone", gid, chid),
            len(message.attachments) > 0 and
            any([typ in message.attachments[0].content_type for typ in {"image", "video"}])
        }
        
        if (all(truth_table)):
            
            # posting art gives you a (FACTOR) point multiplier of 2x
            FACTOR = 2.0
            
            awarded_pts = FACTOR * uda.distributor.get_embed_points(
                message.embeds, uda.pt_flags
            )
            
            # getting points for attachments (non-embed)
            awarded_pts += uda.distributor.get_attachment_points(
                message.attachments, uda.pt_flags
            )

            # award the points
            uda.ub_addpoints(
                None,
                None,
                "Points for sharing artwork.",
                bank_amount=awarded_pts,
                member=message.author,
            )

            return True
        return False

        
    async def award_art_reaction_points(self, payload):
        """
        Award the author points for reactions on their artwork.

        Returns True if success, else False.
        """

        uda = self.bot.get_cog("UserDataAccessor")
        if uda is None:
            print(
                "[point_system] ERROR: UDA is None. "
                "Could not give ART REACTION points."
            )
            return False

        gid = str(payload.guild_id)
        chid = str(payload.channel_id)

        guild = self.bot.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)

        # only award art points if channel is "art_zone"
        res_1 = uda.is_channel("art_zone", gid, chid)
        res_2 = len(message.attachments) > 0
        res_3 = (
            (
                "image" in message.attachments[0].content_type
                or "video" in message.attachments[0].content_type
            )
            if res_2
            else False
        )

        if (
            uda.is_channel("art_zone", gid, chid)
            and (len(message.attachments) > 0)
            and (
                "image" in message.attachments[0].content_type
                or "video" in message.attachments[0].content_type
            )
        ):

            # get num. points allowed per user reaction
            FACTOR = 2.0
            reaction_points = FACTOR * uda.distributor.get_reaction_points()

            uda.ub_addpoints(
                None,
                None,
                "Author points for reaction added on their art.",
                bank_amount=reaction_points,
                member=message.author,
            )

            # print("award_art_reaction success")
            return True

        # print("award_art_reaction fail")
        return False

    # (EXTRA) ART-SHARING LOGIC
    #   - award extra points for every reply to the author's artwork
    def award_art_reply_points(self, message: discord.Message):
        """
        Give points to art piece author if someone replies to the art post.

        Returns True if success, else False.
        """

        #  _
        # /!\
        # NOTE:
        #   Current loophole/gap in logic is there is no mechanism
        #   to differentiate between actual art post and random image/video.
        #
        # SUGGESTED SOLUTION(S):
        #   1. Have art posts "verified" through some mechanism--manual
        #   or auto--that can be plugged in and checked here.

        # print("in award_art_reply_points()")

        uda = self.bot.get_cog("UserDataAccessor")

        if uda is None:
            print(
                "[point_system] ERROR: UDA is None. "
                "Could not give MESSAGE points."
            )
            return False

        gid = str(message.guild.id)
        chid = str(message.channel.id)

        # detect if channel is "art_zone"
        if not uda.is_channel("art_zone", gid, chid):
            return False

        # detect if message is reply
        replied_to_reference = message.reference
        replied_to = replied_to_reference.resolved if replied_to_reference else None
        if replied_to is None:
            return False

        # exit if reply source (msg being replied to) does not have img/video
        if len(replied_to.attachments == 0) or not (
            "image" in message.attachments[0].content_type
            or "video" in message.attachments[0].content_type
        ):
            return False

        # DEBUG
        # print("proceeding to award art reply points")

        # calculate award points (multiply by factor because special case)
        FACTOR = 2.0
        awarded_points = FACTOR * uda.distributor.get_points(replied_to, uda.pt_flags)

        # proceed to award points to author for receiving a reply
        uda.ub_addpoints(
            None,
            None,
            "Artist points--received art reply.",
            bank_amount=awarded_points,
            member=message.author,
        )

        # print("award_art_reply success")
        return True

    # (method) ON_MESSAGE POINT AWARDING
    def award_message_points(self, message: discord.Message):
        """
        Give (potential) points for a user's text message.

        Usually called by <on_message()>
        """

        if not message.author.bot:

            uda = self.bot.get_cog("UserDataAccessor")
            if uda:
                uda.givepoints(message)
            else:
                print(
                    "[point_system] ERROR: UDA is None. "
                    "Could not give MESSAGE points."
                )

    # (method) ON_RAW_REACTION_ADD POINT AWARDING
    async def award_reaction_points(
        self, payload, xp_on: bool = True, award_author: bool = False
    ):
        """
        Give (potential) points for a user's reaction add.
        """

        # "payload.member" only present w/REACTION_ADD event
        if (not payload.guild_id or not payload.member) or payload.member.bot:
            return

        guild = self.bot.get_guild(payload.guild_id)

        # check if the UDA module is loaded
        uda = self.bot.get_cog("UserDataAccessor")
        if not uda:
            print(
                (
                    "[point_system] ERROR: UDA is None. "
                    "Could not give REACTION points."
                )
            )
            return

        # get num. points allowed per user reaction
        reaction_points = uda.distributor.get_reaction_points()

        # (optional) IF <award_author>, get message author (discord.Member)
        msg_author = None
        if award_author:
            try:
                guild = self.bot.get_guild(payload.guild_id)
                channel = guild.get_channel(payload.channel_id)
                msg = await channel.fetch_message(payload.message_id)
                msg_author = msg.author

                # give points to message author
                uda.ub_addpoints(
                    None,
                    None,
                    "Points for reaction add.",
                    bank_amount=reaction_points,
                    member=msg_author,
                )

            except:
                traceback.print_exc()

        # update use points (and XP if applicable)
        if xp_on:
            uda.update("add", reaction_points, "xp", None, member=payload.member)
            if msg_author:
                uda.update("add", reaction_points, "xp", None, member=msg_author)

        await asyncio.sleep(4.0)

        uda.ub_addpoints(
            None,
            None,
            "Points for reaction add.",
            bank_amount=reaction_points,
            member=payload.member,
        )


def setup(bot):
    bot.add_cog(PointSystem(bot))
