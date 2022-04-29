"""
This is VERSION 2 (V2) of TaskScheduler.
The primary scheduler module used is "schedule.py"
"""

import discord
from discord.ext import commands

try:
    import cogs.globalcog as globalcog
    from cogs.globalcog import GlobalCog
except:
    import globalcog
    from globalcog import GlobalCog

from cogs.userdata_accessor import UserDataAccessor

import asyncio
import datetime
import emojis
import functools
import hashlib
import inspect
import json
import os
import pdb  # use 'pdb.set_trace()' wherever you want to trace code exec.
import praw
import random
import schedule
import sys
import threading
import time
import traceback
import uuid
import weakref


class SafeScheduler(schedule.Scheduler):
    """
    Wrapper class for schedule.Scheduler.
    Implements (slight modification to):
        - __init__(...)
        - _run_job(...)
        - run_continuously(...)
        - do(...)
    """

    def __init__(self):
        super().__init__()

    ##    def do(self, job_func, *args, **kwargs):
    ##        '''
    ##        Overwrites what base Scheduler.do() does.
    ##        '''
    ##        self.job_func = functools.partialmethod(job_func, *args, **kwargs)
    ##        try:
    ##            functools.update_wrapper(self.job_func, job_func)
    ##            pass
    ##        except AttributeError:
    ##            # job_funcs already wrapped by functools.partial won't have
    ##            # __name__, __module__ or __doc__ and the update_wrapper()
    ##            # call will fail.
    ##            pass
    ##        self._schedule_next_run()
    ##        self.scheduler.jobs.append(self)
    ##        return self

    def _run_job(self, job):
        try:
            super()._run_job(job)
        except:
            traceback.print_exc()
            job.last_run = datetime.datetime.now()
            job._schedule_next_run()

    def run_continuously(self, interval=1):
        """
        Method invokes superclass' (Schedule(r)) run_continuously() method
        """
        try:
            super().run_continuously(interval)
        except Exception:
            traceback.print_exc()


