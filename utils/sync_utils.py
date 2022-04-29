"""
Small collection of synchronous (normal) methods/functions/utilities.
"""
import discord
from discord.ext.commands import when_mentioned_or
from blop_tknloader import unbelievaboat_token as ub_tkn
import json
import os
from ratelimit import limits
import re
import requests
from requests import patch, get, put
import traceback


# common resources
UB_BASE_URL = "https://unbelievaboat.com/api/v1"
UB_USER_TEMPLATE_URL = UB_BASE_URL + "/guilds/{}/users/{}"
# UB_TKN = "Token {}"
UB_TKN = "{}"


def create_prefixes_file(path="prefixes.json"):
    if not os.path.isfile(path):
        with open(path, "w") as f:
            json.dump({"kaede": {}, "yoshimura": {}}, f, indent=4)


def get_prefix(bot, message):
    try:
        if message.guild is None:
            return "!"

        create_prefixes_file()
        botname = bot.user.name.lower()

        with open("prefixes.json", "r") as f:
            prefixes = json.load(f)

        if prefixes[botname] in (None, ""):
            prefixes[botname] = "!"
            with open("prefixes.json", "w") as f:
                json.dump(prefixes, f, indent=4)
        return when_mentioned_or(prefixes[botname])(bot, message)

    except:
        traceback.print_exc()
        return "!"


def get_prefix_str(bot, message):
    try:
        if message.guild is None:
            return "!"

        create_prefixes_file()
        botname = bot.user.name.lower()

        with open("prefixes.json", "r") as f:
            prefixes = json.load(f)

        if prefixes[bot.user.name.lower()] in (None, ""):
            prefixes[botname] = "!"
            with open("prefixes.json", "w") as f:
                json.dump(prefixes, f, indent=4)
        return prefixes[botname]

    except:
        traceback.print_exc()
        return "!"


def get_links(s):
    """
    Returns a list of URLs found in string.
    """
    return re.findall(r"(https?://\S+)", s)


@limits(calls=10, period=1.0)
def ub_get(bot_id, gid, uid):
    url = UB_USER_TEMPLATE_URL.format(gid, uid)
    head = {"Authorization": UB_TKN.format(ub_tkn(bot_id))}
    return get(url, headers=head)


@limits(calls=10, period=1.0)
def ub_put(bot_id, gid, uid, data):
    url = UB_USER_TEMPLATE_URL.format(gid, uid)
    head = {
        "Accept": "application/json",
        "Authorization": UB_TKN.format(ub_tkn(bot_id)),
    }
    return put(url, data=json.dumps(data), headers=head)


@limits(calls=20, period=1.0)
def ub_patch(bot_id, gid, uid, data):
    url = UB_USER_TEMPLATE_URL.format(gid, uid)
    head = {
        "Accept": "application/json",
        "Authorization": UB_TKN.format(ub_tkn(bot_id)),
    }

    # print((
    #    f"[ub_addpoints] prepped request:\n\n"
    #    f"url: {url}\n"
    #    f"headers:\n{head}\n"
    #    f"data:\n{data}"
    #    f"\n\n"
    # ))

    return patch(url, data=json.dumps(data), headers=head)
