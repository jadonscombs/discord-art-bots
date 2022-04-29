import asyncio
import functools
import blop_tknloader as tknloader
import datetime
import discord
from discord.ext import commands
import json
import traceback
import os
import platform
import sys
import cogs.userdata_accessor
from cogs.userdata_accessor import UserDataAccessor
import time
import emojis
import logging

from utils.custom_help_command import CustomHelpCommand
from utils.async_utils import react_success, react_fail
from utils.sync_utils import create_prefixes_file, get_prefix, get_prefix_str

sys.path.append(os.path.join(os.getcwd(), "cogs"))

# experimental(?):
#   - supposedly a fix to error(s) when trying to restart bot
#   - the <misc_shared> module has this command
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# import cogs.task_scheduler

# setting new "Intents" variables
intents = discord.Intents.default()
intents.members = True
intents.reactions = True
intents.voice_states = True

# setting some bot properties
bot = commands.Bot(
    command_prefix=get_prefix, intents=intents, help_command=CustomHelpCommand()
)
content = ""

# list of cogs/extensions (e.g. markov.py, utility.py)
ext_list = [
    "cogs.userdata_accessor",
    "cogs.kaede.kaede_utility",
    "cogs.kaede.fun",
    "cogs.misc_shared",
    "cogs.messaging",
    "cogs.selection",
    "cogs.statistics",
]

# accessor object for sqlite data retrieval
accessor = None

# loop for point giving in 'on_message()'
loop = asyncio.get_event_loop()

# adding pre-compiled 'asyncio.coroutine' method for on_message() use
coroutine = asyncio.coroutine
escape_markdown = discord.utils.escape_markdown
run_in_executor = loop.run_in_executor
partial = functools.partial
update = None
givepoints = None
get_reaction_points = None
is_channel = None
designation_is_set = None
get_designation_channel_id = None


# tracking time-based variables (place somewhere else later)
# accessor.last_member_update = datetime.datetime.now()

# setup logging
logger = logging.getLogger("kaede")

if __name__ == "__main__":
    # print(os.getcwd())    # DIAGNOSTIC LINE

    for ext in ext_list:
        try:
            bot.load_extension(ext)
        except:
            print("[main] error loading {} extension.".format(ext))
            traceback.print_exc()

    # accessor object for sqlite data retrieval
    accessor = UserDataAccessor.accessor_mirror
    update = accessor.update
    givepoints = accessor.givepoints
    get_reaction_points = accessor.distributor.get_reaction_points
    is_channel = accessor.is_channel
    designation_is_set = accessor.designation_is_set
    get_designation_channel_id = accessor.get_designation_channel_id

"""============================================================================"""


@bot.event
async def on_ready():
    activity = discord.Game(name=f"@{bot.user.name} prefix!")
    await bot.change_presence(activity=activity, status=discord.Status.online)
    print("{}#{} is online now.".format(bot.user.name, bot.user.discriminator))


@bot.event
async def on_command_error(ctx, error):
    """
    Catches any fall-through errors, responds with an Embed containing the error message,
    and logs the error.
    """
    logger.error(error)

    if isinstance(error, commands.CommandNotFound):
        return
    embed = discord.Embed(colour=discord.Colour.red(), description=error)
    await ctx.reply(embed=embed)


@bot.event
async def on_help_command_error(ctx, error):
    return


@bot.event
async def on_guild_join(guild):
    # create prefix file if needed
    create_prefixes_file()

    with open("prefixes.json", "r") as f:
        prefixes = json.load(f)
    if "kaede" not in prefixes:
        prefixes["kaede"] = {}
    prefixes["kaede"] = "!"  # default prefix
    with open("prefixes.json", "w") as f:
        json.dump(prefixes, f, indent=4)


@bot.event
async def on_guild_remove(guild):
    # create prefix file if needed
    create_prefixes_file()

    with open("prefixes.json", "r") as f:
        prefixes = json.load(f)
    prefixes.pop("kaede", None)
    with open("prefixes.json", "w") as f:
        json.dump(prefixes, f, indent=4)


@bot.event
async def on_message(message):

    # soft-lock on Kaede; Kaede must wait for the DB to be created
    if (message.guild is not None) and (not accessor.db_exists(str(message.guild.id))):
        return

    # yield for process-heavy activity
    if accessor.long_process_active:
        return

    # do not process commands if bot is 'disabled';
    # only process if command is possibly <!enable>
    if accessor.disabled:
        if (len(message.clean_content.split()) == 1) and ("enable" in message.content):
            await bot.process_commands(message)

    if message.author.bot:
        # TODO: put extra logic here for kaede/yoshimura
        if message.content.find("No command called") != -1:
            try:
                await message.delete()
            except:
                pass
        return

    # retrieving guildID and userID
    gid = ""
    if isinstance(message.channel, discord.channel.TextChannel):
        gid = str(message.guild.id)
    uid = str(message.author.id)

    # initialize user if not added to db yet
    if not accessor.checking_user:
        accessor.checking_user = True
        accessor.check_user(gid, uid)
        accessor.checking_user = False
    else:
        # give time for checking_user process to finish
        await asyncio.sleep(0.3)

    # processing commands
    try:
        if not accessor.disabled:
            await bot.process_commands(message)
    except:
        return


