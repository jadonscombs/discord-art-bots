import discord
from discord.ext import commands
from cogs.globalcog import GlobalCog
import datetime
import sys
import traceback
from utils.async_utils import react_success, react_fail


class Utility(commands.Cog, GlobalCog):
    """Kaede-specific command utilities."""

    def __init__(self, bot):
        self.bot = bot
        self.max_clearance_level = 25


def setup(bot):
    bot.add_cog(Utility(bot))
    print("[utility] cog loaded!")
