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

# list of cogs/extensions
ext_list = [
    "cogs.userdata_accessor",
    "cogs.info",
    "cogs.yoshimura_utility",
    "cogs.task_scheduler",
    "cogs.misc_shared",
    "cogs.transactions",
    "cogs.verification",
    "cogs.point_system"
]

# accessor object for sqlite data retrieval
accessor = None

# loop for point giving in 'on_message()'
loop = asyncio.get_event_loop()

# adding pre-compiled 'asyncio.coroutine' method
# (and others) for on_message() use
coroutine = asyncio.coroutine
escape_markdown = discord.utils.escape_markdown
run_in_executor = loop.run_in_executor
partial = functools.partial
update = None
givepoints = None
get_reaction_points = None
designation_is_set = None
get_designation_channel_id = None
is_channel = None


# tracking time-based variables (place somewhere else later)
# accessor.last_member_update = datetime.datetime.now()

# setup logging
logger = logging.getLogger("yoshimura")

if __name__ == "__main__":
    # print(os.getcwd())    # DIAGNOSTIC LINE

    for ext in ext_list:
        try:
            bot.load_extension(ext)
        except Exception as e:
            print("[main] error loading {} extension.".format(ext))
            traceback.print_exc()

    # accessor object for sqlite data retrieval
    accessor = UserDataAccessor.accessor_mirror
    update = accessor.update
    givepoints = accessor.givepoints
    get_reaction_points = accessor.distributor.get_reaction_points
    designation_is_set = accessor.designation_is_set
    get_designation_channel_id = accessor.get_designation_channel_id
    is_channel = accessor.is_channel


"""============================================================================"""


@bot.event
async def on_ready():
    activity = discord.Game(name=f"@{bot.user.name} prefix!")
    await bot.change_presence(activity=activity, status=discord.Status.online)
    print("{}#{} is online now.".format(bot.user.name, bot.user.discriminator))


@bot.event
async def on_command_error(ctx, error):
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
    if "yoshimura" not in prefixes:
        prefixes["yoshimura"] = {}
    prefixes["yoshimura"] = "!"  # default prefix
    with open("prefixes.json", "w") as f:
        json.dump(prefixes, f, indent=4)


@bot.event
async def on_guild_remove(guild):
    # create prefix file if needed
    create_prefixes_file()

    with open("prefixes.json", "r") as f:
        prefixes = json.load(f)
    prefixes.pop("yoshimura", None)
    with open("prefixes.json", "w") as f:
        json.dump(prefixes, f, indent=4)


@bot.event
async def on_message(message):
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

    is_guild = message.guild is not None

    # retrieving guildID and userID
    gid = None
    if is_guild:
        gid = str(message.guild.id)
    uid = str(message.author.id)

    # initialize user if not added to db yet
    if is_guild and not accessor.checking_user:
        accessor.check_user(gid, uid)
    else:
        # give time for checking_user process to finish
        await asyncio.sleep(0.3)

    # processing commands
    try:
        if not accessor.disabled:
            await bot.process_commands(message)
    except:
        return

    # COMMENTED OUT FOR POINT_SYSTEM
    # giving points
    # try:
    #    if not bot.is_closed():
    #        await run_in_executor(None, partial(givepoints, message))
    # except: traceback.print_exc()

    # terminal update (stats on the message author)
    if is_guild:
        accessor.print_table(gid, uid)


@bot.event
async def on_member_join(member):
    """
    The primary action here is to:
        - create database entry for the new member
        - add member to a list of UNVERIFIED users
        - ALSO: update join rate??
    """
    try:
        # [YOSHIMURA ACTION] add user to the database (and unverified list)
        accessor.ADD_USER(str(member.guild.id), str(member.id))

    except:
        traceback.print_exc()


@bot.event
async def on_raw_reaction_add(payload):
    """
    Several actions may occur when a reaction is detected.
    """

    if payload.guild_id:
        gid = str(payload.guild_id)
    uid = str(payload.user_id)
    if payload.guild_id:
        guild = bot.get_guild(payload.guild_id)
    if payload.member:
        member = payload.member

    # [YOSHIMURA ACTION][LAST ACTION TO OCCUR FOR THE <on_raw_reaction_add()> EVENT]
    # give user points for adding a reaction
    if not guild:
        guild = bot.get_guild(payload.guild_id)

    if not member:
        member = guild.get_member(payload.user_id)

    if not member.bot:

        # add member to DB if they're not already in
        accessor.check_user(gid, uid)

        # COMMENTED OUT FOR POINT_SYSTEM
        # give user xp/points for reaction
        # reaction_points = get_reaction_points()
        # update("add", reaction_points, "xp", None, member=member)
        # accessor.ub_addpoints(
        #    None,
        #    None,
        #    "Points for reaction add.",
        #    bank_amount=reaction_points,
        #    member=member
        # )


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
    try:
        if member.bot:
            return
    except:
        traceback.print_exc()

    accessor.DELETE_USER(str(member.guild.id), str(member.id))


# !STARTING UP THE BOT!
bot.run(tknloader.bot_token("Yoshimura"))
