"""
This is a pseudo-interface superclass for all the main 'cogs' that have
Discord commands in them; "pseudo" because it holds data that will be
commonly accessed and referenced by other independent cogs that need
information on the current state of some if this data.
"""
import functools
import sys
import traceback


class GlobalCog:
    # userdata accessor object instance
    accessor_mirror = None
    schedule_mirror = None

    # flag indicates if zones are currently being loaded into memory
    zones_being_loaded = False

    # flag for indicating a long task is occurring
    long_process_active = False

    # flag for tracking the last time a member update happened (supports per-guild)
    last_member_update = {}

    # flag indicates if all tables were created successfully
    db_made = False

    # flag for preventing duplicate user-checking with <on_message()> event
    checking_user = False

    # initialize point distribution flags (needed for distributor class)
    pt_flags = {
        "TEXT": True,
        "TEXT_MED": True,
        "TEXT_LONG": True,
        "EMOTE": True,
        "REACITON": True,
        "IMAGE": True,
        "VIDEO": True,
        "URL": True,
        "NO_POINTS": False,
        "APPLY_REDUCTION": False,
        "XP_REDUCTION": False,
    }

    def reset_negative_flags(self):
        """
        Resets the negation flags to their initial values.
        e.g. "NO_POINTS"/"APPLY_REDUCTION"/"XP_REDUCTION"
        """
        self.pt_flags["NO_POINTS"] = False
        self.pt_flags["APPLY_REDUCTION"] = False
        self.pt_flags["XP_REDUCTION"] = False

    def set_clearance(level_N):
        """
        Static non-"self" DECORATOR to ensure only authorized users
        can use commands with specific clearance levels.
        """

        def inner_set_clearance(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                try:
                    # compare user CL with command-specified clearance level
                    user_CL = args[0].get_attr(
                        "clearance", str(args[1].guild.id), str(args[1].author.id)
                    )

                    if not user_CL or (user_CL < level_N):
                        # print to sys.stderr
                        print(
                            "\n[ACCESS DENIED]:" "\n\t>",
                            args[1].author.name,
                            "\n\t(UID=",
                            args[1].author.id,
                            ")",
                            "\n\t(GID=",
                            args[1].guild.id,
                            ")",
                            file=sys.stderr,
                        )
                        return
                    return await func(*args, **kwargs)

                except:
                    traceback.print_exc()

            return wrapper

        return inner_set_clearance

    def no_points():
        """Decorator to disable points for a given command"""

        def inner_no_points(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                args[0].set_flag("NO_POINTS", True)
                return await func(*args, **kwargs)

            return wrapper

        return inner_no_points

    def set_flag(self, flag: str, val: bool):
        """
        Set a given flag True or False; check if exists of course...
        """
        if flag in self.pt_flags:
            self.pt_flags[flag] = val
        else:
            print(f"[[GlobalCog.set_flag]: flag ({flag}) doesn't exist.")

    def get_attr(self, attr: str, gid: str, uid: str):
        """
        Mirror function to use userdata_accessor's 'get_attr' method
        """
        try:
            return GlobalCog.accessor_mirror.get_attr(attr, gid, uid)
        except:
            traceback.print_exc()
