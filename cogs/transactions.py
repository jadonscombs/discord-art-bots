import discord
from discord.ext import commands
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
import argparse
import datetime
from datetime import timezone
import os
import re
import requests
import sqlite3
import subprocess
import sys
import traceback
import typing
from typing import Optional
from constants.values import UB_ID
from cogs.globalcog import GlobalCog
from utils.async_utils import react_success, react_fail
from utils.sync_utils import ub_get, ub_put, ub_patch
import uuid


sql3_connect = sqlite3.connect


class Transactions(commands.Cog, GlobalCog):
    """
    Commands related to transactions (e.g. for books, resources, etc.)
    """

    MAX_RESOURCE_ID_LEN = 80
    folder = "logs_assets"
    folder_path = os.path.join(folder, "store_assets")
    table_info = {
        "Transactions": {
            "id": {"value": "?", "type": "text"},
            "date": {"value": "?", "type": "text"},
            "user": {"value": "?", "type": "text"},
            "resource_id": {"value": "?", "type": "text"},
            "amount": {"value": 0, "type": "real"},
        },
        "Resources": {
            "id": {"value": "?", "type": "text"},
            "name": {"value": "?", "type": "text"},
            "link": {"value": "?", "type": "text"},
        },
    }

    # [regex pattern] detect a successful purchase
    purchase_pattern = "(.*You have bought \d+ .+ for)"

    # [regex pattern] parse item name info
    item_pattern = "bought \d+ .+ for"

    # [regex pattern] parse item tags info
    tag_pattern = "\[[^\[\]]+\]"

    password_prefix = ">>"

    # resource confirmation string:
    # (used when sending resources/resource links to customers)
    resource_confirmation_template = (
        "[EdenGenesis][Transaction ID: {}]\n\n"
        "Your order (**{}**) has been prepared! :blush:\n\n"
        "**Enjoy!"
    )

    def __init__(self, bot):
        self.bot = bot
        self.transactionfile_fmt = "{}_logs_assets.sqlite3"

        # pre-compile parsers for event listeners
        self.purchase_parser = re.compile(self.purchase_pattern)
        self.item_parser = re.compile(self.item_pattern)
        self.tag_parser = re.compile(self.tag_pattern)

        # NOTE: <fetch_member()> is ASYNC (use await when calling)
        self.member_fetcher = commands.MemberConverter()
        self.fetch_member = self.member_fetcher.convert

        self.create_logfolder()

    def head(self, f, n):
        """
        Helper method to RETURN the FIRST <n> lines from a text (log) file.

        [resource(s)]:
        stackoverflow.com/questions/1767513
        """
        with open(f) as logfile:
            entries = []
            append = entries.append
            try:
                for _ in range(n):
                    entry = next(logfile)
                    append(entry)
            except StopIteration:
                pass
            return [self.logfile_header] + entries

    def tail(self, f, n, offset=0):
        """
        Helper method to RETURN the LAST <n> lines from a text (log) file.

        [resource(s)]:
        stackoverflow.com/questions/136168 (subprocess tail method)
        stackoverflow.com/questions/2301789 (generator seek method)
        """

        # TODO: REWRITE THIS TO WORK LIKE "HEAD" WORKS
        # with open(f, "rb") as logfile:

        # buf_size = 8192
        # entry = None

        # logfile.seek(0, os.SEEK_END)            # move file cursor to EOF
        # fsize = remaining_size = logfile.tell() # init. remaining file bytes to parse

        # # TODO: PROVIDE EXPLANATION OF FILE SEEK/BUFFER OPERATION LOGIC
        # while remaining_size > 0:

        # offset = min(fsize, offset + buf_size)
        # logfile.seek(fsize - offset)
        # buf = logfile.read(min(remaining_size, buf_size))
        # remaining_size -= buf_size
        # lines = buf.split("\n")

        # if entry is not None:
        # if buf[-1] != "\n":
        # lines[-1] += entry
        # else:
        # yield entry
        # entry = lines[0]
        # for i in range(len(lines) - 1, 0, -1):
        # if lines[i]:
        # yield lines[i]

        # if entry is not None:
        # yield entry

        proc = subprocess.Popen(
            ["tail", "-n" + str(n + offset), f], stdout=subprocess.PIPE
        )
        lines = proc.stdout.readlines()
        lines = [str(line, "utf-8") for line in lines]
        return [self.logfile_header] + lines

    def create_logfolder(self):
        """
        Create the directory for transaction/resource logs.
        """

        # <self.folder> is base directory
        if not os.path.isdir(self.folder):
            os.makedirs(self.folder, exist_ok=True)

        # <self.folder>/<f1> is the directory for store-related logs
        if not os.path.isdir(self.folder_path):
            os.makedirs(self.folder_path, exist_ok=True)

    def create_log_db(self, gid: str, checked: bool = False):
        """
        Create the DB primarily for hosting Transaction and Resource information.

        NOTE: context/guild-based call.
        """
        if not checked:
            self.create_logfolder()

        newpath = os.path.join(self.folder_path, self.transactionfile_fmt.format(gid))

        print(f"[create_log_db] fpath={newpath}")

        # create new db if needed (and tables)
        if not os.path.isfile(newpath):
            print("[create_log_db] DB file not found. proceeding with DB creation")

            with sql3_connect(newpath) as conn:

                cur = conn.cursor()

                # create 1 table at a time (see <self.table_info>)
                cmd = "CREATE TABLE {}({});"

                header = None

                print("[create_log_db] creating all tables now...")

                # 1 iteration + execution per table
                for table, attribs in self.table_info.items():

                    print(f"[create_log_db] current table={table}")

                    # get table attribs/cols/headers
                    header = [a for a in attribs]
                    s = "{} {} PRIMARY KEY".format(
                        header[0], attribs[header[0]]["type"]
                    )

                    # complete string formatting
                    for h in header[1:]:
                        s += ", {} {}".format(h, attribs[h]["type"])

                    # insert string in <cmd>, then execute
                    cur.execute(cmd.format(table, s))

                conn.commit()

                print("[create_log_db] finished creating tables")

        print("[create_log_db] DB was found, returning connection now.")
        return sql3_connect(newpath)

    def connect(self, gid: str):
        """
        Return sqlite3 connection to the associated guild's <gid> database.
        """
        gid = str(gid)

        db_path = os.path.join(self.folder_path, self.transactionfile_fmt.format(gid))

        if not os.path.isfile(db_path):
            print("[self.connect]: no DB found. now creating new DB...")
            return self.create_log_db(gid)
            print("[self.connect]: finished creating new DB")

        # print("[self.connect]: existing DB found, returning connection.")
        return sql3_connect(db_path)

    def add_log_entry(
        self,
        gid: str,
        user: discord.User,
        resource_id: str,
        amount: float,
    ):
        """
        Primary method of adding a transaction log entry.

        See <self.table_info> for details on information logged.

        Attribs "date" and "id" are generated within this method if no arguments given.

        Order of information must match order of attribs for the associated table in <self.table_info>
        """

        try:
            date = datetime.datetime.now(timezone.utc)
            date = date.strftime("%Y:%m:%d-%H:%M:%S-%Z")
            id_ = uuid.uuid4()

            with self.connect(gid) as conn:

                # write log entry
                cmd = "INSERT INTO Transactions VALUES (?,?,?,?,?)"
                cur = conn.cursor()
                cur.execute(
                    cmd, (id_, date, f"{user.id} ({user.name})", resource_id, amount)
                )
                conn.commit()

        except:
            traceback.print_exc()

    def add_resource_entry(self, gid, resource_id, name, link):
        """
        Add resource entry into Resources table.

        "name" is the name of the resource.
        """
        try:
            with self.connect(gid) as conn:

                # write resource entry
                cmd = "INSERT INTO Resources VALUES (?, ?, ?)"
                cur = conn.cursor()
                cur.execute(cmd, (resource_id, name, link))
                conn.commit()

        except:
            traceback.print_exc()
            raise RuntimeError("Could not add the specified resource to the database.")

    def remove_resource_entry(self, gid, resource_id):
        """
        Remove resource entry from DB if it exists.
        """
        try:
            with self.connect(gid) as conn:
                cmd = f"DELETE FROM Resources WHERE id=?"
                cur = conn.cursor()
                cur.execute(cmd, (resource_id,))
                conn.commit()

        except:
            traceback.print_exc()
            raise RuntimeError(
                "Could not remove the specified resource from the database."
            )

    def resource_exists(self, gid, resource_id):
        """
        Return True if specified resource <resource_id> exists in the DB.
        """
        with self.connect(gid) as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM Resources WHERE id=?", (resource_id,))
            data = cur.fetchone()[0]
            return (data is not None) and (data != 0)

    def get_resource(self, gid, resource_id, property: Optional[str] = "link"):
        """
        Return the link associated with a given resource <resource_id>.

        Valid <property> values:
            - "basic" (provides resource's ID and name)
            - "link", "name", "id" (any attrib. in <table_info["Resources"]>)
        """

        # print(f"[get_resource]\n\ttarget ID: {resource_id}\n\ttarget property: {property}")

        # create correct command to execute
        cmd = ""
        if property == "link":
            cmd = "SELECT link FROM Resources WHERE id=?"
        else:
            if property in self.table_info["Resources"]:
                cmd = f"SELECT {property} FROM Resources WHERE id=?"

            elif property == "basic":
                cmd = "SELECT id,name FROM Resources WHERE id=?"

        # execute and return data
        with self.connect(gid) as conn:
            cur = conn.cursor()
            cur.execute(cmd, (resource_id,))
            result = cur.fetchone()

            # parent calling methods will check value
            if result is None:
                return result

            # print(f"[get_resource] fetched result:\n{result}\n")

            if property != "basic":
                return result[0]
            return " - ".join(result)

    def get_all_resources(self, gid):
        """
        Retrieve all resource entries in the DB. Will only yield basic info (excludes link).
        """
        with self.connect(gid) as conn:
            cmd = "SELECT id,name FROM Resources"
            cur = conn.cursor()
            cur.execute(cmd)
            return cur.fetchall()

    def update_resource_property(
        self, gid, resource_id, property, value, checked=False
    ):
        """
        Update resource entry in DB with specified property and value.

        Set <checked> to True if entry validation was already performed.
        """
        if not checked and not self.resource_exists(gid, resource_id):
            raise Exception("No entry found for requested resource.")

        if property not in self.table_info["Resources"]:
            raise ValueError("Invalid resource property.")

        with self.connect(gid) as conn:
            cmd = f"UPDATE Resources SET {property}=? where id=?"
            cur = conn.cursor()
            cur.execute(cmd, (value, resource_id))
            conn.commit()

    def resource_link_retrieval_err_embed(self, resource_id, customer: discord.User):
        """
        [helper method]

        Return a discord.Embed object with info stating resource link could not be retrieved.
        """

        customer = "you" if customer is None else customer.mention

        description = (
            f"Could not retrieve resource [{resource_id}] for {customer}. "
            "Please keep record of this and notify an admin to "
            "ensure you receive your purchased item."
        )
        e = discord.Embed(description=description, colour=discord.Colour.red())
        if isinstance(customer, discord.User):
            e.set_author(name=customer.display_name, icon_url=customer.avatar_url)

        return e

    def resource_purchase_embed(
        self, resource_name, resource_link, transaction_id, customer: discord.User
    ):
        """
        [helper method]

        Return a formatted discord.Embed object w/info on buyer, transaction ID & resource link.

        This embed object is intended to be sent to a user to deliver their purchased resource.
        """

        # for security reasons, dots (.) in URLs are replaced with "[.]"
        pw = None
        if self.password_prefix in resource_link:
            resource_link, pw = resource_link.split(self.password_prefix)
            pw = pw.strip('"')

        # check if resource link is a URL (plaintext);
        # if URL detected, <resource_link> gets formatted
        # try:
        # resp = requests.get(resource_link)
        resource_link = resource_link.replace(".", "[.]")
        resource_link = resource_link.replace("://", ":// ")
        resource_link = resource_link.strip('"')
        # except requests.ConnectionError:
        #    pass

        description = (
            f"Hi {customer.name}, your order " f"has been prepared. Enjoy! :blush:\n⠀"
        )

        notice_info = (
            f"**DO NOT SHARE** this resource with "
            f"anyone or outside the server. This is only for your use. "
            f"If you enjoyed this resource, go support the author/artist!\n⠀"
        )

        link_info = (
            f"**LINK:** || {resource_link} ||\n"
            f"**PASS:** || {'(No Password)' if pw is None else pw} ||\n\n"
            f"__Helpful Tips:__\n"
            f"> - You may need to decode the link AND/OR password\n"
            f"> - Visit our FAQ/instructions on decoding for more info\n"
            f"> - Replace any `[.]` with `.`\n⠀"
        )

        footer_info = (
            f"Transaction ID: {transaction_id}\n" f"Customer ID: {customer.id}"
        )

        e = discord.Embed(
            title="[EdenGenesis] Purchase Delivery!",
            description=description,
            colour=discord.Colour.green(),
        )
        e.add_field(name=f"{resource_name}", value=link_info, inline=False)
        e.add_field(name=":warning: NOTICE :warning:", value=notice_info, inline=False)
        e.set_footer(text=footer_info)

        return e

    def find_resource_info_route1(self, s: str):
        """
        IMPORTANT: CURRENTLY UNUSED ROUTE. PLEASE SEE THE
        <find_resource_info_route2(...)> METHOD INSTEAD.

        Return a tuple (resource_id, resource_name) after parsing <s>.

        <s> is assumed to have the form:
            "You have bought <N> <item_name> [<resource_id>] for [. . .]"
        """

        try:
            name_start = s.find("t") + 4
            id_start = s.find("[") + 1
            name_end = name_start - 2
            id_end = s.find("]")

            resource_id = s[id_start:id_end]
            resource_name = s[name_start:name_end]
            return (resource_id, resource_name)

        except:
            traceback.print_exc()
            return None

    def find_resource_info_route2(self, s: str):
        """
        Return a STRING (resource_id) after parsing <s>.

        <s> is assumed to have the form:
            "<@customer_mention> You bought [<resource_id>]!"
        """

        id_start = s.find("[") + 1
        id_end = s.find("]")
        try:
            return s[id_start:id_end]
        except:
            return None

    @commands.Cog.listener()
    async def on_message(self, message):
        """
        Primarily a message event listener to parse UnbelievaBoat transaction messages.

        Facilitates communication between Kaede/Yoshi and UnbelievaBoat to complete transaction of goods.


        Upon successful purchase from UnbelievaBoat's (UB's) store, the response EMBED message is:
            [if item is "usable"]:
                "You have bought <N> <item_name> for <currency_symbol> <amount>! [. . .]"

            [if non-inventory item]:
                "<the item's "Reply message" value>"


        Current approach will use the [item is "usable"] message format.

        To ensure purchases are properly detected, the following will be used:
            - item is usable (but only to detect standard system message)
            - item "Reply message" is not used.
            - item name format:
                "<item_name> [<resource ID>][<category>][<tier>]"
        """

        # apply filters before processing further...
        if message.guild is None or message.author.id != UB_ID:
            return

        # (shorthand) get UB reply info (UB reply and customer ID)
        if not message.embeds:
            e_desc = message.content
            customer_id = message.mentions[0].id if message.mentions else None
        else:
            e = message.embeds[0]
            e_desc = e.description
            customer_id = e.author.id

        # purchase detected; get customer object
        try:
            ctx = await self.bot.get_context(message)
            customer = await ctx.guild.fetch_member(customer_id)
        except:
            return

            # traceback.print_exc()
            # e_error = self.resource_link_retrieval_err_embed("???", None)
            # return await message.reply(embed=e_error)

        resource_name, resource_id = None, None

        # ATTEMPT ROUTE 1: (UB's default "You have bought..." message)
        if self.purchase_parser.match(e_desc) is not None:

            try:
                # retrieve resource name AND id
                info = self.find_resource_info_route1(e_desc)
                resource_name, resource_id = info

            except:

                traceback.print_exc()
                # TODO: replace this (generic) error report with a more specific one
                e_error = self.resource_link_retrieval_err_embed("???", customer)
                return await message.reply(embed=e_error)

        # ATTEMPT ROUTE 2: (CUSTOM string reply, "You bought [<code>]!")
        elif (e_desc.find("You bought ") != -1) and message.mentions:

            try:
                # retrieve resource name AND id
                resource_id = self.find_resource_info_route2(e_desc)
                resource_name = self.get_resource(
                    ctx.guild.id, resource_id, property="name"
                )
                if resource_name is None:
                    raise Exception("Resource name couldn't be found.")
            except:

                traceback.print_exc()
                # TODO: replace this (generic) error report with a more specific one
                e_error = self.resource_link_retrieval_err_embed("???", customer)
                return await message.reply(embed=e_error)

        # ROUTE 3: ERROR -- NOTHING COULD BE FOUND
        else:
            e_error = self.resource_link_retrieval_err_embed("???", customer)
            return await message.reply(embed=e_error)

        # retrieve resource link from DB (using ID)
        resource_link = self.get_resource(message.guild.id, resource_id)
        if resource_link is None:
            traceback.print_exc()
            e_error = self.resource_link_retrieval_err_embed(resource_id, customer)
            return await message.reply(embed=e_error)

        # generate transaction ID
        trans_id = uuid.uuid4()

        # DM/PM resource link to customer
        purchase_embed = self.resource_purchase_embed(
            resource_name, resource_link, trans_id, customer
        )
        sent = await customer.send(embed=purchase_embed)

        # TODO: IMPLEMENT THE AUDIT SECTION TO ACCOUNT FOR "ROUTE 2"
        #
        # - may need to do a lookup in K/Y's DB? not sure
        #
        # add audit log entry if resource successfully sent
        # if sent:
        #
        #    # get/parse resource cost
        #    amt_start = e_desc.find("for ") + 4
        #    amt_start = e_desc.find(" ", amt_start) + 1
        #    amt_end = e_desc.find("!")
        #    amt_str = e_desc[amt_start:amt_end]
        #
        #    self.add_log_entry(
        #        str(message.guild.id),
        #        customer,
        #        resource_id,
        #        float(amt_str),
        #        id_=trans_id
        #    )

    @commands.group("shop")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def shop(self, ctx):
        """
        [ADMINISTRATORS ONLY]

        Parent command for important shop utilities. IMPORTANT START-UP INFO BELOW.

        "UB" = "UnbelievaBoat"

        __To add an item to the store for purchase (hosted by UnbelievaBoat):__

        PART 1:
        > use `ub!create-item` and follow this structure:
        > - `name` (format): YOUR-ITEM-CODE (e.g. "DRW-039", no quotes)
        > - `price`: (you set the price)
        > - `description`: (put book or resource title here)
        > - `show in inventory?` no
        > - enter "skip" (6 times)
        > - `reply message`: {member.mention} You bought [YOUR-ITEM-CODE]!

        PART 2:
        > use `y!help shop addlink` and _follow the instructions_.
        > - resource/item name MUST MATCH the item name in the UB store.


        ITEM SHOULD BE ADDED PROPERLY NOW.
        --- --- ---
        """

        if ctx.invoked_subcommand is None:
            pass

    @shop.command("addlink")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def shop_addlink(self, ctx, link: str, id_: str, resource_name):
        """
        Add an encoded resource/book link.

        QUOTES (") REQUIRED around name of resource <resource_name>.

        If link requires password, use ">>" to separate (encoded) link and password:
        "my_link_here>>password_here"

        Usage:
        !shop addlink asd89320hf9328n01 BL-031 "How to Draw BL"
        !shop addlink asd89320hf9328n01 D-032.1 "Resource Title Here"

        Usage (if link has password):
        !shop addlink asd89320hf9328n01>>p4ssw0rd BL-031 "How to Draw BL"
        """

        # check 1: ensure <id_> not too long
        if len(id_) > self.MAX_RESOURCE_ID_LEN:
            raise commands.CommandError(
                (
                    f"Failed to add resource link. "
                    f"ID exceeded max length ({self.MAX_RESOURCE_ID_LEN})."
                )
            )

        # check 2: malformed quotations
        if '"' in resource_name:
            raise commands.CommandError('Bad quotations ("), link not added.')

        # if ID (id_) is unique, proceed with entry addition
        if not self.resource_exists(ctx.guild.id, id_):

            self.add_resource_entry(ctx.guild.id, id_, resource_name, f'"{link}"')

            description = (
                f"[**{id_}**] _'{resource_name}'_ " "resource link successfully added."
            )
            e = discord.Embed(description=description, colour=discord.Colour.green())
            return await ctx.reply(embed=e)

        # if ID (id_) already exists, notify user
        else:
            raise commands.CommandError(
                (
                    "Resource link could not be added. A "
                    f"resource with ID `{id_}` already exists."
                    f"\n\nUse `y!shop removelink {id_}`, then "
                    "try re-adding the resource."
                )
            )

    @shop.command("updatelink")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def shop_updatelink(self, ctx, resource_id: str, property: str, *, value):
        """
        Use this to update a stored link's `link` or associated `name`.

        If updating link password, use this command format (>>):
        "!shop updatelink 0BXD49 link s0m3link>>p4ssw0rd"

        ^^Above, the link is "s0m3link" and the password is "p4ssw0rd"

        Common use case(s):
        - resource link is added before the associate store item is added.
        - resource password changed
        - resource link changed
        - resource's associated item name changed

        <property>:     "link" | "name"

        Usage:
        !shop updatelink 0355D1 link fDxaa003hadlfhealBx
        !shop updatelink 0355D1 link YourLinkHere>>p4ssw0rd
        !shop updatelink 0355D1 name How to Draw Circles
        !shop updatelink 0355D1 name random_new_name
        """

        if property not in {"link", "name"}:
            raise commands.CommandError("Invalid property. Must be `link` or `name`.")

        if property == "link":

            # set "verify_exists" False to only check for proper URL string formation
            # validator = URLValidator(verify_exists=False)
            # try:
            #    validator(value)
            # except ValidationError, e:
            #    if
            #
            #    raise commands.CommandError("Improper URL. Link not added.")

            # wrap link in quotes (") so it doesn't malform when retrieving
            value = f'"{value}"'

        # perform attrib update on resource
        self.update_resource_property(ctx.guild.id, resource_id, property, value)

        # notify cmd user to change UB item name accordingly
        if property == "name":
            await ctx.reply(
                (
                    f"Name change success! Make sure the item name "
                    f"in UnbelievaBoat's store matches."
                )
            )

        elif property == "link":
            await ctx.reply("Link successfully updated.")

        await react_success(ctx)

    @shop.command("removelink")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def shop_removelink(self, ctx, resource_id: str):
        """
        Remove a resource link from the database of resources.

        Link entry is searched via its <resource_id>.

        WARNING:
        UnbelievaBoat store item associated with this resource may need to manually be removed.
        This async method may optionally be used by a custom event listener for store item removals.

        Usage:
        !shop removelink 0355D1
        """

        if not self.resource_exists(ctx.guild.id, resource_id):
            return await ctx.reply(
                f"Resource (ID: {resource_id}) not found. No action taken."
            )

        try:
            # remove resource from DB
            self.remove_resource_entry(ctx.guild.id, resource_id)
            await react_success(ctx)

        except RuntimeError:
            raise commands.CommandError(
                "Error: could not remove the specified resource."
            )

    @shop.command("viewlinks")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def shop_viewlinks(self, ctx, resource_id: Optional[str] = None):
        """
        [diagnostic tool]

        View current resource entries in the DB, or find a specific entry (via ID).

        Usage:
        !shop viewlinks
        !shop viewlinks 0355D1
        """

        # TODO: ADD SUPPORT FOR FILTERING/VIEWING BY TAG

        # specific resource info requested
        if resource_id is not None and self.resource_exists(ctx.guild.id, resource_id):
            info = self.get_resource(ctx.guild.id, resource_id, "basic")

            e = discord.Embed(
                description=f"Resource info: `{info}`",
                colour=discord.Colour.dark_grey(),
            )
            await ctx.reply(embed=e)

        # all resource listings requested
        elif resource_id is None:

            # gather resources from DB
            info = []
            entries = self.get_all_resources(ctx.guild.id)
            for i, row in enumerate(entries):
                # format: [entry#] <resource_id> - <resource_name>
                info.append(f"[{i}] " + " - ".join(list(row)))
            info = "\n".join(info)

            # container for resource listings
            e = discord.Embed(
                title="Resources Found:",
                description=info,
                colour=discord.Colour.dark_grey(),
            )

            await ctx.reply(embed=e)


def setup(bot):
    bot.add_cog(Transactions(bot))
