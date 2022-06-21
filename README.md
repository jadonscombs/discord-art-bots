[![CircleCI](https://circleci.com/gh/Jtheowl/discord-EGbot.svg?style=shield&circle-token=de715f375b3a6b4788f9cb094ffbccba0713f925)](https://circleci.com/gh/Jtheowl/discord-EGbot)
## Introduction
Kaede and Yoshimura are two personalized Discord bots that work together in offering a variety of features and enhancements, tailored towards art communities. Kaede is more friendly and mostly has social and user-centric features/responsibilities, while Yoshimura handles more backend, data collection and processing responsibilities.

An integral part of many of these bots' features is the use of a locally maintained SQLite3 **database**. Some features can work without it, **others require it** for you and your (art) community to experience non-limited functionality and features.

&nbsp;
## High-Level Application Architecture
Below you will find a high-level overview of the core components of this application. I will add more detailed diagrams over time, to provide visualizations of processes involving specific integral components within the generally defined components in this diagram below.

![aaa](https://raw.githubusercontent.com/jadonscombs/discord-art-bots/blob/main/DiscordBotsHighLevelArchitecture1.png)

&nbsp;
## Quick Start
Follow the steps below to deploy these two friendly, community-oriented Discord bots.

#### 1. You must create a `bot_token.json` file in the root directory of this project (`discord-EGbot/`) with the following contents:
```
{ 
     "Kaede":     "<discord token for bot 1>",
     "Yoshimura": "<discord token for bot 2>"
}
 ```
The names "Kaede" and "Yoshimura" are required for now. Just replace `<discord token for bot X>` with the bot token for your associated Discord bot 1 and 2.

#### 2. Start up the main scripts: `yoshimura.py` first, then `kaede.py`
Warning: `kaede.py` can _update_ a database, but will not _create_ a database if it does not exist. `yoshimura.py` will automatically create a database as needed if one does not already exist, as long as `yoshimura.py` is active.

#### 3. You're all set!
Technically the bots work, but some custom configuration via the bot commands will be needed to unlock full functionality (e.g. custom "designation zones" that are needed for things like automated user verification or channel-based point system features). See the **"Configuration"** section below.


&nbsp;
## Configuration
By default, you can access _Kaede's_ help information with the `!help` command, and _Yoshimura's_ help information with the `+help` command.
If you would like to change the command prefixes for either bot (default: "!" for Kaede, "+" for Yoshimura), use the following command and replace `NEW_PREFIX` with the prefix you want:
```
@your_kaede_bot prefix NEW_PREFIX
@your_yoshimura_bot prefix NEW_PREFIX
```

(replace "`your_kaede_bot`"/"`your_yoshimura_bot`" with the mention(s) for the bots you assigned to Kaede and Yoshimura)


#### Designation Zones
Another key component that these bots rely on is the use of _designation zones._ Designation zones are specific pre-defined "labels" or categories that you assign to channels in your discord server. For example, if you want to designate a `#text-4-stream` channel to receive "Discord stream notifications" you would execute the following command (`dzone set`) using Yoshimura's prefix (`y!`):
```
y!dzone set stream_text #text-4-stream
```

Once you do this, the bots will send a message in `#text-4-stream` when someone starts streaming in one of the voice channels you have.

To see _all_ designation zones that you can assign--including the essential and mandatory ones--use the following command:
```
y!dzone list
```

**RECOMMENDED: Use the `y!help` or `k!help` to explore bot features and configurations. More help information here coming soon!**
