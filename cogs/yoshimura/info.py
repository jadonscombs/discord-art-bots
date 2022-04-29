"""
General information-based operations requested by a user.
"""

import discord
from discord.ext import commands
import cogs.globalcog as globalcog
from cogs.globalcog import GlobalCog
import asyncio
import emojis
import random
import traceback

from utils.async_utils import react_success, react_fail


class Info(commands.Cog, GlobalCog):
    """Information/statistics tools and functionality"""

    def __init__(self, bot):
        self.bot = bot


def setup(bot):
    bot.add_cog(Info(bot))
