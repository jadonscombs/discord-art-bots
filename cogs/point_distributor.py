import discord
from discord.ext import commands
import emojis
import re
from utils.sync_utils import get_links


class Distributor(commands.Cog):
    """
    Class for handling point-awarding mechanisms and distribution.
    """

    def __init__(self, bot, fname=None):
        self.bot = bot

        # set distribution of points
        self.pdistribution = {}
        if fname:
            self.set_points_distribution(fname)
        else:
            self.set_points_distribution()

        # define flags/limits here
        self.TEXT_LEN = 2  # X chars or more in message
        self.TEXT_LEN_MED = 50  # X chars or more in message
        self.TEXT_LEN_LONG = 185  # X chars or more in message

        self.NO_POINTS = False  # don't award points if true
        self.APPLY_REDUCTION = False  # reduce points awarded if true
        self.XP_REDUCTION = False  # reduce xp awarded if true

        # global reduction ratio if APPLY_REDUCTION is True;
        # custom reduction ratio can be applied per criteria check
        self.PT_REDUCE_RATIO = 0.5
        self.XP_REDUCE_RATIO = 0.5

    def set_points_distribution(self, fname="action_point_distribution.txt"):
        """
        Assign point distribution to use when giving points for user actions
        """

        tmpdict = {}
        lines = []

        # read all file lines
        try:
            with open(fname, "r") as f:
                lines = f.readlines()
        except:
            with open("cogs/" + fname, "r") as f:
                lines = f.readlines()
        finally:
            # populate dict with each line
            for line in lines:
                tmp = line.split(",")
                tmpdict.update({tmp[0]: float(tmp[1])})

            # assign initialized dict to pdistribution
            self.pdistribution = tmpdict

    def flag_switch(self, flag, is_true: bool):
        """
        Switch-case implementation for determining what points are
        allowed to be given based on input flags
        """

        if self.pdistribution:
            # find and execute method attributed to flag
            method_name = f"{flag}_flag"
            method = getattr(
                self, method_name, lambda x: "[Distributor]: Invalid flag."
            )
            return method(is_true)

        print("[Distributor.flag_switch]: BAD FLAG")
        return -1

    # CURRENT LIST OF ALL THE FLAGS USED IN THE POINT DISTRIBUTOR
    def text_flag(self, is_true: bool):
        return self.pdistribution["text"] if is_true else 0

    def text_med_flag(self, is_true: bool):
        return self.pdistribution["text_med"] if is_true else 0

    def text_long_flag(self, is_true: bool):
        return self.pdistribution["text_long"] if is_true else 0

    def reaction_flag(self, is_true: bool):
        return self.pdistribution["reaction"] if is_true else 0

    def emote_flag(self, is_true: bool):
        return self.pdistribution["emote"] if is_true else 0

    def image_flag(self, is_true: bool):
        return self.pdistribution["image"] if is_true else 0

    def video_flag(self, is_true: bool):
        return self.pdistribution["video_upload"] if is_true else 0

    def url_flag(self, is_true: bool):
        return self.pdistribution["url"] if is_true else 0

    def get_points(self, message, flags):
        """
        CLIENT-SIDE function to determine most point criteria for a message;
        May return a tuple of awarded points, and awarded xp;

        'message': discord.Message object

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
        """

        if message.content is None or flags["NO_POINTS"]:
            return (0, 0)

        awarded_points, awarded_xp = 0.0, 0.0

        # checking text length criteria
        awarded_points += self.get_text_points(message.content, flags)

        # checking emoji criteria
        awarded_points += self.get_emoji_points(message.clean_content, flags)

        # checking image/embed criteria (incl. video)
        awarded_points += self.get_embed_points(message.embeds, flags)

        # (TODO) checking url criteria
        awarded_points += self.get_url_points(message.content, flags)

        # calculate awarded xp (check xp reduction flag)
        if self.XP_REDUCTION:
            awarded_xp += (self.XP_REDUCE_RATIO) * awarded_points
        else:
            awarded_xp += awarded_points

        return (awarded_points, awarded_xp)

    def get_text_points(self, txt_msg: str, flags):
        """
        Return message's award points based on text length
        """

        # check if flag "NO_POINTS" is enabled
        if self.NO_POINTS:
            return 0.0

        awarded_points = 0.0

        # points amount conditionally based on text length
        if len(txt_msg) >= self.TEXT_LEN_LONG:
            awarded_points += self.flag_switch("text_long", flags["TEXT_LONG"])
        elif len(txt_msg) >= self.TEXT_LEN_MED:
            awarded_points += self.flag_switch("text_med", flags["TEXT_MED"])
        else:
            awarded_points += self.flag_switch("text", flags["TEXT"])

        return awarded_points

    def get_emoji_points(self, msg: str, flags, hi=10, hi_coeff=2.1):
        """
        Determine points to award msg based on # of emojis present
        """

        # check if flag "NO_POINTS" is enabled
        if self.NO_POINTS:
            return 0.0

        # num_emojis = self.find_num_emojis(txt_msg, custom=True) + \
        #             self.find_num_emojis(txt_msg, custom=False)
        num_emojis = emojis.count(msg)

        # if user put more than <hi> amount of emojis, give more points
        if num_emojis > hi:
            return (hi_coeff) * self.flag_switch("emote", flags["EMOTE"])

        # otherwise, standard point rewarding
        if num_emojis >= 1:
            return self.flag_switch("emote", flags["EMOTE"])

        return 0.0

    # def find_num_emojis(self, txt_msg: str, custom=False):
    # '''
    # Return number of emojis found in string;
    # Source: https://stackoverflow.com/questions/54859876/
    # how-check-on-message-if-message-has-emoji-for-discord-py
    # '''
    # emojis = None
    # if custom: emojis = re.findall(r'<:\w\w*:\d*>', txt_msg)
    # else: emojis = re.findall(r':\w\w*:', txt_msg)

    # return len(emojis)

    def get_embed_points(self, embeds, flags):
        """
        Return points based on # of embeds found in msg
        """

        # check if flag "NO_POINTS" is enabled
        if self.NO_POINTS:
            return 0.0

        awarded_points = 0.0

        for embed in embeds:
            if embed.video:  # if video upload
                awarded_points += self.flag_switch("video", flags["VIDEO"])
            elif embed.image:  # if image upload
                awarded_points += self.flag_switch("image", flags["IMAGE"])

        return awarded_points

    def get_reaction_points(self):
        """
        Return points for a single reaction;
        Usually called by async "on_message_reaction()" method?
        """

        return self.pdistribution["reaction"]

    def get_url_points(self, msg: str, flags):
        """
        Return points calculated based on the presence of URLs present in a message.
        """

        # check if flag "NO_POINTS" is enabled
        if (not self.NO_POINTS) and (len(get_links(msg)) > 0):
            return self.flag_switch("url", flags["URL"])
        return 0


""" ======================= COGLOADING + MAIN ====================== """


def setup(bot):
    bot.add_cog(Distributor(bot))
    print("[distributor] cog loaded!")


# basic tests below
if __name__ == "__main__":
    print("Begin simple [distributor] tests...")

    bot = None

    d = Distributor(bot)
    print(d.pdistribution)
    print(bool(d.pdistribution))  # confirm dict is not empty

    val = d.flag_switch("text", True)
    print(val, "\t", bool(val))  # confirm switching properly
    # (distrib file info assumed present)

    print("End simple [distributor] tests.")
