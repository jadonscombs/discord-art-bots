import discord
from discord.ext import commands
from cogs.globalcog import GlobalCog


class Statistics(commands.Cog, GlobalCog):
    """
    Stuff related to server statistics.
    """

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """
        Tracks reactions to messages within a guild context.
        """
        if not payload.guild_id or payload.member.bot:
            return

        accessor = self.bot.get_cog("UserDataAccessor")

        # increment reaction count for giver
        accessor.update("add", 1, "total_reactions_added", None, member=payload.member)

        # increment reaction count for receiver
        guild = self.bot.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        accessor.update("add", 1, "total_pos_reactions", message)

    @commands.Cog.listener()
    async def on_message(self, message):
        """
        Tracks messages within a guild context.
        """
        if message.guild is None:
            return

        accessor = self.bot.get_cog("UserDataAccessor")
        accessor.update("add", 1, "total_messages", message)


def setup(bot):
    bot.add_cog(Statistics(bot))
