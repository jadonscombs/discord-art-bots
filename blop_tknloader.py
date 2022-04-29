import json


def bot_token(bot_name) -> str:
    """
    Function to return discord bot token.

    Specify "Kaede" or "Yoshimura" as bot name to get proper token
        - result is "Kaedetoken.json" or "Yoshimuratoken.json"
    """

    # default token filename: "bot_token.json"
    #
    # json format:
    #   {   "Yoshimura":    "<token_1>",
    #           ...         ...
    #       "Kaede":        "<token_N>"
    #   }

    with open("bot_token.json") as f:
        token = json.load(f)[str(bot_name)]
        return token


def unbelievaboat_token(bot_id) -> str:
    """
    Function to retrieve and return UnbelievaBoat API token associated with given bot <bot_id>.

    Bot ID must belong to Kaede or Yoshimura.
    """

    # default token filename: "ub_token.json"
    #
    # json format:
    #   {   "0325073215352315": "<token_1>",
    #           ...         ...
    #       "8994854324082452": "<token_N>"
    #   }

    with open("ub_token.json") as f:
        token = json.load(f)[str(bot_id)]
        return token