class TaskScheduler(commands.Cog, GlobalCog):
    """
    Module dedicated to scheduling things (like reminders).

    Designed to be "thread-safe" in case of execution errors!
    """

    # References:
    #   - gist.github.com/mplewis/8483f1c24f2d6259aef6 (SafeScheduler)

    _self = None

    DAYS_OF_WEEK = (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )
    DAYS_ABBREV = ("M", "T", "W", "Th", "F", "Sa", "Su")

    # MAXIMUM NUMBER OF REMINDERS ALLOWED PER USER
    REMINDER_LIMIT_PER_USER = 4

    def __init__(self, bot):
        self.bot = bot
        self.ts = SafeScheduler()  # ts = "taskscheduler"
        self.__class__._self = self

        # load any recurring tasks listed in given file
        # tracks curr. jobs while bot is online
        self.job_dict = json.loads("{}")
        job_fpath = "json_jobs.json"
        self.load_jobs(job_fpath)

        # get extra event loop (~thread) specifically for scheduler
        # self.loop = asyncio.get_event_loop()???

        """
        This is a threading.Event object (continuous_run_obj).
        "run_continuously(interval)" puts Scheduler instance
        in another thread of control (non-main thread), so it
        does not conflict with <discord.py>'s async functionality.

        DIRECTIONS:
            Use this object's 4 methods to modify flag or wait();
            Ref: docs.python.org/3.7/library/threading.html#threading.Event

            - is_set(), set(), clear(), wait(timeout=None)
        """
        self.ts.run_continuously(interval=0.5)

    async def react_success(self, ctx):
        """
        React to the supplied ctx.message with a 'check mark'
        """
        await ctx.message.add_reaction("\N{HEAVY CHECK MARK}")

    async def react_fail(self, ctx):
        """
        React to the supplied ctx.message with a 'cross mark'
        """
        await ctx.message.add_reaction("\N{CROSS MARK}")

    def load_jobs(self, fpath="json_jobs.json"):
        """
        This will load all user and non-user jobs from a file.
        ALL periodic/recurrent jobs are stored here, regardless of server.
        """
        try:
            # load in hard-coded (non-user) jobs first
            self.load_nonuser_jobs()

            # > load <f> into JSON object;
            # create jobfile with self.save_jobs()
            if not os.path.exists(fpath):
                if self.save_jobs() < 0 and not os.path.exists(fpath):
                    raise RuntimeError()
            with open(fpath, "r") as f:
                try:
                    self.job_dict = json.load(f)
                except:
                    traceback.print_exc()
                    self.job_dict = {}

            # statistics -- report ratio of jobs succcessfully loaded
            print("now parsing jobs file.")
            hit, miss = 0, 0
            for job_id in self.job_dict.keys():
                result = self.load_job(job_id)
                if result:
                    hit += 1
                else:
                    miss += 1
            self.save_jobs()

            hit_ratio = 0
            if hit + miss > 0:
                hit_ratio = hit / (hit + miss)
            print(
                "done parsing jobs file. success = {}/{} = {}".format(
                    hit, hit + miss, hit_ratio
                )
            )
        except:
            traceback.print_exc()

    def load_job(self, job_id, job_dict=None):
        """
        Schedule and load one (1) job (via ID), into self.job_dict.
        ASSUME: the job whose id is <job_id> has not been scheduled yet.

        RETURN: scheduler.Job object that was scheduled
        """
        try:
            # <job_dict> is JSON object, not a dict()
            if job_dict is None:
                job_dict = self.job_dict
            info = job_dict[job_id]
            if info["runs_left"] <= 0:
                job_dict.pop(job_id, None)
                return -2

            # assemble job components/variables
            interval = info["interval"]
            unit = info["unit"]
            at_time = info["at_time"]
            next_run = info["next_run"]
            f = self.str2jobfunc(info["do"])
            args = self.unserialize_args(info["args"])
            tags = info["tags"]
            important = info["i"]
            components = [interval, unit, at_time, next_run, f, args, tags]

            # create & schedule job with components
            j = self.parse_sched_components(components)

            # change next_run date + other relevant job attrs. if necessary
            j = self.parse_next_run_logic(j, next_run, important)

            # save jobs status to file and to job_dict
            self.store_job(j, job_id, info["runs_left"], important)
            return j

        except:
            traceback.print_exc()
            return None

    def load_nonuser_jobs(self):
        """
        Schedules hard-coded jobs that the bot should always run.
        """
        try:
            # daily cat/owl job
            # self.ts.every().day.at('17:05').do(
            #    TaskScheduler.do_func, None,
            #    True, self.dailycat, skip_store=True)
            # self.ts.every().day.at('17:15').do(
            #    TaskScheduler.do_func, None,
            #    True, self.dailyowl, skip_store=True)

            # point giveaway
            pass

        except:
            traceback.print_exc()

    def parse_next_run_logic(self, job, next_run, i, job_fmt="obj", cmd="remindme"):
        """
        Includes logic for chaning a job's <next_run> attribute in case
        the bot needs to recalculate when the next run should be,
        depending on the command and other contextual information.
        ASSUME: job.tags[-1] is the job ID

        RETURN: the job that was changed

        PARAMS
        ------
            job:
                can be string or scheduler.Job; <job_fmt> should specify
            next_run:
                string object representing date of next time to run.
                gets converted to datetime.datetime object
            i:
                bool; if True, job is important
            job_fmt:
                should dictate the type of param to expect from <job>
            cmd:
                string. helps determine course of parse action based
                on the context of the command that uses it

        Used by:
        - load_job(...)
        """
        try:
            if cmd != "remindme":
                return None
            if job_fmt != "obj":
                return None

            # convert next_run to datetime object
            if next_run is not None:
                if isinstance(next_run, str):
                    next_run = datetime.datetime.strptime(next_run, "%Y-%m-%d %H:%M:%S")

            job_id = list(job.tags)[-1]

            datefmt1 = "%Y-%m-%d %H:%M:%S"
            now = datetime.datetime.now()
            delta = now - next_run  # datetime.timedelta object
            hrs = divmod(delta.total_seconds(), 3600)[0]

            # CASE 0: if NOT important <i> and 4+ hours passed, remove job
            if not i and hrs >= 4:
                self.job_dict.pop(job_id, None)
                self.save_jobs()
                return None

            # CASE 1: if delta at least 30 seconds early, reschedule
            # using existing (stored) next_run date
            if delta.total_seconds() < -30:
                job.next_run = next_run
                return job

            # CASE 2: if delta < 8 hrs, task is late, but not too late...
            if hrs < 8:
                if self.ts.next_run is not None:
                    a = self.ts.idle_seconds

                # minimum 30 sec. separation between tasks
                x = max(delta.total_seconds(), a + 30)

                # rescheduling task to a less "nocturnal" time
                newtime = next_run + datetime.timedelta(seconds=x)
                newhr = int(newtime.strftime("%H"))
                if newhr > 3 and newhr < 8:  # 3am - 8am
                    newtime = newtime.replace(hour=8, minute=0, second=0)
                job.next_run = newtime
                return job

            # CASE 3: if delta > 8 hrs, task is WAY too late.
            # schedule for today, but same time
            if hrs > 8:
                if self.ts.next_run is not None:
                    a = divmod(self.ts.idle_seconds, 60)[0]
                tremain = divmod(delta.total_seconds(), 60)[0]

                # minimum 1 minute separation between tasks
                x = max(tremain, a + 1)
                job.next_run = next_run.replace(day=datetime.date.today().day)
                return job

        except:
            traceback.print_exc()
            return None

    def parse_sched_components(self, args):
        """
        Return a scheduled job based on the components provided in <args>.

        <args> order:
        args[0] = job interval (number)
        args[1] = job unit (string)
        args[2] = job at_time (string format: '%H:%M:%S')
        args[3] = job next_run (string format: '%Y-%m-%d %H:%M:%S')
        args[4] = target function object to execute (callable func. obj.)
        args[5] = target function args (list)
        args[6] = job tags (list-like or set)
        """
        try:
            j = self.ts.every(args[0])
            j = getattr(j, args[1])

            # convert at_time to datetime object
            if args[2] is not None:
                if isinstance(args[2], str):
                    args[2] = datetime.datetime.strptime(args[2], "%H:%M:%S")
                j = j.at(args[2])

            # assign job func + args, and next_run datetime object (args[3])
            return j.do(args[4], *args[5]).tag(*args[6])
        except:
            traceback.print_exc()
            return None

    def save_jobs(self, fpath="json_jobs.json"):
        """
        Save the current info held in <self.job_dict> to file.
        ASSUME: <store_new_job()> was already called before this.

        RETURN: 0 (success),  -1 (error)
        """
        if self.job_dict is not None:
            try:
                # dump job_dict content into 'json_jobs.json'
                with open(fpath, "w") as jobs_outfile:
                    json.dump(self.job_dict, jobs_outfile, indent=4)
                return 0
            except FileNotFoundError:
                print("error: job file not found.")
            except:
                traceback.print_exc()
        return -1

    def store_job(self, job, job_id=None, runs_left=1, i=False):
        """
        Stores a newly scheduled task/job into the <jobs> JSON dict, and
        saves the changes accordingly.

        RETURN: the updated/saved <jobs> JSON dict.

        PARAMS
        ------
            job:
                scheduler.Job object
            job_id:
                if None, an ID will be randomly generated
            runs_left:
                the number of times to reschedule the job
        """
        try:
            if self.job_dict is None:
                raise RuntimeError()
            if job_id is None:
                job_id = uuid.uuid4()

            # converting at_time to string
            at_time = None
            if job.at_time is not None:
                at_time = job.at_time.strftime("%H:%M:%S")

            # converting next_run to string
            next_run = None
            if job.next_run is not None:
                next_run = job.next_run.strftime("%Y-%m-%d %H:%M:%S")

            # storing data as new entry in self.job_dict
            self.job_dict[job_id] = {
                "i": i,
                "runs_left": runs_left,  # default is 1
                "interval": job.interval,
                "unit": job.unit,
                "at_time": at_time,
                "do": self.jobfunc2str(job.job_func),
                "args": self.serialize_args(job.job_func.args),
                "next_run": next_run,
                "tags": list(job.tags),
            }

            # now update JSON dict with new job data entry
            success = self.save_jobs()
            if success == 0:
                return self.job_dict
            return None

        except RuntimeError:
            raise RuntimeError("cannot store job because<job_dict> is NoneType.")
        except:
            traceback.print_exc()
            return None

    def remove_job(self, job, save=True):
        try:
            job_id = list(job.tags)[0]
            self.ts.cancel_job(job)
            self.job_dict.pop(job_id, None)
            if save:
                self.save_jobs()
        except:
            traceback.print_exc()

    def hash_task_id(items):
        """
        Generate a hashable ID based on the elements in <items>.
        ASSUME: elements in <items> can be cast to <str> type.

        RETURN: str-casted int hash value; or -1 (if error).

        NOTES:  current scheme is to concatenate str(i) for i in <items>;
                current hash character length is --> 15
        """
        if len(items) == 0 or len(items) > 250:
            return -1
        try:
            # OPTION 1:
            strtohash = "".join(map(str, items))
            m = hashlib.md5()
            m.update(strtohash.encode("utf-8"))
            return str(int(m.hexdigest(), 16))[:15]
        except:
            traceback.print_exc()
            return -1

    ##    def get_class_that_defined_method(meth):
    ##        '''
    ##        THIS IS NOT MY FUNCTION. SOURCE IS BELOW:
    ##        https://stackoverflow.com/questions/
    ##        3589311/get-defining-class-of-unbound-method-object-in-python-3/
    ##        '''
    ##        if inspect.ismethod(meth):
    ##            for cls in inspect.getmro(meth.__self__.__class__):
    ##                if cls.__dict__.get(meth.__name__) is meth: return cls
    ##            meth = meth.__func__  # fallback to __qualname__ parsing
    ##
    ##        if inspect.isfunction(meth):
    ##            cls = getattr(inspect.getmodule(meth),
    ##                          meth.__qualname__.split(
    ##                              '.<locals>', 1)[0].rsplit('.', 1)[0])
    ##            if isinstance(cls, type): return cls
    ##
    ##        # handle special descriptor objects
    ##        return getattr(meth, '__objclass__', None)

    def serialize_args(self, args):
        """
        Convert any arguments in <args> into a convertable
        string representation. E.g., from type <method> to 'string'
        that can be looked up via some dict.

        RETURN: list of args, properly converted and serialized
        """
        try:
            verified = []
            append = verified.append
            for arg in args:
                if callable(arg):
                    arg = "func" + self.jobfunc2str(arg)
                append(arg)
            return verified
        except:
            traceback.print_exc()
            return None

    def unserialize_args(self, args):
        """
        Convert serialized args (via serialize_args()) to
        a list of args properly parsed.
        """
        try:
            verified = []
            append = verified.append
            for arg in args:
                if isinstance(arg, str) and len(arg) > 4:
                    if arg[:4] == "func":
                        arg = self.str2jobfunc(arg[4:])
                append(arg)
            return verified
        except:
            traceback.print_exc()
            return None

    def jobfunc2str(self, f):
        """
        Return string representation/attributes of function object.
        """
        try:
            # module = inspect.getmodule( f )
            # below (3) lines commented out -- 6/20/2020
            # print('jobfunc2str -> module name={}'.format(module))
            # if module == 'builtins': return f.__name__
            # return '.'.join( [module, f.__name__] )

            class_and_method = f.__qualname__
            return class_and_method

        except:
            traceback.print_exc()
            raise RuntimeError()

    def str2jobfunc(self, s):
        """
        Convert string representation/attrs. of function to actual object
        """
        try:
            s = s.split(".")
            # print('str2jobfunc -> input s={}'.format(s))
            if len(s) == 1:
                return getattr("builtins", s[0])

            # mod = sys.modules[s[0]]
            # print('str2jobfunc -> mod={}'.format(mod))

            # func_class = getattr( mod, s[-2]) # new addition
            # func_class = getattr( sys.modules[ s[-3]], s[-2] )

            return getattr(globals()[s[-2]], s[-1])

        except:
            traceback.print_exc()
            raise RuntimeError()

    async def schedule_once(self, sched_date, is_async, taglist, func, *args, **kwargs):
        """
        Call this method to schedule a job to run once at <sched_date>.

        THIS IS USUALLY CALLED BY an async TaskScheduler method that
        works directly/indirectly with discord.py.

        RETURN: scheduler.Job

        params
        ------
            sched_date:
                datetime.datetime() object; date/time of execution
            is_async:
                True if <func> is an "async" function
            taglist:
                list of identifying attributes (helps enable cancelling jobs)
            *args, **kwargs:
                Function args and kwargs, lol
        """
        try:
            # ERROR: NoneType or null-equivalent date
            if not sched_date:
                return -1

            # CASE HANDLING: <sched_date> = a day of the week
            d = ""
            obj = self.ts.every()
            if sched_date in self.DAYS_OF_WEEK:
                d = sched_date
                if d == "monday":
                    obj = obj.monday
                elif d == "tuesday":
                    obj = obj.tuesday
                elif d == "wednesday":
                    obj = obj.wednesday
                elif d == "thursday":
                    obj = obj.thursday
                elif d == "friday":
                    obj = obj.friday
                elif d == "saturday":
                    obj = obj.saturday
                elif d == "sunday":
                    obj = obj.sunday
                else:
                    return -1

                # obj.do(self.do_func, is_async, func,
                #       *args, **kwargs).tag(*taglist, 'run_once')
                # return 0
                return obj.do(self.do_func, is_async, func, *args, **kwargs).tag(
                    *taglist
                )

            # CASE HANDLING: <sched_date> = specific time (HMS format)
            elif sched_date > 0:
                # self.ts.every(sched_date).seconds.do(
                #    self.do_func, is_async, func,
                #    *args, **kwargs).tag(*taglist, 'run_once')
                # return 0
                return (
                    self.ts.every(sched_date)
                    .seconds.do(self.do_func, is_async, func, *args, **kwargs)
                    .tag(*taglist)
                )

            else:
                return -1
        except:
            traceback.print_exc()
            return -1

    def find_jobs(self, tags, ref=False):
        """
        Return a list of task/job IDs associated with a <gid> and <uid>.
        The tasks/jobs are found by look at all active jobs' tags.

        If <ref> is True, return job references/objects instead.
        """
        tags = set(tags)
        results = []
        append = results.append
        is_subset = tags.issubset

        # branch 1: returning job objects/references
        if ref:
            for job in self.ts.jobs:
                if is_subset(job.tags):
                    append(job)
            return results

        # branch 2: returning job IDs instead
        info = None
        for taskID in self.job_dict.keys():
            info = self.job_dict[taskID]
            if is_subset(set(info["tags"])):
                append(taskID)
        return results

    def timed2datetime(self, time_str: str, time_format=0):
        """
        RETURN: formatted datetime.datetime() object of given
        time duration (represented by time_str). or None

        THIS IS USUALLY CALLED BY (self) TaskScheduler.schedule_once().

        ASSUMPTION(S):
            - IMPLIED USAGE via one-time scheduling

        w,d,h,m,s = weeks,days,hours,minutes,seconds

        TIME format: (order = days,hours,minutes,seconds)
            - 4d,3h,16m,10s
            - 42d,24h,3m
            - 12h
            - 3h,2s
            - (any format as long as order ^^ is retained)

        params
        ------
            time_format:
                - 0 (default): XXw,XXd,XXh,XXm,XXs
                - TBD
        """
        try:
            # check if <time_str> is empty or has invalid format
            if time_str == "":
                return None
            timeparts = time_str.split(",")
            if len(timeparts) == 0:
                return None

            # declare default time values;
            # secs=1 to delay immediate execution
            days, DAYS_LIMIT = 0, 14
            hrs, HRS_LIMIT = 0, 120
            mins, MINS_LIMIT = 0, 500
            secs, SECS_LIMIT = 1, 1000

            # attempt to parse all time parts/components
            partval = 0
            unit = ""
            units_seen = []
            for part in timeparts:
                try:
                    unit = part[-1].lower()

                    # ERROR: duplicate time unit arguments seen;
                    # e.g. "7w 3w 4d" or "5m 3m"
                    if unit in units_seen:
                        return None
                    units_seen.append(unit)

                    # ERROR: unrecognized time unit
                    if unit not in ("w", "d", "h", "m", "s"):
                        return None

                    # ERROR: do not accept negative numbers!
                    partval = int(part[:-1])
                    if partval < 0:
                        return None

                    if part[-1] == "w":  # weeks (convert to days)
                        days += 7 * partval
                    elif part[-1] == "d":  # days
                        days += partval
                    elif part[-1] == "h":  # hours (convert to mins)
                        mins += 60 * partval
                    elif part[-1] == "m":  # minutes
                        mins += partval
                    elif part[-1] == "s":  # seconds
                        secs += partval
                    else:
                        return None  # ??? ERROR ???
                except:
                    traceback.print_exc()
                    return None

            # use datetime to calculate time offset
            run_date = datetime.datetime.now()
            copy_run_date = run_date
            delta = datetime.timedelta(days=days, minutes=mins, seconds=secs)
            run_date = run_date + delta

            # experimental line
            # delta = datetime.timedelta(
            #    days=(run_date.day - copy_run_date.day),
            #    hours=(run_date.hour - copy_run_date.hour),
            #    minutes=(run_date.minute - copy_run_date.minute),
            #    seconds=(run_date.second - copy_run_date.second))

            # print("[time2datetime] run date: {}".format(run_date))
            # print("[time2datetime] delta date: {}".format(delta))
            # return run_date
            return (days * 24 * 3600) + (mins * 60) + secs

        except:
            traceback.print_exc()
            return None

    def do_func(job_id, is_async, func, *args, skip_store=False, **kwargs):
        """
        Mediator to execute a function depending on whether it's async or not
        """

        try:
            self = getattr(TaskScheduler, "_self")

            # CASE 0: func does NOT want to be stored/backed up
            if skip_store:
                # branch 1: target func <func> is async
                if is_async:
                    fut = asyncio.run_coroutine_threadsafe(
                        func(*args, **kwargs), self.bot.loop
                    )
                    return fut.result()
                else:
                    return func(*args, **kwargs)

            # CASE 1: (DEFAULT)
            runs_left = self.job_dict[job_id]["runs_left"]

            if runs_left <= 0:
                job = self.find_jobs([job_id], ref=True)
                print("do_func -> found jobs:\n", job)
                self.remove_job(job[0])
                return 0

            x = None
            # branch 1: target func <func> is async
            if is_async:
                fut = asyncio.run_coroutine_threadsafe(
                    func(*args, **kwargs), self.bot.loop
                )

                # Future.result() executes registered function
                x = fut.result()

            # branch 2: target func is not async
            else:
                x = func(*args, **kwargs)

            # final step, save current state of current jobs
            self.job_dict[job_id]["runs_left"] -= 1
            if runs_left - 1 <= 0:
                self.job_dict.pop(job_id, None)
                self.save_jobs()
                return schedule.CancelJob
            self.save_jobs()
            return x

        except:
            traceback.print_exc()

    async def reminder_func(userid, message):
        """
        This is the ACTUAL reminder function called when the
        <time> specified in "!remindme <time> <msg>" has come.

        TL;DR:
        !remindme (...) --> [schedule stuff] --> reminder_func(...)

        params
        ------
            userid:       ID of User who requested the reminder
            message:    message/reminder to send
        """
        try:
            # get user real quick
            self = getattr(TaskScheduler, "_self")
            user = self.bot.get_user(userid)

            await user.send(f"> :bell: Reminder:\n{message}")
        except:
            traceback.print_exc()

    @commands.command("remindme")
    @commands.cooldown(1, 3, commands.BucketType.user)
    @commands.guild_only()
    @GlobalCog.set_clearance(2)
    async def remindme(self, ctx, _time: str, *, msg: str):
        """
        (DM-only!) Set a reminder for user, at <time> with <msg>.

        (OPTIONAL)("i" = important)
        Type "i" as last word, if you want the bot to re-try
        your reminder in case of an error.

        FORMAT: >>remindme <TIME> <MESSAGE> [i]

        EXAMPLE USAGE:
            - >>remindme 3h,26m inhouses starting.
            - >>remindme 3d workout day! i
            - >>remindme 3d workout day!
            - >>remindme 45m give the new members some roles i
            - >>remindme 45m give the new members some roles
            - >>remindme 18h,27m,5s go2sleep
            - >>remindme 18h,27m,5s go2sleep i

        <TIME> format: (order = days,hours,minutes,seconds)
            - 4d,3h,16m,10s
            - 42d,24h,3m
            - 3h,2s
            - 12h
            - (any format as long as order ^^ is retained)
        """
        # TODO: add support for "monday/tuesday/wednesday/etc. argument"
        # TODO: add support for perk/privilege-based reminder capability

        MAX_MSG_LEN = 150

        try:
            sched_date = None
            if _time.lower() in self.DAYS_OF_WEEK:
                sched_date = _time.lower()
            else:
                sched_date = self.timed2datetime(_time)

            # create unique tags for reminder
            taglist = [str(ctx.guild.id), str(ctx.author.id)]
            taglist = [TaskScheduler.hash_task_id(taglist)]

            # make sure user hasn't reached their reminder limit
            reminders_found = self.find_jobs(taglist)
            if len(reminders_found) > self.REMINDER_LIMIT_PER_USER:
                msg = "Sorry! I can only remember `{}` reminders per user..."
                return await ctx.send(msg.format(self.REMINDER_LIMIT_PER_USER))

            # add another 'tag' to indicate this is the "Nth" reminder
            n = str(1 + len(reminders_found))
            taglist.append(n)

            # sched. date and msg. length must be valid
            if not sched_date:
                return await ctx.reply("Bad time/time-format given.")
            if len(msg) > MAX_MSG_LEN:
                return await ctx.reply("Message too long (150 char max).")

            # set importance flag
            i = False
            if len(msg) > 2 and msg[-2:].lower() == " i":
                msg = msg[:-2]
                i = True

            # create job ID, add it to <taglist>
            job_id = str(uuid.uuid4())
            taglist.append(job_id)

            # actually call the scheduler
            job = self.ts.every(sched_date).seconds
            job = job.do(
                TaskScheduler.do_func,
                job_id,
                True,
                TaskScheduler.reminder_func,
                ctx.author.id,
                msg,
            ).tag(*taglist)

            # store/save scheduled job
            success = self.store_job(job, job_id, i=i)

            # return msg in chat saying "scheduled! :sparkles:"
            if bool(success):
                await self.react_success(ctx)
            # else: print( 'success is type({})'.format(type(success)) )

        except:
            traceback.print_exc()

    @commands.command("print_jobs", aliases=["prjobs"], hidden=True)
    @commands.guild_only()
    @GlobalCog.set_clearance(7)
    async def print_jobs(self, ctx, verbose=""):
        """
        Print currently registered jobs for the scheduler. ('prjobs' is a shorthand).

        Add "-v" or "--verbose" arg if you want it shown in discord.

        Usage:
        !print_jobs         (display in console-only)
        !print_jobs -v      (will show in discord)
        !prjobs             (display in console-only)
        """
        acc = self.accessor_mirror

        # (applies to non-owners) ensure command is only executed in a bot operator zone
        if not self.bot.is_owner(ctx.author):
            # <bot_operator_zone> designation must be set
            if not acc.designation_is_set(str(ctx.guild.id), "bot_operator_zone"):
                return await self.react_fail(ctx)

            # check if this channel is a <bot_operator_zone>
            bot_chid = acc.get_designation_channel_id(
                str(ctx.guild.id), "bot_operator_zone"
            )
            if str(ctx.channel.id) not in bot_chid.split(","):
                return await self.react_fail(ctx)

        if self.ts.jobs:
            joblist = [str(j) for j in self.ts.jobs]

            print("\nScheduled Tasks:\n" + "\n".join(joblist))
            if verbose in ("-v", "--verbose"):

                # prepare and send embed
                embed = discord.Embed(
                    title=emojis.encode(":gear: __Scheduled Jobs__"),
                    description="```{}```".format("\n".join(joblist)),
                    colour=0xFFC02E,
                )
                await ctx.reply(embed=embed)

        else:
            await ctx.reply("No jobs found.")

    # CLEAR <YOUR> LAST REMINDER (if it exists)

    # CLEAR ALL <YOUR> REMINDERS (if they exist)
    @commands.command("clear_reminders")
    @commands.cooldown(1, 30, commands.BucketType.user)
    @GlobalCog.set_clearance(2)
    async def clear_all_reminders(self, ctx):
        """
        All reminders the user has scheduled will be removed.
        """
        if not self.ts.jobs:
            return await self.react_success(ctx)

        # get hash to make filtering easier
        userhash = TaskScheduler.hash_task_id([str(ctx.guild.id), str(ctx.author.id)])
        matches = self.find_jobs([userhash], ref=True)
        if len(matches) == 0:
            await self.react_fail(ctx)
            await ctx.message.delete(delay=3.0)

        # remove all jobs, but don't run 'save_jobs' until the end
        remove_job = self.remove_job
        for m in matches:
            remove_job(m, save=False)
        self.save_jobs()
        await self.react_success(ctx)
        await ctx.message.delete(delay=3.0)

    # VIEW ALL YOUR CURRENT REMINDERS
    @commands.command("reminders", aliases=["myreminders"])
    @commands.cooldown(3, 10, commands.BucketType.user)
    @GlobalCog.set_clearance(2)
    async def view_reminders(self, ctx):
        """(DM-only) Display current reminders you have scheduled."""
        # get hash to make filtering easier
        userhash = TaskScheduler.hash_task_id([str(ctx.guild.id), str(ctx.author.id)])
        matches = self.find_jobs([userhash], ref=True)

        if not self.ts.jobs or (len(matches) == 0):
            reply = await ctx.reply("(0) reminders scheduled.")
            await ctx.message.delete(delay=15.0)
            return await reply.delete(delay=15.0)

        # add each job found to the table to display (time, message)
        table = []
        skeleton = '[{}]: "{}"'
        datefmt = "%Y-%m-%d %H:%M:%S"
        append = table.append
        fmt = skeleton.format

        # iterating over all found jobs
        for m in matches:
            append(fmt(m.next_run.strftime(datefmt), m.job_func.args[-1]))

        # prepare and send embed
        embed = discord.Embed(
            title=emojis.encode(":bookmark_tabs: __Your Reminders__"),
            description="\n".join(table),
            colour=0xFFC02E,  # construction yellow
        )
        await ctx.author.send(embed=embed)

    # # DAILY CAT -- sent every day at 5:05 pm
    # async def dailycat(self, search_term='cat'):
    # '''
    # DAILY CAT PICTURE! -- sent every day at 5:00 pm.
    # ---
    # Sends the same picture (random) up to 5 connected servers
    # '''
    # MAX_RCV = 5     # maximum number of servers to receive the picture
    # serverid = 0    # container to hold a server ID
    # channel = None  # container to hold a discord.channel object

    # try:
    # uagent = 'python:owl-cat-imgfetcher:v1.0 (by /u/TheCosmicMeowl)'
    # reddit = praw.Reddit(client_id='m8AFKcvPW05F-A',
    # client_secret='hGejj35OBMu4laGDNVBDFfqQ8lM',
    # user_agent=uagent)
    # subreddit = reddit.subreddit(search_term).new()
    # chosen = random.randint(1, 30)
    # img = None

    # # choose the first image that isn't pinned on the subreddit
    # for i in range(chosen):
    # img = next(x for x in subreddit if not x.stickied)

    # self = getattr( TaskScheduler, '_self')
    # N = min(MAX_RCV, len(self.bot.guilds))
    # for i in range(N):
    # serverid = self.bot.guilds[i].id
    # print('serverid = ', serverid)

    # # UNCOMMENT THIS:
    # # boogaloo server (posting in  #blip-testing  )
    # if serverid == 582309943915315276:
    # channel = self.bot.get_channel(582309943919509555)

    # # humble abode server (posting in  #basic channel  )
    # if serverid == 480876592654975006:
    # channel = self.bot.get_channel(480876592654975010)

    # else: continue

    # # send the <cat/owl> image
    # await channel.send('_{}_\n{}'.format(img.title, img.url))

    # except ApiException as AE: print(AE)
    # except: traceback.print_exc()

    # # DAILY OWL -- sent every day at 5:15 pm
    # async def dailyowl(self):
    # '''
    # DAILY OWL PICTURE! -- sent every day at 5:15 pm.
    # ---
    # Sends the same picture (random) up to 5 connected servers.
    # '''
    # try: await self.dailycat(search_term='owl')
    # except: traceback.print_exc()

    # DAILY RANDOM QUESTION ( randomize from file )

    # WEEKLY LOTTERY/POINTS DRAW (single person) (every Saturday, 4:00 pm)
    # WEEKLY LOTTERY/POINTS DRAW (random role)   (every Saturday, 6:00 pm)


""" ======================= COGLOADING + MAIN ====================== """


def setup(bot):
    bot.add_cog(TaskScheduler(bot))
    print("[taskscheduler] cog loaded!")


if __name__ == "__main__":
    try:
        print("Loading taskscheduler cog!")
    except:
        traceback.print_exc()