@bot.event
async def on_member_join(member):
    """
    The primary action for Kaede is to:
        - send a DM to user on how to get started
        - TBD?
    """
    try:
        await accessor.kaede_entrance_routine(member)
    except:
        traceback.print_exc()


@bot.event
async def on_reaction_add(reaction, user):
    """
    Several actions may occur when a reaction is detected.
    """
    # gid = str(reaction.message.guild.id)
    pass


@bot.event
async def on_member_update(before, after):
    """
    Detect member role changes.
    """
    pass


@bot.event
async def on_member_remove(member):
    """
    Called when member leaves the server.
    """
    # TODO: -->  decide if/what member stats get deleted from database,
    #           as well as how leave/join rate are affected (server stat)
    pass


@bot.event
async def on_voice_state_update(member, prev, cur):
    """
    Called when there's an update in voice channel activity
    Currently, this event is used for the "!streamnotifs <on/off>" cmd
    """
    # print('[voice update] truth tables:')
    # print(f'\t>prev: stream={prev.self_stream}; connected={prev.channel}')
    # print(f'\t>cur: stream={cur.self_stream}; connected={cur.channel}')

    # ======================= stream-related handling logic =======================
    # =========== logic for notifying users when someone goes LIVE ================

    # if user started streaming AND they did not channel hop
    if (
        cur.self_stream and (prev.self_stream != cur.self_stream)
    ) and (  # user went !LIVE!
        (prev.channel is None) or (prev.channel == cur.channel)
    ):
        # see if anyone's (@streamnotif) subscribed to notifs first...
        notif_role = discord.utils.get(member.guild.roles, name="streamnotif")
        if notif_role:

            gid = str(member.guild.id)

            # check if the "stream_text" designation zone is set;
            # THIS DESIGNATION ZONE MUST BE SET IF USERS WANT TO GET @MENTIONED
            uda = bot.get_cog("UserDataAccessor")
            if uda.designation_is_set(gid, "stream_text"):

                # print("[kaede-on_voice_state_update] stream_text channel found.")

                try:
                    # check if user went LIVE recently; if YES, return (no spam notifs)
                    # prevent spam notifs. only send one if it's been a while
                    if not accessor.check_went_live_interval(
                        member, min_interval_sec=300
                    ):
                        return

                    # get designated channel (get first ID if there are multiple)
                    channel_id = get_designation_channel_id(gid, "stream_text")
                    # print(f"[kaede-on_voice_state_update] stream_text channel_id: {channel_id or ''}")

                    if channel_id and (channel_id not in {"", "n/a"}):
                        channel_id = channel_id.split(",")[0]

                        # print(f"[kaede-on_voice_state_update] parsed(0) channel_id: {channel_id or ''}")

                        channel = member.guild.get_channel(int(channel_id))

                        # send the notification + @mention message!
                        notif_msg = (
                            f"**{member.name}** just started streaming. "
                            f"Come watch! :partying_face:"
                        )
                        await channel.send(f"{notif_role.mention} {notif_msg}")

                        # print(f"[kaede-on_voice_state_update] notif msg sent.")

                except:
                    traceback.print_exc()

    # ============ LOGIC FOR UPDATING USER STREAM TIME ================
    # >>>   this section aims to track user's *total* streaming time
    #       when user STOPS streaming/going LIVE.
    if (not cur.self_stream and prev.self_stream) or (
        cur.self_stream and not cur.channel
    ):
        try:
            # get most recent stream "live" time, and stream "end" time
            time_now = datetime.datetime.now()
            last_went_live = accessor.get_last_live_time(member)

            last_went_live = datetime.datetime.strptime(
                last_went_live, "%m/%d/%Y %H:%M:%S"
            )

            # print( f'last_went_live: {last_went_live}' )

            # check if time delta is "significant" enough to record;
            # this will record in minutes
            diff = time_now - last_went_live
            total = diff.total_seconds()

            # print( f'seconds streamed: {total} ({total/60} mins.)' )

            if total > 60:
                t = round(total / 60, 1)
                # add stream time to the users' stats
                # stats: (num_times_streamed, total_time_streamed)
                update("add", t, "total_time_streamed", None, member=member)
                update("add", 1, "num_times_streamed", None, member=member)

            # now award points for streaming (if applicable)
            accessor.award_stream_points(total, member)

        except:
            traceback.print_exc()


# !STARTING UP THE BOT!
bot.run(tknloader.bot_token("Kaede"))
