import discord
from discord.ext import commands


class CustomHelpCommand(commands.MinimalHelpCommand):
    EMBED_ICON_URL = "https://i.imgur.com/v4MQk41.png"

    async def send_pages(self):
        destination = self.get_destination()
        num_pages = len(self.paginator.pages)

        for index, page in enumerate(self.paginator.pages, start=1):
            embed = discord.Embed(
                colour=discord.Colour.blurple(), description=page
            ).set_thumbnail(url=self.EMBED_ICON_URL)

            if num_pages > 1:
                embed.set_footer(text=f"Page {index}/{num_pages}")

            await destination.send(embed=embed)

    def get_command_signature(self, command):
        return f"**{self.clean_prefix}{command.qualified_name} {command.signature}**"

    def add_aliases_formatting(self, aliases):
        self.paginator.add_line(
            f"{self.aliases_heading} {', '.join(aliases)}", empty=True
        )
