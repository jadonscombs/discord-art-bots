from cogs.userdata_accessor import UserDataAccessor
from discord.ext import commands
from utils.custom_help_command import CustomHelpCommand
from utils.sync_utils import create_prefixes_file, get_prefix
import asyncio
import blop_tknloader as tknloader
import datetime
import discord
import functools
import json
import logging
import os
import platform
import sys
import traceback

# if needed, set Win. policy (global per-process event loop manager);
# see more: https://docs.python.org/3.7/library/asyncio-policy.html
# note: fixes error(s) when restarting the bot
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# setting new "Intents" variables
intents = discord.Intents.default()
intents.members = True
intents.reactions = True
intents.voice_states = True

# setting some bot properties
bot = commands.Bot(
    command_prefix=get_prefix,
    intents=intents,
    help_command=CustomHelpCommand()
)
content = ""

# list of cogs/extensions (e.g. markov.py, utility.py)
ext_list = {
    "cogs.userdata_accessor",
    "cogs.kaede_utility",
    "cogs.fun",
    "cogs.misc_shared",
    "cogs.messaging",
    "cogs.selection",
    "cogs.statistics"
}

# accessor object for sqlite data retrieval
accessor = None

# loop for point giving in 'on_message()'
loop = asyncio.get_event_loop()

# adding pre-compiled method declarations/vars
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


# setup event log for kaede
logger = logging.getLogger("kaede")


if __name__ == "__main__":

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


@bot.event
async def on_ready():
    activity = discord.Game(name=f"@{bot.user.name} prefix!")
    await bot.change_presence(activity=activity, status=discord.Status.online)
    print(f"{bot.user.name}#{bot.user.discriminator} is online now.")


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
    if (
        (message.guild is not None) and 
        (not accessor.db_exists(str(message.guild.id)))
    ):
        return

    # yield for process-heavy activity
    if accessor.long_process_active:
        return

    # do not process commands if bot is 'disabled';
    # only process if command is <!enable>
    if accessor.disabled:
        if (
            (len(message.clean_content.split()) == 1) and
            ("enable" in message.content)
        ):
            await bot.process_commands(message)

    if message.author.bot:
        # ignore command error msg. to avoid bandwidth pollution
        if message.content.find("No command called") != -1:
            try:
                await message.delete()
            except:
                pass
        return

    # retrieving guildID and userID
    uid = str(message.author.id)
    if message.guild is not None:
        gid = str(message.guild.id)
        
        # if system is NOT checking user's entry in DB...
        if not accessor.checking_user:
        
            # attempt to add DB entry for user
            accessor.check_user(gid, uid)
        else:
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
    Actions to take when new user joins the servers.
    """
    try:
        # send user a welcome message with verification instructions
        await accessor.kaede_entrance_routine(member)
    except:
        traceback.print_exc()


@bot.event
async def on_reaction_add(reaction, user):
    """
    Several actions may occur when a reaction is detected.
    """
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


# !STARTING UP THE BOT!
bot.run(tknloader.bot_token("Kaede"))
