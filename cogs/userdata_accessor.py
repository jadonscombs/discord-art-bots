"""
Description:
    Primary file for reading/writing values to/from a database of
    uses for a specified guild.

NOTE:
    The object instance is not coupled to a particular database associated
    with a guild. It is used to point at whatever guild is required when a
    a command or other entity requests it (like a cursor).

Operations:
    General operations may include (and are not limited to):
        - reading attribute of a User
        - retrieving all a User's stats
        - incrementing a User attribute
        - retrieving names of users with the X highest values for an attr.

Saving data:
    Use <Connection>.commit() to save any changes.
"""


import discord
from discord.ext import commands, tasks
from cogs.globalcog import GlobalCog
from constants import roles
import argparse
import asyncio
import datetime
from datetime import timezone
import json
import math
import numbers
import os
import shutil
import cogs.point_distributor as points
import sqlite3
from utils.sync_utils import ub_get, ub_put, ub_patch
import sys
import time
import traceback
from typing import Optional


# minor optimization
sql3_connect = sqlite3.connect
os_join = os.path.join
os_isfile = os.path.isfile
os_isdir = os.path.isdir
os_realpath = os.path.realpath
os_dirname = os.path.dirname
makedirs = os.makedirs


class UserDataAccessor(commands.Cog, GlobalCog):
    """Data and Statistics Module"""

    # class variables ----------- shared across all instances
    EXT_NAME = ".sqlite3"  # default db extension type
    FOLDER = "sqlite_dbs"  # default self.FOLDER name
    NUMERIC_UPPER_BOUND = 5.0e7  # (50,000,000)

    def __init__(self, bot):
        self.bot = bot
        self.distributor = points.Distributor(bot)

        # flag to disable the bot
        self.disabled = False

        # defining attributes for future reference
        self.numeric_attrs = [
            "level",
            "xp",
            "points",
            "clearance",
            "total_pos_reactions",
            "total_neg_reactions",
            "total_messages",
            "total_reactions_added",
            "total_content_links_shared",
            "total_links_shared",
            "total_resolutions",
            "num_times_streamed",
            "total_time_streamed",
            "activeness_score",  # out of 100
            "overall_consistency_score",
            "overall_reliability_score",
            "num_times_featured_as_artist",
            "num_warnings",
            "num_times_muted",
            "num_times_blacklisted",
        ]

        # core user identifier attributes
        self.core_text_attrs = ["id", "username", "discrim"]

        # text attributes
        self.text_attrs = self.core_text_attrs + [
            "member_status",
            "preferred_language",
            "last_time_went_live",
        ]

        # core and non-core text attribute default values;
        # NOTE: number of items must match the number in <self.text_attrs>
        self.text_attrs_default_vals = ["n/a", "n/a", "n/a", "unverified", "n/a", "n/a"]

        # attrs = (attrs + numeric_attrs)
        self.attrs = self.text_attrs + self.numeric_attrs

        # unverified users attributes (0=False, 1=True)
        self.unverified_users_default_vals = {
            "id": {"value": "?", "type": "text"},
            "member_status": {"value": "unverified", "type": "text"},
            "is_new_member": {"value": 1, "type": "integer"},
            "message_pass": {"value": 0, "type": "integer"},
            "reaction_pass": {"value": 0, "type": "integer"},
        }
        self.unverified_users_attrs = list(self.unverified_users_default_vals.keys())

        # blacklist attributes (all text)
        self.blacklist_attrs = ["id", "status", "status_value", "note"]

        # server stats attributes (all real)
        self.server_attrs = [
            "total_users_left",
            "total_users_joined",
            "leave_rate_weekly",
            "join_rate_weekly",
            "leave_rate_monthly",
            "join_rate_monthly",
            "num_unreacts_on_rules",
            "num_reacts_on_rules",
            "message_send_rate_daily",
            "message_send_rate_weekly",
            "message_send_rate_monthly",
            "num_unique_donations",
            "weekly_art_submissions",
            "total_donations_usd",
            "total_num_incidents",
        ]

        # allowed tables for update()-ing
        self.allowed_update_tables = (
            "udata",
            "unverified_users",
            "server_stats",
            "blacklist",
            "designated_zones",
        )

        # template zone info (name, priority, channel_limit)
        #
        # <priority> attrib: 0=mandatory, 1=optional, 2=undecided
        self.zone_info = {
            "rules":                {"priority": 0, "channel_limit": 1},
            "introductions":        {"priority": 0, "channel_limit": 1},
            "action_approval":      {"priority": 2, "channel_limit": 10},
            "self_appraisal":       {"priority": 2, "channel_limit": 10},
            "stream_text":          {"priority": 1, "channel_limit": 3},
            "tag_library":          {"priority": 2, "channel_limit": 2},
            "bot_operator_zone":    {"priority": 0, "channel_limit": 20},
            "administration_zone":  {"priority": 2, "channel_limit": 4},
            "art_zone":             {"priority": 1, "channel_limit": 20},
            "art_gallery":          {"priority": 0, "channel_limit": 8},
            "faq":                  {"priority": 2, "channel_limit": 3},
            "share_zone":           {"priority": 1, "channel_limit": 20},
            "general":              {"priority": 1, "channel_limit": 5},
        }

        # priority numbers: 0=mandatory, 1=optional, 2=undecided
        self.zone_priorities = {
            "rules":                0,
            "introductions":        0,
            "action_approval":      2,
            "self_appraisal":       2,
            "stream_text":          1,
            "tag_library":          2,
            "bot_operator_zone":    0,
            "administration_zone":  2,
            "art_gallery":          2,
            "faq":                  2
        }

        # designated zone names (#TODO: automate designation zone retrieval)
        self.zone_names = list(self.zone_info.keys())

        # currently designated zones (RAM-only)
        self.zones = {}

        # help create mirror in GlobalCog to access db
        GlobalCog.accessor_mirror = self

        # ensure the "sqlite_dbs" folder is made upon initialization
        if not os_isdir("sqlite_dbs"):
            makedirs("sqlite_dbs")

    def get_currdir(self) -> str:
        """
        Return current directory of MAIN BOT SCRIPT
        """
        return os_dirname(os_realpath(sys.argv[0]))

    def get_fpath(self, gid: str) -> str:
        """
        Return filepath (incl. filename) of server w/GuildID <gid>
        """
        currdir = self.get_currdir()
        isdir_path = os_join(currdir, self.FOLDER)

        # check if folder FOLDER exists
        if not os_isdir(isdir_path):
            makedirs(isdir_path)

        # return full file path
        return os_join(isdir_path, gid + self.EXT_NAME)

        # OLD IMPLEMENTATION:
        # return os_join(os_dirname(self.get_currdir()),
        #                    self.FOLDER, gid + self.EXT_NAME)

    def db_exists(self, gid: str) -> bool:
        """
        Check if specified database exists.
        """
        return os_isfile(self.get_fpath(gid))

    def make_new(self, gid: str):
        """
        Create new database (with 'udata') for guild (fname).
        ESSENTIALLY, connect( 'db_name.sqlite3' ) IS WHAT CREATES A
        NEW DATABASE.

        Assumption(s): Only execute(s) after checking db_exists(...)
        """
        conn = sql3_connect(self.get_fpath(gid))
        conn.commit()
        conn.close()
        self.CREATE_TABLE(gid)

    def connect(self, gid: str):
        """
        Description: return SQLite Connection object to a db; is handler.
            > CREATE_TABLE(...) should create (N) TABLES:
                1. user stats (the main table)
                2. "unverified_users" (for unverified/new users)
                3. blacklist?
        """
        # if file exists and tables exist
        if self.db_exists(gid) and self.db_made:
            return sql3_connect(self.get_fpath(gid))

        # if file exists but unsure if tables exist
        elif self.db_exists(gid):
            conn = sql3_connect(self.get_fpath(gid))

            # check if table 'udata' exists (create if necessary);
            # NOTE (FEB. 24 2021):
            # THIS ONLY CHECKS FOR 'udata', not any OTHER TABLES
            #
            cur = conn.cursor()
            cur.execute(
                "SELECT count(name) FROM sqlite_master WHERE "
                "type='table' AND name='udata'"
            )

            # create/initialize db
            if cur.fetchone() is None:
                conn.close()
                self.CREATE_TABLE(gid)

            self.db_made = True
            return sql3_connect(self.get_fpath(gid))

        # if file DOESN'T exist: create db, save and close
        conn = sql3_connect(self.get_fpath(gid))
        conn.commit()
        conn.close()

        self.CREATE_TABLE(gid)
        return sql3_connect(self.get_fpath(gid))

    def get_columns(self):
        """
        Return names of columns in database
        """
        return self.attrs

    def CREATE_TABLE(self, gid: str):
        """
        Create a table for user data if not created already
        """
        with sql3_connect(self.get_fpath(gid)) as conn:
            cur = conn.cursor()
            try:
                # formatting string for easier readability
                text_col_labels = " text, ".join(self.text_attrs[1:]) + " text, "
                numeric_col_labels = " real, ".join(self.numeric_attrs) + " real"
                userdata_column_labels = text_col_labels + numeric_col_labels
                cmd_string = "CREATE TABLE udata(id text PRIMARY KEY, {});"
                cmd_string = cmd_string.format(userdata_column_labels)

                # create the MAIN table (for user stats)
                cur.execute(cmd_string)
                conn.commit()

                # create the "unverified users" table
                unverified_users_cmd = (
                    "CREATE TABLE unverified_users(id text PRIMARY KEY, "
                )

                for k, v in list(self.unverified_users_default_vals.items())[1:]:
                    unverified_users_cmd += "{} {}, ".format(k, v["type"])

                unverified_users_cmd = unverified_users_cmd[:-2] + ");"
                cur.execute(unverified_users_cmd)
                conn.commit()

                # create the "server stats" table
                server_stats_cmd = "CREATE TABLE server_stats("
                server_stats_cmd += " real,".join(self.server_attrs) + " real);"
                cur.execute(server_stats_cmd)
                conn.commit()

                # create a default row (zeros) in the "server stats" table
                row_entry = "INSERT INTO server_stats("
                row_entry += ",".join(self.server_attrs) + ") VALUES({});"
                row_entry = row_entry.format(",".join(["0.0"] * len(self.server_attrs)))
                cur.execute(row_entry)
                conn.commit()

                # create the "blacklist" table (TODO: UNFINISHED)
                cmd = "CREATE TABLE blacklist(id text PRIMARY KEY, "
                cmd += " text,".join(self.blacklist_attrs[1:]) + " text);"
                cur.execute(cmd)
                conn.commit()

                # create a designated_zones table (to enforce command "domains"/"zones")
                cmd = (
                    "CREATE TABLE designated_zones("
                    "designation_name text PRIMARY KEY, "
                    "channel_id text, channel_limit real);"
                )
                cur.execute(cmd)
                conn.commit()

            except:
                traceback.print_exc()

        # create placeholder rows in the <designated_zones> table
        self.add_zone_entries(gid)
        self.db_made = True
        print("All tables have been successfully created.")

        
    def gather_user_stats(
        self,
        gid: str,
        uid: str,
        fields: list = None,
        table: str = "udata"
    ):
        """
        Helper method for <print_table()>.
        
        Returns specific stats (<fields>) for the given user <uid>.
        """
        
        # establish user database connection
        with self.connect(gid) as conn:
            cur = conn.cursor()
            
            # construct fields to retrieve or use default fields;
            # <fields> parameter must be non-empty and only
            # contain string elements;
            if (
                isinstance(fields, list) and
                all([isinstance(field, str) for field in fields])
            ):
                fields_str = ",".join(fields)
            else:
                fields = [
                    "id",
                    "username",
                    "discrim",
                    "points",
                    "num_times_streamed",
                    "total_time_streamed",
                    "last_time_went_live"
                ]
                fields_str = ",".join(fields)
            
            # if supplied <uid> is empty or None, raise error
            if not bool(uid):
                raise ValueError(
                    "[userdata_accessor.brief_stats] error: "
                    "malformed user id <uid>"
                )
            
            # retrieve fields from database for specified user ID
            cmd = f"SELECT {fields_str} FROM {table} WHERE id=?"
            cur.execute(cmd, (uid,))
            result = cur.fetchone()
            
            # error-checking if fetched results are None
            if result is None:
                raise ValueError(
                    "[userdata_accessor.brief_stats] error: "
                    "retrieved fields is type None"
                )
            
            # convert result to string (labels and values underneath) and return
            result_dict = dict(zip(
                fields,
                [str(value) for value in list(result)]
            ))
            
            result_str = ",\n".join(
                ["{}: {}".format(k, v) for k,v in result_dict.items()]
            )
            return result_str
        
        
    def print_table(self, gid: str, uid: str, table: str = "udata"):
        """
        Output helper method used by <on_message()> to display basic stats
        of the message author.
        """
        
        stats = self.gather_user_stats(gid, uid, table=table)
        print(f"---\n\n{stats}\n\n---")
        

    def ADD_COL(self, colname: str, coltype="text", gid: str = "all", table="udata"):
        """
        Add new column to specified database (gid).
        """
        cmd = "ALTER TABLE {tbl} ADD COLUMN '{cn}' {ct}".format(
            tbl=table, cn=colname, ct=coltype
        )

        conn, cur = None, None
        # gid = ALL AVAILABLE
        if gid == "all":  # check all dbs in {self.FOLDER}
            db_dir = os.path.join(os.path.dirname(self.get_currdir()), self.FOLDER)

            # list of db file names
            files = [
                f for f in os.listdir(db_dir) if os.path.isfile(os.path.join(db_dir, f))
            ]

            # minor optimization
            join = os.path.join

            # iterate over each filename
            for f in files:
                conn = sql3_connect(join(db_dir, f))
                cur = conn.cursor()
                try:
                    cur.execute(cmd)

                    # LAST STEP: add a default value to the column
                    if coltype == "text":
                        cmd2 = "UPDATE {} SET ? = ''".format(table)
                        cur.execute(cmd2, (colname,))
                    elif coltype == "real":
                        cmd2 = "UPDATE {} SET ? = 0.0".format(table)
                        cur.execute(cmd2, (colname,))

                    conn.commit()
                except:
                    traceback.print_exc()
                finally:
                    conn.close()

        # gid = SINGLE GUILD ID
        elif self.db_exists(gid):
            conn = self.connect(gid)
            cur = conn.cursor()
            try:
                cur.execute(cmd)
                conn.commit()
            except:
                traceback.print_exc()
            finally:
                conn.close()

    def ADD_USER(self, gid: str, uid: str, connection=None):
        """
        Description: add user to particular DB associated with gid;
        Note: the <connection> param (unused) is added to speed up process
        """
        # print( 'entered ADD_USER' )
        if self.user_exists(gid, uid):
            return
        # print( 'user does not exist, now making an entry...' )

        # validate connection
        with self.connect(gid) as conn:
            cur = conn.cursor()
            try:
                # validate guild existence
                guild = self.bot.get_guild(int(gid))
                if guild is not None:
                    # print("[ADD_USER] guild found:", guild.name)

                    # check if user entry ALREADY EXISTS
                    # exists_query = "SELECT EXISTS(SELECT 1 FROM udata WHERE id=?)"
                    # cur.execute( exists_query,(uid,) )
                    # if cur.fetchone(): return

                    # INSERT NEW ROW with initialized user info
                    member = guild.get_member(int(uid))

                    # DO NOT add BOTS as a member
                    if member.bot:
                        print("[add_user] member NOT added: member is a bot.")
                        return

                    labels = ", ".join([str(s) for s in self.attrs])

                    # WARNING: THIS MUST BE UPDATED WHEN NON-NUMERIC ATTRIBS ARE ADDED!!!
                    vals = (
                        "'"
                        + "', '".join(
                            [uid, member.name, member.discriminator]
                            + self.text_attrs_default_vals[3:]
                        )
                        + "'"
                    )

                    # numeric default values of '0' added for N numeric attributes
                    vals += ", " + ", ".join(["0"] * len(self.numeric_attrs))

                    # execute the command -- adding default values for a new user
                    cmd_string = "INSERT INTO udata ({}) VALUES ({});".format(
                        labels, vals
                    )
                    cur.execute(cmd_string)

                    # also add user to the UNVERIFIED list/table (IF they don't have a verified role)
                    verified_status = "unverified"
                    if (
                        discord.utils.get(member.roles, name=roles.VERIFIED_MEMBER)
                        is None
                    ):
                        vals = tuple(
                            [
                                v["value"]
                                for k, v in self.unverified_users_default_vals.items()
                            ][2:]
                        )
                        vals = (uid, verified_status) + vals
                        param_repeats = ",".join(["?"] * len(vals))
                        cmd_string = "INSERT INTO unverified_users VALUES({});".format(
                            param_repeats
                        )
                        cur.execute(cmd_string, tuple(vals))

                    else:
                        # update their member status
                        cmd_string = (
                            "UPDATE udata SET member_status='verified' WHERE id=?"
                        )
                        cur.execute(cmd_string, (uid,))

                    try:
                        print("New user has been added:", member.name)
                    except:
                        pass

                    conn.commit()

            # occurs if ID entry already exists
            except sqlite3.IntegrityError:
                # UNCOMMENT BELOW LINE IF YOU NEED TO KNOW ABOUT DUPLICATES
                # print("[userdata_accessor.adduser] PRIMARY KEY ERROR")
                traceback.print_exc()

            except:
                print("[userdata_accessor.adduser] ERROR:")
                traceback.print_exc()

    def DELETE_USER(self, gid: str, uid: str):
        """
        Delete specified user from all records in all databases where user appears.

        code 0:     successfully deleted user records
        code -1:    failed to delete user records
        """
        try:
            with self.connect(gid) as conn:
                cur = conn.cursor()

                # deleting user from the "unverified_users" table
                cur.execute("DELETE FROM unverified_users WHERE id=?", (uid,))

                # deleting user from the "udata" table
                cur.execute("DELETE FROM udata WHERE id=?", (uid,))

                # deleting user from the "blacklist" table
                # cur.execute("DELETE FROM blacklist WHERE id=?", (uid,))

                conn.commit()
            return 0
        except:
            traceback.print_exc()
            return -1

    def add_zone_entries(self, gid: str):
        """Add placeholder zone entries (populate later)."""
        try:
            cmd = (
                "INSERT INTO designated_zones(designation_name,"
                "channel_id,channel_limit) VALUES(?,?,?)"
            )
            with self.connect(gid) as conn:
                cur = conn.cursor()
                for zone in self.zone_info:
                    cur.execute(cmd, (zone, "", self.zone_info[zone]["channel_limit"]))
                conn.commit()

        except:
            traceback.print_exc()

    def load_zone_entries(self, gid: str, naive_load=True):
        """
        Load current zones/zone entries from DB into memory (self.zones).

        Best used when starting up the bot.

        Set <naive_load> to False to NOT overwrite existing cache entries.

        STRUCTURE OF SELF.ZONES:
        ------------------------
            [guild_id1]
                [zone_name1] : [channel_id1, ..., channel_idN]
                [zone_name2] : [channel_id1, ..., channel_idN]
                    ...             ...
                [zone_nameN] : [channel_id1, ..., channel_idN]

                ...
                ...

            [guild_idN]
                [zone_name1] : [channel_id1, ..., channel_idN]
                [zone_name2] : [channel_id1, ..., channel_idN]
                    ...             ...
                [zone_nameN] : [channel_id1, ..., channel_idN]
        """
        try:
            # print("[load_zone_entries] now executing")
            with self.connect(gid) as conn:
                self.zones_being_loaded = True

                # retrieve guild's zone data from DB
                cur = conn.cursor()
                cur.execute("SELECT * FROM designated_zones")

                if gid not in self.zones:
                    self.zones[gid] = {}
                elif (self.zones[gid] is None) or len(self.zones[gid]) == 0:
                    self.zones[gid] = {}

                for row in cur.fetchall():

                    # print(f"[loading] current designation name: {row[0]")
                    # row[0]: designation_name
                    # row[1]: comma-separated channel_id(s)

                    # load everything regardless
                    if naive_load:
                        self.zones[gid][row[0]] = row[1]

                    # only load if zone is null in cache entry
                    elif (
                        row[0] not in self.zones[gid] or self.zones[gid][row[0]] is None
                    ):
                        self.zones[gid][row[0]] = row[1]

                # add in unmentioned/unaccounted zone names from
                # the UDA template <self.zone_info>; apply persistent changes.
                for zone in self.zone_info:
                    if zone not in self.zones[gid]:

                        # print(f"[loading] unaccounted designation name: {zone}")

                        cmd = "INSERT INTO designated_zones VALUES(?,?,?)"
                        cur.execute(cmd, (zone, "", self.zone_info[zone]["priority"]))

                        self.zones[gid][zone] = ""

                self.zones_being_loaded = False

                # print("[load_zone_entries] finished executing. now leaving.")
                # print(f"Currently loaded zones:\n{self.zones}")
        except:
            traceback.print_exc()

    def add_designation_category(
        self, gid: str, zone_name: str, channel_id: str = "", limit: int = 1
    ):
        """
        Add a designation category/zone. Commands that operate only in this
        category/zone will need AT LEAST ONE (1) text channel, DESIGNATED
        to this particular category/zone, to allow the bot to respond.

        (note: database table name is "designated_zones")
        """

        try:
            with self.connect(gid) as conn:
                cur = conn.cursor()

                # if zone does not yet, add the zone name + default vals
                if zone_name not in self.zones[gid]:
                    cur.execute(
                        "INSERT INTO designated_zones VALUES(?,?,?)",
                        (zone_name, channel_id, 1),
                    )
                    conn.commit()
                    self.zones[gid][zone_name] = channel_id

        # this implies the DB has the zone listed, but not the cache
        except sqlite3.IntegrityError:

            # reload zone entries to remedy this inconsistency;
            # set flag False to not affect current entries
            self.load_zone_entries(gid, naive_load=False)

        except:
            traceback.print_exc()

    def remove_designation_category(
        self, gid: str, zone_name: str, force: bool = False
    ):
        """
        Remove a designation category/zone.

        Set <force> to True if removing a mandatory zone (e.g. "introductions" or "rules").

        WARNING: Commands that previous depended on this category/zone may not work afterwards.
        """

        try:
            with self.connect(gid) as conn:

                # remove the entry from DB
                cur = conn.cursor()
                cur.execute("DELETE FROM designated_zones WHERE id=?", (zone_name,))

                # remove the entry from cache (RAM-only)
                try:
                    del self.zones[gid][zone_name]
                    conn.commit()
                except KeyError:
                    pass

        except:
            traceback.print_exc()

    def designation_is_set(self, gid: str, zone_name: str):
        """
        Return true if specified designation <zone_name> has been set
        for the guild with a guild ID of <gid>.
        """
        try:

            # load designation zones into memory if needed
            if (gid not in self.zones) or (
                (len(self.zones[gid]) <= 0) and (not self.zones_being_loaded)
            ):
                # print(f"[designation_is_set] calling <load_zone_entries()>")
                self.load_zone_entries(gid)
                # print(f"[designation_is_set] exited <load_zone_entries()>")

            try:
                # print(f"[designation_is_set] now trying to find {zone_name} entry in cache")

                # check RAM/cache if zone is set for the guild
                found = self.zones[gid][zone_name] not in ("", " ", "n/a")
                # print(f"[designation_is_set] {zone_name} {'' if found else 'NOT'} found for {gid}.")

                if not found:
                    # check DB if zone is set for the guild
                    with self.connect(gid) as conn:
                        cur = conn.cursor()
                        cmd = "SELECT channel_id FROM designated_zones WHERE designation_name=?"
                        cur.execute(cmd, (zone_name,))
                        result = cur.fetchone()
                        if result is not None:

                            result = result[0] not in {"", "n/a", None}
                            # print((
                            #    f"[designation_is_set] {zone_name} zone entry "
                            #    f"{'' if result else 'NOT'} found."
                            # ))
                            return result

                        # print(f"[designation_is_set] no DB results for {zone_name}.")
                else:
                    return True

            except KeyError:
                traceback.print_exc()
                return False
        except:
            traceback.print_exc()
            return False

    def set_designation(
        self, gid: str, zone_name: str, channel_id: str, overwrite=False
    ):
        """
        This does two things:
            1. Set/classify a given channel as a given designation zone.
            2. Add the channel_id to the existing list of channel IDs for the specified zone.

        WARNING:
            If <overwrite> set to True, zone entry is overwritten with <channel_id> value.
        """

        # TODO (NOTES):
        #   - need to add logic that considers if the zone's <limit> (# of channels allowed per guild)
        #     has been surpassed. e.g., if <introductions> has a limit of 2, then this function should
        #     not allow adding (3) a third channel to the <introductions> zone for a guild.

        # load zones in RAM/cache (if needed)
        if gid not in self.zones or (
            (len(self.zones[gid]) <= 0) and (not self.zones_being_loaded)
        ):
            self.load_zone_entries(gid)

        # ensure zone is a valid zone
        if zone_name not in self.zones[gid] and zone_name not in self.zone_info:
            raise Exception("Invalid or nonexistent designation zone ({zone_name}).")

        with self.connect(gid) as conn:
            cur = conn.cursor()

            # get list of channel_ids for <zone_name>
            cmd = "SELECT channel_id FROM designated_zones WHERE designation_name=?"
            cur.execute(cmd, (zone_name,))
            channel_ids = cur.fetchone()
            if channel_ids is None:
                channel_ids = ""
            else:
                channel_ids = channel_ids[0]

            # if channel_id is in zone's list of entries, return
            if (not overwrite) and self.is_channel(zone_name, gid, channel_id):
                # print(f"[set_designation] channel IS set as {zone_name}. now returning")
                return

            # string formatting to incporate added entry
            if overwrite or channel_ids.strip() in {"", "n/a", None}:
                channel_ids = channel_id
            else:
                channel_ids += f",{channel_id}"

            # ensure entries are unique (no duplicates)
            channel_ids = ",".join(list(set(channel_ids.split(","))))

            # push zone entries update to DB
            # print(f"[set_designation] update:\nzone={zone_name}, ch={channel_ids}")

            cmd = "UPDATE designated_zones SET channel_id=? WHERE designation_name=?"
            cur.execute(cmd, (channel_ids, zone_name))
            conn.commit()

            # push update to self.zones (in-memory "cache")
            self.zones[gid][zone_name] = channel_ids
            # print(f"[set_designation] cache updated: {zone_name}={self.zones[gid][zone_name]}")

    def remove_designation(
        self, gid: str, zone_name: str, channel_id: str, is_channel_bypass: bool = False
    ):
        """
        This removes a given <channel_id> from the specified <zone_name> for the given <gid>.

        Set <is_channel_bypass> to True to skip the <is_channel(...)> check.
        """

        # print(f"[rm_designation] TARGETS: channel={channel_id}, zone={zone_name}\n")

        # load zones in RAM/cache (if needed)
        if gid not in self.zones:
            self.load_zone_entries(gid)

        # ensure zone is a valid zone
        if zone_name not in self.zones[gid] and zone_name not in self.zone_info:
            raise Exception("Invalid or nonexistent designation zone.")

        # check if channel IS an entry in the given zone's entries for this guild
        if (not is_channel_bypass) and not self.is_channel(zone_name, gid, channel_id):
            return

        # proceed with operations
        channel_id = str(channel_id)
        with self.connect(gid) as conn:
            cur = conn.cursor()

            # get the current data
            cmd = "SELECT channel_id FROM designated_zones WHERE designation_name=?"
            cur.execute(cmd, (zone_name,))
            channel_ids = cur.fetchone()[0]
            channel_ids = channel_ids.split(",")

            # print(f"[rm_designation] pre-removal entries retrieved:\n\t{channel_ids}\n")

            # find & remove <channel_id> from list; then reconvert to str
            try:
                channel_ids.remove(channel_id)
            except ValueError:
                # print(f"[rm_designation] could not remove channel ({channel_id}).")
                return  # does not exist

            # ensure unique entries and no empty entries
            channel_ids = list(set(channel_ids))
            channel_ids = ",".join(channel_ids)

            # print(f"[rm_designation] pushing update to DB: {zone_name}={channel_ids}")

            # push zone entries update to DB
            cmd = "UPDATE designated_zones SET channel_id=? WHERE designation_name=?"
            cur.execute(cmd, (channel_ids, zone_name))
            conn.commit()

            # push update to self.zones (in-memory "cache")
            self.zones[gid][zone_name] = channel_ids

            # print(f"[rm_designation] self.zones[gid] status:\n\n{self.zones[gid]}\n\n")

    def get_designation_channel_id(self, gid: str, zone_name: str):
        """
        Return the associated channel id(s) for <zone_name>. Returns ("") if fail.
        """
        try:

            # attempt retrieval from RAM/cache
            if self.zones[gid][zone_name] not in ("", " ", "n/a"):
                return self.zones[gid][zone_name]

            # (if needed) attempt retrieval from DB
            with self.connect(gid) as conn:
                cur = conn.cursor()
                cmd = "SELECT channel_id FROM designated_zones WHERE designation_name=?"
                cur.execute(cmd, (zone_name,))
                channel_id = cur.fetchone()
                return channel_id[0] if channel_id else ""
        except:
            traceback.print_exc()
            return ""

    def is_channel(self, zone_name: str, gid: str, channel_id: str):
        """
        Return true if the specified channel <channel_id> is registered
        as the zone <zone_name> for the current guild <gid>.

        NOTE: <channel_name> must be the name of a pre-defined "designation zone."
        """
        if (gid not in self.zones) or (
            (len(self.zones[gid]) <= 0) and (not self.zones_being_loaded)
        ):
            self.load_zone_entries(gid)

        if zone_name not in self.zones[gid] and zone_name not in self.zone_info:
            return False

        try:

            # print(f"[is_channel] TARGETS: channel={channel_id}, zone={zone_name}")

            # check if channel is an entry for the zone (RAM/cache)
            ram_entry = (self.zones[gid][zone_name] or "").split(",")

            if channel_id not in ram_entry:
                # print(f"[is_channel] 1st check failed")

                # check DB if channel is an entry for the zone (for guild)
                with self.connect(gid) as conn:
                    cur = conn.cursor()
                    cmd = "SELECT channel_id FROM designated_zones WHERE designation_name=?"
                    cur.execute(cmd, (zone_name,))

                    result = cur.fetchone()
                    if result is not None:
                        # print(f"[is_channel] DB result found: {result}")
                        # print(f"[is_channel] now cross-referencing DB result")

                        result = channel_id in result[0].split(",")
                        # print(f"[is_channel] result: {channel_id} {'IS' if result else 'NOT'} found.")
                        return result

                    # print(f"[is_channel] DB result wasn't found")

            else:
                # print(f"[is_channel] channel found in zone entries! returning True.")
                return True

        except KeyError:
            return False
        except:
            traceback.print_exc()
            return False

        # end-case: this channel is not a registered <zone>
        return False

    def strfmt_zones(self, gid: str):
        """
        Return string-formatted designation zones.

        NOTE:   currently still using the 0,1,2 priority scheme
                (0=mandatory, 1=optional/recommended, 2=undecided)
        """
        pri_names = ["mandatory", "recommended", "undecided"]
        zones_str = []  # starts as list, then join()ed as string later
        append = zones_str.append

        # make list of string-formatted zones;
        # format: <zone_name> <zone_priority>
        for zone in self.zones:
            try:
                append(f"{zone}")
            except KeyError:
                continue
            except:
                continue

        # construct string-formatted string now
        zones_str = "->" + "\n->".join(zones_str)
        return zones_str

    """ ======================== USER OPERATIONS ======================= """

    def check_user(self, gid: str, uid: str):
        """
        Create user entry in db if needed.
        This method is called by (async) on_message()
        """
        self.checking_user = True
        self.ADD_USER(gid, uid)
        self.checking_user = False

    def user_exists(self, gid: str, uid: str) -> bool:
        """
        Return true if row/entry made in DB for user
        """
        try:
            with self.connect(gid) as conn:
                cur = conn.cursor()
                cmd = "SELECT EXISTS(SELECT 1 FROM udata WHERE id=?)"
                cur.execute(cmd, (uid,))

                # returns either true if found, or false
                res = cur.fetchone()[0]
                return bool(res)

        except sqlite3.OperationalError:
            traceback.print_exc()
            return False
        except:
            traceback.print_exc()
            return False

    def check_clearance(self, gid: str, uid: str):
        """
        Check/return the given user's <uid> clearance level.
        """
        try:
            with self.connect(gid) as conn:
                cur = conn.cursor()
                cmd = "SELECT clearance FROM udata WHERE id=?"
                cur.execute(cmd, (uid,))

            clearance = cur.fetchone()
            if clearance:
                return clearance[0]  # return clearance level
            return -1  # return -1 (error case)

        except:
            traceback.print_exc()
            return -1

    def fetch_role(self, role_name: str, gid: str, guild_object=None):
        """
        Return the discord.Role(?) object; faster if <message_object> provided.
        """
        try:
            roles = None
            if guild_object is None:
                roles = self.bot.get_guild(int(gid)).roles
            else:
                roles = guild_object.roles
            return discord.utils.get(roles, name=role_name)
        except:
            traceback.print_exc()
            return None

    def has_role(
        self, gid: str, uid: str, role_name: str, guild_object=None, member=None
    ):
        """
        Return true if specified user has the role <role_name>
        """
        try:
            # get User/Member object first
            if member is None:
                if guild_object is None:
                    member = self.bot.get_guild(int(gid)).get_member(int(uid))
                else:
                    member = guild_object.get_member(int(uid))

            # checking if specified role is present in User/Member
            return self.fetch_role(role_name, gid, guild_object) in member.roles

        except:
            traceback.print_exc()
            return False

    def is_unverified(self, gid: str, uid: str, member=None):
        """
        Return true if user is UNVERIFIED; faster if <member> object provided
        """
        try:
            if member is None:
                guild = self.bot.get_guild(int(gid))
                member = guild.get_member(int(uid))
            return (
                discord.utils.get(member.roles, name=roles.VERIFIED_MEMBER) is not None
            )
        except:
            traceback.print_exc()
            return True

    def is_numeric_attr(self, attr: str) -> bool:
        """Return True if 'attr' is considered a numeric attribute"""
        return attr in self.numeric_attrs

    def is_attr(self, attr: str) -> bool:
        """Return True if 'attr' is considered an attribute held in a DB"""
        return attr in self.attrs

    def get_numeric_attr(self, attr: str, gid: str, uid: str):
        """
        Return value of specified NUMERIC attr, for specified user/guild;

        NOTE: Currently ONLY works for the *udata* table.
        TODO: add support for other tables.
        """
        if self.is_numeric_attr(attr):
            try:
                cur = None
                with self.connect(gid) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT ? FROM udata WHERE id=?", (attr, uid))
                    res = cur.fetchone()[0]

                try:
                    return float(res)
                except:
                    return int(res)

            except:
                return -1
        return -1

    def get_attr(self, attr: str, gid: str, uid: str, table="udata"):
        """
        Return value of specified attr, for specified user/guild
        """
        # case 1 (standard): retrieving a user attribute from udata
        if table == "udata" and self.is_attr(attr):
            try:
                with self.connect(gid) as conn:
                    cur = conn.cursor()
                    cmd = "SELECT {} FROM udata WHERE id={}".format(attr, uid)
                    cur.execute(cmd)
                    res = cur.fetchone()[0]
                    # print("[get_attr][udata] attr=", attr, ", val=", res, ", type:", type(res), "\n")
                    return res
            except:
                return ""

        elif table != "udata":
            try:
                with self.connect(gid) as conn:
                    cur = conn.cursor()
                    cmd = "SELECT {} FROM {} WHERE id={}".format(attr, table, uid)
                    cur.execute(cmd)
                    # cmd = "SELECT ? FROM {} WHERE id=?".format( table )
                    # cur.execute(cmd, (attr, uid))
                    res = cur.fetchone()[0]
                    # print("[get_attr][unver] attr=", attr, ", val=", res, ", type:", type(res), "\n")
                    return res
            except:
                return ""

        return ""

    def get_user_stats(
        self,
        gid: str,
        uid: str,
        content: str = "basic",
        blacklist=["id", "username", "discrim"],
    ):
        """
        Return formatted string of a given user's current stats;
        """
        user_str = ""
        try:
            with self.connect(gid) as conn:
                cur = conn.cursor()
                cur.execute("SELECT * FROM udata WHERE id=?", (uid,))
                labels = cur.description
                whitelist_labels = []
                raw_items = [str(x) for x in cur.fetchone()]
                items = []

                # only get items that are not blacklisted
                wl_append = whitelist_labels.append
                item_append = items.append
                for i in range(len(raw_items)):
                    if labels[i][0] not in blacklist:
                        wl_append(labels[i][0].replace("_", " "))
                        item_append(raw_items[i])

                # create formatted str with items & labels
                if items:
                    # print('items:', items)
                    # print('labels:', whitelist_labels)
                    user_str = "\n".join(
                        [
                            label + ": \t\t" + val
                            for label, val in zip(whitelist_labels, items)
                        ]
                    )
                return user_str
        except:
            traceback.print_exc()
            raise RuntimeError()

    def get_last_live_time(self, member):
        """
        Return the last recorded time the <member> went LIVE in discord voice chat.
        """
        with self.connect(str(member.guild.id)) as conn:
            cmd = "SELECT last_time_went_live FROM udata WHERE id=?"
            try:
                cur = conn.cursor()
                cur.execute(cmd, (str(member.id),))

                res = cur.fetchone()
                res = res[0] if res else ""
                if res.startswith('"') and res.endswith('"'):
                    res = res[1:-1]
                return res
            except:
                traceback.print_exc()
                return ""

    def check_went_live_interval(self, member, min_interval_sec=20):
        """
        Returns true if [currtime] - [previously recorded stream "went live" time] > [min_interval_sec]

        BEFORE return value is determined...time difference is calculated, and <currtime>
        replaces the value for "last_time_went_live" for <member> if time difference is large enough.
        """
        try:
            # step 0: quickly jot down current time
            currtime = datetime.datetime.now()

            # step 1: get <member>'s previously recorded "last_time_went_live" value
            prevtime = self.get_attr(
                "last_time_went_live", str(member.guild.id), str(member.id)
            )

            # step 2: get time difference (if value returned), otherwise set new time and return True
            if prevtime not in ("", "n/a", None):
                prevtime = prevtime.strip('"')
                diff = currtime - datetime.datetime.strptime(
                    prevtime, "%m/%d/%Y %H:%M:%S"
                )

                # diagnostic line
                # print( 'live time diff:', diff.total_seconds() )

                # attempt to set new "last_time_went_live" value & return true
                if diff.total_seconds() > min_interval_sec:
                    self.update(
                        "set",
                        currtime.strftime("%m/%d/%Y %H:%M:%S"),
                        "last_time_went_live",
                        None,
                        member=member,
                    )
                    return True
                return False

            else:
                # set new "last_time_went_live" value & return true
                self.update(
                    "set",
                    currtime.strftime("%m/%d/%Y %H:%M:%S"),
                    "last_time_went_live",
                    None,
                    member=member,
                )

                # diagnostic line
                # print( '[updated <last_time_went_live> to {}'.format(
                #    currtime.strftime("%m/%d/%Y %H:%M:%S") ) )

                return True

        except:
            traceback.print_exc()
            return False

    def add_user_to_blacklist(self, gid: str, uid: str):
        """
        Attempts to add user to <blacklist>, otherwise pass.
        """
        try:
            size = len(self.blacklist_attrs)
            labels_str = ",".join([self.blacklist_attrs])
            values_str = uid + "," + ",".join(["n/a"] * (size - 1))
            cmd = "INSERT INTO blacklist ({}) VALUES ({})"
            cmd = cmd.format(labels_str, values_str)
            with self.connect(gid) as conn:
                cur = conn.cursor()
                cur.execute(cmd)
                conn.commit()

        # exceptions, exceptions...
        except sqlite3.OperationalError:
            traceback.print_exc()
        except sqlite3.IntegrityError:
            traceback.print_exc()
        except:
            traceback.print_exc()

    def remove_user_from_blacklist(self, gid: str, uid: str):
        """
        Attempts to remove user from <blacklist>, otherwise pass.
        """
        try:
            with self.connect(gid) as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM blacklist WHERE id=?", (uid,))
                conn.commit()

        # exceptions, exceptions...
        except sqlite3.OperationalError:
            traceback.print_exc()
        except sqlite3.IntegrityError:
            traceback.print_exc()
        except:
            traceback.print_exc()

    def remove_user_from_unverified(
        self, gid: str, uid: str, status_already_set: bool = False
    ):
        """
        DO THE FOLLOWING:
            1. remove user from the <unverified_users> table
            2. set user status in <udata> to "verified"
        """
        try:
            with self.connect(gid) as conn:
                cur = conn.cursor()

                # ACTION 1: remove user from unverified (they're verified now)
                cur.execute("DELETE FROM unverified_users WHERE id=?", (uid,))

                # ACTION 2: change user's <member_status> to "verified"
                if not status_already_set:
                    cur.execute(
                        "UPDATE udata set member_status = 'verified' WHERE id=?", (uid,)
                    )

                conn.commit()

        # exceptions, exceptions...
        except sqlite3.OperationalError:
            traceback.print_exc()
        except sqlite3.IntegrityError:
            traceback.print_exc()
        except:
            traceback.print_exc()

    def add_user_to_unverified(self, gid: str, uid: str):
        """
        Add specified user/member to the "unverified_users" database table.
        """
        try:
            # retrieve user-specific values to replace default unverified_users vals.
            vals = []
            append = vals.append
            for k, v in self.unverified_users_default_vals.items():
                if k == "id":
                    append(uid)
                else:
                    append(v["value"])

            # string formatting
            param_repeats = ",".join(["?"] * len(vals))
            cmd_string = "INSERT INTO unverified_users VALUES({})".format(param_repeats)

            # execute database operations
            with self.connect(gid) as conn:
                try:
                    cur = conn.cursor()
                    cur.execute(cmd_string, tuple(vals))
                    conn.commit()
                except sqlite3.IntegrityError:
                    pass
        except:
            traceback.print_exc()

    async def kaede_entrance_routine(self, user, bot_name="Kaede", delay=5.0):
        """
        Send a Direct Message (DM) to <user> when they enter the server;
        message guides user on how to get verified.

        <bot_name>: (Kaede/Yoshimura)
        <delay>:    time to wait before sending a DM
        """
        if user.bot:
            return

        msg = (
            "Welcome welcome, my beloved new member! I'm ***{}*** :innocent:\n\n"
            "Thank you so much for joining us! Now first thing's first, "
            "we need to get you **verified.** \n\n"
            "__Follow the steps in our `#rules` channel__ so we can give you "
            "**full access** to the community!"
            "\n\n\n__Example introductions:__\n"
            "> - briefly talk about what you want to improve on\n"
            "> - briefly talk about your interests (drawing, references, or other)\n"
            "> - talk about yourself or how you found the community\n"
            "> - OR introduce yourself another way!\n\n"
            "Thank you very much and welcome to the community! :blush:"
        )
        msg = msg.format(bot_name)
        embed = discord.Embed(colour=discord.Colour.green(), description=msg)

        await asyncio.sleep(delay)
        await user.send(embed=embed)


    """================================"""
    """STUFF FOR                       """
    """UPDATING ATTRIBUTES             """
    """BELOW HERE                      """
    """================================"""

    def update(
        self, action: str, amount, attr: str, message, table="udata", member=None
    ):
        """
        Centralized intermediary to access add(), multiply() or setval();
        An operation applies to a single user.
        """

        # "soft" restriction on allowed specified tables
        if table not in self.allowed_update_tables:
            return

        # no execution if "points" param passed;
        # UnbelievaBoat holds user balance data
        if attr == "points":
            return

        # check on <message> param
        # - if no <message> given, <member> MUST be present
        # - otherwise attempt to get IDs from <message> var.
        gid, uid = "", ""
        if (message is None) and member:
            gid = str(member.guild.id)
            uid = str(member.id)
        else:
            gid = str(message.guild.id)
            uid = str(message.author.id)

        # PRIMARY PAYLOAD
        contents = {
            "amount": amount,
            "attr": attr,
            "gid": gid,
            "uid": uid,
            "table": table,
        }

        # print('\n[update]...contents[attr] is:', attr)
        # print('[update]...contents[amount] is:', amount)
        # print('[update]...contents[table] is:', table, '\n')
        # print()

        try:
            # check update action to take
            if action in ("multiply", "mult"):
                self.multiply(contents)
            elif action == "add":
                self.add(contents)
            elif action in ("set", "setval"):
                self.setval(contents)
            else:
                print(f"[accessor.update] no action taken {action}")
        except:
            traceback.print_exc()

    def add(self, contents):
        """
        Add contents[amount] to contents[attr] in guild-associated db, or
        add <amount> to <attr> for <uid>
        """
        try:
            with self.connect(contents["gid"]) as conn:
                cur = conn.cursor()
                cmd = "UPDATE {} SET {} = {} + {} WHERE id = {}".format(
                    contents["table"],
                    contents["attr"],
                    contents["attr"],
                    contents["amount"],
                    contents["uid"],
                )
                cur.execute(cmd)
                conn.commit()
        except:
            traceback.print_exc()

    def multiply(self, contents):
        """
        Multiply contents[attr] in guild db by contents[amount] or,
        multiply <attr> for <uid> in db by <amount>;
        Note: can divide if ratio (e.g. 0.43) supplied as amount
        """
        try:
            with self.connect(contents["gid"]) as conn:
                cur = conn.cursor()
                cmd = "UPDATE {} SET {} = {} * {} WHERE id = {}".format(
                    contents["table"],
                    contents["attr"],
                    contents["attr"],
                    contents["amount"],
                    contents["uid"],
                )
                cur.execute(cmd)
                conn.commit()
        except:
            traceback.print_exc()

    def setval(self, contents):
        """Set <attr> for user <uid> = <amount>"""
        with self.connect(contents["gid"]) as conn:
            try:
                cur = conn.cursor()

                # print('contents[amount] is type:', type(contents['amount']))
                # print('contents[amount] data:', contents['amount'])

                # set value differently if value is a string type
                if isinstance(contents["amount"], str):
                    # contents['amount'] = "'" + contents['amount'] + "'"

                    cmd = "UPDATE {} SET {} = ? WHERE id = {}".format(
                        contents["table"], contents["attr"], contents["uid"]
                    )
                    # print( f"cmd is:\n{cmd}\n" )
                    cur.execute(cmd, (contents["amount"],))
                else:
                    cmd = "UPDATE {} SET {} = {} WHERE id = {}".format(
                        contents["table"],
                        contents["attr"],
                        contents["amount"],
                        contents["uid"],
                    )
                    # print( f"cmd is:\n{cmd}\n" )
                    cur.execute(cmd)

                conn.commit()
            except:
                traceback.print_exc()

    def ub_addpoints(
        self,
        gid,
        uid,
        reason_for_action,
        cash_amount: Optional[float] = None,
        bank_amount: Optional[float] = None,
        member: Optional[discord.Member] = None,
    ):
        """
        [dedicated method] Increment or decrement a user's balance (in UnbelievaBoat wallet).

        Accepts a (discord.Member) object in place of <gid> & <uid>.

        If decrementing, pass in a negative number.

        Issues a PATCH request to UnbelievaBoat's API.
        """

        if cash_amount is None and bank_amount is None:
            print("[ub_addpoints] both bank_amount and cash_amount are None")
            return None

        data = {
            "cash": cash_amount or 0,
            "bank": bank_amount or 0,
            "reason": reason_for_action,
        }

        if isinstance(member, discord.Member):
            gid = member.guild.id
            uid = member.id

        res = ub_patch(self.bot.user.id, gid, uid, data)
        print(f"[ub_addpoints] JSON response:\n\n{res.text}\n\n")
        return res

    def ub_setpoints(
        self,
        gid,
        uid,
        reason_for_action,
        cash_amount: Optional[float] = None,
        bank_amount: Optional[float] = None,
        member: Optional[discord.Member] = None,
    ):
        """
        [dedicated method] Set a user's balance (in UnbelievaBoat wallet).

        Accepts a (discord.Member) object in place of <gid> & <uid>

        Issues a PUT request to UnbelievaBoat's API.
        """
        if cash_amount is None and bank_amount is None:
            return None

        data = {
            "cash": cash_amount or 0,
            "bank": bank_amount or 0,
            "reason": reason_for_action,
        }

        if isinstance(member, discord.Member):
            gid = member.guild.id
            uid = member.id

        return ub_put(self.bot.user.id, gid, uid, data)

    def ub_getpoints(self, gid, uid, member: Optional[discord.Member] = None):
        """
        [dedicated method] Retrieve user's current balance (in UnbelievaBoat wallet).

        Accepts a (discord.Member) object in place of <gid> & <uid>

        Issues a GET request to UnbelievaBoat's API.
        """
        if isinstance(member, discord.Member):
            gid = member.guild.id
            uid = member.id

        return ub_get(self.bot.user.id, gid, uid)

    """================================"""
    """STUFF FOR                       """
    """LEVELING UP                     """
    """BELOW HERE                      """
    """================================"""

    def calc_next_level_xp(
        self, curr_level, a: float = 23, b: float = 1.4, expo: float = 1.73
    ):
        """
        Helper to calculate total xp (from 0 to ?) needed to reach next level.

        description
        -----------
            return amount of XP needed to reach level <curr>+1
        formula
        -------
            req_xp = ceil(23 * ((1.4 + X)^1.73) - 23)
        params
        ------
            curr_level:  user's current level
            a:           coefficient 1
            b:           coefficient 2
            expo:        exponent
        """
        return math.ceil(a * ((b + curr_level + 1) ** expo) - a)

    def can_levelup(self, message) -> bool:
        """
        Check if user's <gamble/normal> xp is enough to level up
        """
        with self.connect(str(message.guild.id)) as conn:
            uid = str(message.author.id)
            xp, level_type = "xp", "level"
            cur = conn.cursor()

            try:
                # fetch user xp
                cur.execute("SELECT {} FROM udata WHERE id={}".format(xp, uid))
                user_xp = cur.fetchone()

                # check if unsuccessful query
                if not user_xp:
                    print("[can_levelup]: no xp data")
                    return False
                user_xp = user_xp[0]

                # query for user's current level
                cur.execute("SELECT {} FROM udata WHERE id={}".format(level_type, uid))
                level = cur.fetchone()

                # check if unsuccessful query
                if not level:
                    print("[can_levelup]: no level data")
                    return False

                # return true if user has enough xp to level up
                level = level[0]
                return user_xp >= self.calc_next_level_xp(level)

            except:
                print("[can_levelup] ERROR:", end="")
                traceback.print_exc()

    def levelup(self, message):
        """
        Increment a user's level by 1. (for now, don't return anything)
        """

        # safety check, ensure enough xp to level up
        try:
            print(
                "[userdata_accessor] LEVELUP MECHANISM NOT IMPLEMENTED YET",
                file=sys.stderr,
            )
            return

            # TODO
            # TODO: LEVELUP MECHANISM NEEDS TO BE RE-EXAMINED!!!
            # TODO

            if self.can_levelup(message):
                level_type = "level"
                self.update("add", 1, level_type, message)

        except:
            print("[levelup] ERROR:")
            traceback.print_exc()

    def givepoints(self, message):
        """
        Primary client-side function to access the point distribution class;

        Note about 'flags':
            - it is a dict of point award enablers/disablers
            - naming is similar to distributor flags, for consistency
            - the following flags will be in this dict:
                > TEXT
                > TEXT_MED
                > TEXT_LONG
                > EMOTE
                > REACTION
                > IMAGE
                > VIDEO
                > URL
                > NO_POINTS
                > APPLY_REDUCTION
                > XP_REDUCTION (??)

        Assume: func is used post-command (no user check required);
        Note: distributor class is called "points"
        """
        try:
            if message.guild is None:
                return

            gid, uid = str(message.guild.id), str(message.author.id)

            # TEMPORARY lazy disable on point-earning in "waifu-wars" channel
            if message.channel.id == 896044032512360479:
                return

            # reset point flags
            if self.pt_flags["NO_POINTS"]:
                return self.reset_negative_flags()

            # retrieve user's awarded points (get_points() = tuple)
            a = self.distributor.get_points(message, self.pt_flags)
            awarded_points, awarded_xp = a

            # update/add xp
            self.update("add", awarded_xp, "xp", message)

            # update/add points--
            #   - value of calculated <awarded_points> must be at least 2
            #     points or more, otherwise it's a redundant point award
            #     for the same message that the UB bot already awards
            #     points for (1pt. per msg).
            #
            #   - 1 point is subtracted from <awarded_points> to account
            #     for the base amount (1 points) awarded per message,
            #     which the UB bot already awards for.
            if awarded_points >= 2.0:
                self.ub_addpoints(
                    None,
                    None,
                    "Msg-based point award.",
                    bank_amount=awarded_points - 1.0,  # subtract 1pt.
                    member=message.author,
                )

            # reset flags
            self.reset_negative_flags()

            # TODO: (last step) level up if enough xp; REENABLE WHEN READY
            # self.levelup(message)

        except:
            print("[givepoints() error]:")
            traceback.print_exc()

    def award_stream_points(
        self,
        stream_time_seconds,
        member: discord.Member,
        points_per_min=0.1,
        xp_on=True,
    ):
        """
        Give user points (optionally XP as well) for every minute they were streaming.
        """
        try:
            # convert seconds to minutes; calculate points
            awarded_points = points_per_min * (stream_time_seconds / 60)
            awarded_points = round(awarded_points, 1)

            # give points (and XP, if applicable)
            if xp_on:
                self.update("add", awarded_points, "xp", None, member=member)

            # ADDING POINTS TO USER'S BALANCE
            # (1 Sep. 2021):
            #   - commented out "self.update(...)", replaced with "self.ub_addpoints(...)"
            # self.update('add', awarded_points, 'points', None, member=member)
            return self.ub_addpoints(
                None,
                None,
                "Points for stream activity.",
                bank_amount=awarded_points,
                member=member,
            )

        except:
            print("[award_stream_points() error]:")
            traceback.print_exc()

    def userdata_backup_helper(self):
        """
        Helper method for saving userdata files.

        NOTE: this routine currently uses the `shutil` built-in Python
        library for copying userdata file(s).
        """
        for file in os.listdir(os_join(os.getcwd(), self.FOLDER)):

            # only make backups of non-backup files
            # assumption is the file ends with ".sqlite3" (UserDataAccessor.EXT_NAME)
            if not file.endswith(".backup"):

                # we can convert to the appropriate timezone externally if needed
                timestamp = datetime.datetime.now(timezone.utc)

                # build new filename to save;
                # name scheme: "{guild_id} {datetime}.sqlite3.backup"
                f = file[: file.find(self.EXT_NAME)]
                f += timestamp.strftime(" %Y:%m:%d-%H:%M:%S-%Z") + ".backup"
                fname = os_join(self.FOLDER, f)

                # make new backup copy
                shutil.copy2(os_join(self.FOLDER, file), fname)

    # looping task for autosaving user data
    @tasks.loop(minutes=360.0)  # every 6 hrs.
    async def autosave_userdata(self):
        """
        This routine should periodically create a backup file for all userdata files created by UserDataAccessor.

        Same naming convention as the regular userdata file will be used, but ".backup" will be appended to the backup name.

        For example:
            (normal file name)  :   "user_file.sqlite3"
            (backup file name)  :   "user_file.sqlite3.backup"
        """
        self.userdata_backup_helper()

    @commands.group("uda", hidden=True)
    @commands.guild_only()
    async def uda(self, ctx):
        if ctx.invoked_subcommand is None:
            pass

    @uda.command("backup", hidden=True)
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def uda_backup(self, ctx):
        """
        Use this subcommand (parent="uda") to manually create backups of userdata-related files for all guilds.
        """
        self.userdata_backup_helper()


def setup(bot):
    bot.add_cog(UserDataAccessor(bot))
