import discord
from discord.ext import commands
import re
import typing
from cogs.globalcog import GlobalCog
from constants import roles
from utils.sync_utils import get_links
from urllib.parse import quote

# limit for batch deleting messages in channels
MESSAGE_PURGE_LIMIT = 100


class Messaging(commands.Cog, GlobalCog):
    """
    Commands related to messages.
    """

    def __init__(self, bot):
        self.bot = bot

    @commands.command("cc")
    @commands.cooldown(2, 5, commands.BucketType.member)
    @commands.has_role(roles.VERIFIED_MEMBER)
    @GlobalCog.no_points()
    async def cc(self, ctx, message: typing.Optional[discord.Message]):
        """
        Copies the specified message from a channel and sends it to you via direct message.

        You can either reply to the message you wish to CC or paste the link to the message as an argument.

        If you specify both, the replied to message will take precedence.

        Usage:
        !cc https://discord.com/channels/123/456/789
        """

        replied_to_reference = ctx.message.reference
        replied_to = replied_to_reference.resolved if replied_to_reference else None
        message_to_cc = replied_to or message

        # validations
        if not message_to_cc:
            # 1. message actually exists
            raise commands.CommandError("You didn't specify a valid message to CC.")
        elif isinstance(replied_to, discord.DeletedReferencedMessage):
            # 2. message has not been deleted
            raise commands.CommandError("The message you replied to has been deleted.")

        # 3. user can actually read the message
        origin_channel_permissions = message_to_cc.channel.permissions_for(ctx.author)

        if (
            not origin_channel_permissions.view_channel
            or not origin_channel_permissions.read_message_history
        ):
            raise commands.CommandError(
                "You do not have permissions to view this message."
            )

        # this will format the original content as a multiline quote
        # note that the jump_url cannot be followed by a colon otherwise the link will trigger a Discord.com preview
        cc_content = (
            f":memo: from **{message_to_cc.author}** on {message_to_cc.created_at.strftime('%c UTC')} ({message_to_cc.jump_url})\n"
            f">>> {message_to_cc.clean_content}"
        )
        await ctx.author.send(cc_content)

    @commands.command("purge")
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    @commands.guild_only()
    @commands.has_role(roles.ADMIN)
    @GlobalCog.no_points()
    async def purge(self, ctx, author: typing.Optional[discord.Member], limit: int = 1):
        """
        Deletes the most recent messages from the current channel.

        If a member is specified, only that member's messages will be deleted. This will not necessarily delete [limit] messages; instead, it scans the most recent messages and only deletes them if they were from the member.

        A maximum of 100 messages can be deleted at once. Note that the command message will not be deleted.

        Usage:
        !purge
        !purge 10
        !purge @BobTheBuilder
        !purge @BobTheBuilder 25
        """

        def is_target_member(m):
            return m.author == author if author else True

        await ctx.channel.purge(
            limit=min(limit, MESSAGE_PURGE_LIMIT),
            check=is_target_member,
            before=ctx.message,
        )

    @commands.command("share")
    @commands.cooldown(1, 10, commands.BucketType.member)
    @commands.guild_only()
    @commands.has_role(roles.VERIFIED_MEMBER)
    @GlobalCog.no_points()  # because separately awarded at the end
    async def share_resource(
        self,
        ctx,
        link: str,
        title: str,
        description: str,
        tags: str,
        img_url: typing.Optional[str] = None,
    ):
        """
        Use this command to format and share your content/resources!

        Recommended: Use the <description> to put link/key/code information if your file is encrypted.

        __**Parameters**__

        __link : str__
            A URL/link to a supported file host containing your content.
            Please see our info channels for info on supported file hosts!
            ONLY USE 1 LINK, OTHERWISE IT WILL NOT WORK.

        __title : str__
            The name of your content. PLEASE PUT "QUOTES" around name. For example:
            - "This Random Title"   (GOOD)
            - This Random Title     (BAD)

        __description : str__
            If no description, type "none" or "n/a".
            PLEASE PUT "QUOTES" around description.

        __tags : str__
            If no tags, type "none" or "n/a".
            If you want to add tags,use the format:
            - "tag1,tag2,...,tag"   (GOOD)
            - tag1,tag2,...,tag     (BAD)

        __img_url : str__
            (OPTIONAL) Add one (1) preview image to your post.
            MUST BE VALID URL.
            You can also UPLOAD AN IMAGE with the command.
            The uploaded image takes precedence over the <img_url>.

        Usage:
        !share https://mega.nz/0f983iqn3a "Title Here" "description here" "art,draw,2d" https://imgur.com/cover-art.png
        !share https://gofile.io/somefile "Title Here" none none
        !share https://gofile.io/somefile "Title Here" n/a n/a
        !share https://gofile.io/somefile "Title Here" none "art,reference,photoset"
        """

        # only allow execution in "share_zone" channels
        uda = self.bot.get_cog("UserDataAccessor")
        if not uda.is_channel("share_zone", str(ctx.guild.id), str(ctx.channel.id)):
            raise commands.CommandError("Command only allowed in a share zone.")

        # deprecated for now: "quote(str)" to sanitize string
        # parse and sanitize link/url
        link = link.replace(".", ". ").replace("://", ":// ")
        if len(get_links(link)) > 1:
            raise commands.CommandError(
                "Too many URLs detected. Please use only 1 URL."
            )

        # parse and sanitize title
        if len(get_links(title)) > 0 or '"' in title:
            raise commands.CommandError(
                "Invalid title. Make sure title is properly formatted."
            )

        # parse and sanitize description
        # if len(get_links(description)) > 0 or '"' in description:
        if '"' in description:
            raise commands.CommandError(
                "Invalid description. Make sure description is properly formatted."
            )
        if description in {"none", "n/a"}:
            description = None

        # parse and sanitize tags
        if tags not in {"none", "n/a"}:
            if len(get_links(tags)) > 0:
                raise commands.CommandError("No URLs allowed in tags. ")
            tags = tags.strip('"').split(",")
            tags = f"[{']['.join(tags)}]"  # [tag1][tag2][tag3]...

        # parse image url (sanitize if no attachment)
        if ctx.message.attachments is not None and len(ctx.message.attachments) > 0:
            img_url = ctx.message.attachments[0].url
        else:
            if img_url is not None:
                url_pattern = r"(?:http\:|https\:)?\/\/.*\.(?:png|jpg|webp|gif)"
                image = re.search(url_pattern, img_url)
                if image:
                    img_url = image.group(0)

        # create and package Embed:
        embed = discord.Embed(title=title, colour=discord.Colour.random())
        embed.add_field(name="link", value=f"||{link}||", inline=False)
        if description is not None:
            embed.add_field(name="DESCRIPTION", value=description, inline=False)
        if tags is not None:
            embed.add_field(name="TAGS", value=tags, inline=False)
        if img_url is not None and len(img_url) > 12:
            embed.set_image(url=img_url)
        embed.set_footer(text=f"Uploaded by {ctx.author}")
        embed.timestamp = ctx.message.created_at

        # send embed
        await ctx.send(embed=embed)

        # delete user command/msg (no longer needed)
        await ctx.message.delete()

        # (temporary solution for awarding points)
        # award extra points w/direct call here
        uda.ub_addpoints(
            None,
            None,
            "Points for sharing resource.",
            bank_amount=15.0,
            member=ctx.author,
        )


def setup(bot):
    bot.add_cog(Messaging(bot))
