import discord
from discord.ext import commands

try:
    import cogs.globalcog as globalcog
    from cogs.globalcog import GlobalCog
except:
    import globalcog
    from globalcog import GlobalCog

import asyncio
import emojis
import json
import os
import random
import signal
import traceback
import typing

from utils.sync_utils import create_prefixes_file, get_prefix_str
from utils.async_utils import react_success


class MiscShared(commands.Cog, GlobalCog):
    """Uncategorized shared commands between Kaede and Yoshimura"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command("reboot", hidden=True)
    @commands.is_owner()
    @commands.cooldown(1, 10, commands.BucketType.default)
    async def reboot(self, ctx):
        """Reboots the bot."""
        try:
            await self.bot.change_presence(status=discord.Status.offline)
            await asyncio.sleep(0.5)
            await self.bot.close()
            signal.signal(signal.SIGQUIT, signal.SIG_DFL)
            os.kill(os.getpid(), signal.SIGQUIT)
        except Exception as e:
            await self.bot.change_presence(status=discord.Status.online)
            raise commands.CommandError(f"Failed to reboot: {e}")

    @commands.command("disable", hidden=True)
    @commands.is_owner()
    @commands.cooldown(1, 9, commands.BucketType.default)
    async def disable(self, ctx):
        """
        Similar effect to shutting down the bot.

        Bot cannot respond to any **other** command until it is re-enabled
        Usage:
        (via mention)   @Kaede/@Yoshimura disable
        (standard)      !disable
        """
        # 'bot already disabled'
        if self.accessor_mirror.disabled:
            return await react_success(ctx)

        # var update for 'bot disabled'
        self.accessor_mirror.disabled = True

        # prepare and send embed
        embed = discord.Embed(
            description="Bot disabled.", colour=discord.Colour.greyple()
        )
        return await ctx.reply(embed=embed)

    @commands.command("enable", hidden=True)
    @commands.is_owner()
    @commands.cooldown(1, 9, commands.BucketType.default)
    async def enable(self, ctx):
        """
        (re)enables bot if disabled.

        Usage:
        (via mention)   @Kaede/@Yoshimura enable
        (standard)      !enable
        """
        # 'bot already enabled'
        if not self.accessor_mirror.disabled:
            return await react_success(ctx)

        # var update for 'bot enabled'
        self.accessor_mirror.disabled = False

        # prepare and send embed
        embed = discord.Embed(description="Bot enabled.", colour=discord.Colour.green())
        return await ctx.reply(embed=embed)

    def resolve_ext_path(self, ext: str):
        """
        Return correct dot (.) notation path for extension <ext>.
        """
        cwd = os.getcwd()

        if os.path.isfile(os.path.join(cwd, ext + ".py")):
            return ext
        if os.path.isfile(os.path.join(cwd, "cogs", ext + ".py")):
            return f"cogs.{ext}"

        # resolve by bot_name
        bot_name = self.bot.user.name.lower()
        if os.path.isfile(os.path.join(cwd, "cogs", bot_name, ext + ".py")):
            return f"cogs.{bot_name}.{ext}"

        # if we can't resolve the name, just pass it through as is
        return ext

    @commands.group("ext", hidden=True)
    @commands.guild_only()
    @GlobalCog.set_clearance(9)
    async def ext(self, ctx):
        if ctx.invoked_subcommand is None:
            pass
            # await ctx.message.delete( delay=3.0 )

    @ext.command("reload", aliases=["re"], hidden=True)
    @commands.guild_only()
    @GlobalCog.set_clearance(9)
    async def reload_ext(self, ctx, ext: str):
        """
        Reload one of the bot's extensions.

        Usage:
        !ext reload dot.separated.extension.path
        !ext re dot.separated.extension.path
        """
        try:
            self.bot.reload_extension(self.resolve_ext_path(ext))
            await react_success(ctx)
        except commands.ExtensionError as e:
            raise commands.CommandError(f"Failed to reload extension: {e}")

    @ext.command("load", aliases=["ld"], hidden=True)
    @commands.guild_only()
    @GlobalCog.set_clearance(9)
    async def load_ext(self, ctx, ext: str):
        """
        Load one of the bot's extensions.

        Usage:
        !ext load dot.separated.extension.path
        !ext ld dot.separated.extension.path
        """
        try:
            self.bot.load_extension(self.resolve_ext_path(ext))
            await react_success(ctx)
        except commands.ExtensionError as e:
            raise commands.CommandError(f"Failed to load extension: {e}")

    @ext.command("unload", aliases=["ul"], hidden=True)
    @commands.guild_only()
    @GlobalCog.set_clearance(9)
    async def unload_ext(self, ctx, ext: str):
        """
        Unload one of the bot's extensions.

        Usage:
        !ext unload dot.separated.extension.path
        !ext ul dot.separated.extension.path
        """
        try:
            self.bot.unload_extension(self.resolve_ext_path(ext))
            await react_success(ctx)
        except commands.ExtensionError as e:
            raise commands.CommandError(f"Failed to unload extension: {e}")

    @commands.command("relay")
    @commands.has_permissions(administrator=True)
    async def relay(self, ctx, channel: discord.TextChannel, *, message):
        """
        Have the bot send a message FOR YOU, to the channel you choose.

        Usage:
        !relay <guild_id>:<channel_id> your message here
        !relay 089435034:99391055523 your message here
        !relay #channel_mention ANNOUNCEMENT: Today is the day!
        """
        # TODO: add support for adding embedded images/media (e.g. via DM message ID)
        # TODO: add <use_embed> option if sender wants the relayed msg inside an embed
        # TODO: add support for potentially extracting message from a message link
        # check if issuing user is part of the guild the provided channel is in
        if channel.guild.get_member(ctx.author.id) is None:
            raise commands.CommandError(
                "You must be a member of this guild to relay a message."
            )

        # check if issuing user has permission to view the specified text channel
        issuer_perms = channel.permissions_for(ctx.author)
        if not issuer_perms.view_channel or not issuer_perms.read_message_history:
            raise commands.CommandError(
                "You do not have permissions to view this channel."
            )

        await channel.send(message)
        await react_success(ctx)

    @commands.command("react")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def react(self, ctx, emoji, msg: discord.Message):
        """
        Attach an <emoji> to the specified <msg>.

        Usage:
        !react :paintbrush: 023805712532155
        !react :paintbrush: https://discord.com/channels/111/222/333
        """
        await msg.add_reaction(str(emoji))

    @commands.command("prefix")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def prefix(self, ctx, new_prefix: typing.Optional[str]):
        """
        Set or view current prefix for this bot.

        <new_prefix>:   (optional) new prefix to set for this bot

        Usage:
            SET PREFIX:     "!prefix 'your_prefix?!'"
            VIEW CURRENT:   "!prefix"
        """
        # case: display current prefix
        if new_prefix is None:
            current_prefix = get_prefix_str(self.bot, ctx.message)

            embed = discord.Embed(
                description=f"Current prefix: `{current_prefix}`", colour=0xFFC02E
            )  # construction yellow
            return await ctx.reply(embed=embed)

        # case: set new prefix
        if len(new_prefix) < 4:
            create_prefixes_file()
            with open("prefixes.json", "r") as f:
                prefixes = json.load(f)

            # add new prefix entry and save
            prefixes[self.bot.user.name.lower()] = new_prefix

            with open("prefixes.json", "w") as f:
                json.dump(prefixes, f, indent=4)

            # update bot activity now
            new_status = discord.Game(name=f"{new_prefix}help")
            await self.bot.change_presence(activity=new_status)
            embed = discord.Embed(
                description=f"New prefix set to {new_prefix}.",
                colour=discord.Colour.green(),
            )
            await ctx.reply(embed=embed)
        else:
            embed = discord.Embed(
                description="Prefix is too long.", colour=discord.Colour.red()
            )
            await ctx.reply(embed=embed)

    @commands.command("change_outfit", aliases=["change"], hidden=True)
    @commands.guild_only()
    @commands.cooldown(2, 10, commands.BucketType.default)
    @GlobalCog.set_clearance(7)
    async def change_outfit(self, ctx, mode="normal"):
        """
        Manually make the bot switch outfits (outside scheduled times).

        <mode>(optional):   One of "normal" (default), or "sleep".

        Usage:
        !change
        !change sleep
        """
        if mode not in {"normal", "sleep"}:
            return

        # get correct file path
        bot_name = self.bot.user.name.lower()
        # bot_name = 'kaede'
        img_dir = os.path.join(os.getcwd(), "pfp", bot_name)

        # choose random image
        img_path = None
        if mode == "normal":
            files = os.listdir(img_dir)
            img_path = os.path.join(img_dir, random.choice(files))

        # or choose sleep image (currently only 1 sleep image)
        elif mode == "sleep":
            img_path = os.path.join(img_dir, f"{bot_name}-sleep1.png")

        # set new profile pic
        with open(img_path, "rb") as pfp:
            pfp = pfp.read()

            try:
                await self.bot.user.edit(avatar=pfp)
            except discord.DiscordException as e:
                raise commands.CommandError(f"Failed to set bot avatar: {e}")

        embed = discord.Embed(
            description="Outfit changed successfully.", colour=discord.Colour.green()
        )
        await ctx.reply(embed=embed)

    @commands.command("showhidden", aliases=["hiddencommands"], hidden=True)
    @GlobalCog.set_clearance(9)
    async def showhidden(self, ctx):
        """Display all hidden commands."""
        hiddenlist = []
        append = hiddenlist.append
        prefix = get_prefix_str(self.bot, ctx.message)

        # iterate over cogs
        for cog in self.bot.cogs:
            cmdlist = []

            # iterate over commands
            for cmd in self.bot.cogs[cog].get_commands():
                if cmd.hidden:
                    cmdlist.append(cmd)
            if len(cmdlist) != 0:
                append(f"[{cmdlist[0].cog_name}]:")
                for c in cmdlist:
                    append(prefix + c.name)
                append("\n")

        # print only if hidden commands were found
        if len(hiddenlist) > 0:
            output = "\n```{}```".format("\n".join(hiddenlist))
            await ctx.reply(f"hidden commands:{output}")


def setup(bot):
    bot.add_cog(MiscShared(bot))
    print("[misc_shared] cog loaded!")


if __name__ == "__main__":
    try:
        print("Loading misc_shared cog!")
    except:
        traceback.print_exc()
