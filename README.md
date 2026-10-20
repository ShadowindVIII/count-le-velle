This bot relies on MongoDB Atlas for its database, and can be run in a docker container. This README assumes you know how to use Docker and either already have a Discord bot created in the Developer Portal, or that you know how to make one and configure it as needed. You will need to enable the Message Content and Server Members privileged intents in Discord's Developer Portal. 

Setup information can be found at the bottom of this README, starting at the Database section. 

MongoDB is chosen for the database because it already stores data in an encrypted format, both at rest as well as in transit, because it is required by Discord's Developer TOS. Docker is chosen as it creates a virtual environment so your `.env` file is not easily accessible by other softwares that might be running on your host machine, and so that any dependencies (most notably, the lack thereof) gets handled by Docker.

Please note that this software is presented to the public **as-is, with no guarantees or assurances if separate functionality or different functionality is desired**. I will try my best to explain the systems herein to allow the bot to work as-is, but I am still a human and this was built in a little over 2 weeks, with the bulk of that time being in the last 5 days, around the time that the Gaius bots and their owner got hacked.

# Experience System

- Every time someone sends a message, a timestamp is stored along with who sent the message 
- If a previous timestamp exists, it compares the time between their most recent message and the one stored
- If the difference is greater than 10 seconds (configurable), it awards 3 experience points (configurable) for a rate of 18exp/min, which serves to prevent people from spamming to grind experience quickly
- It also requires the message to be >1 character long, unless there is an image attached
- Posting stickers or sending messages that start with the bot's prefix will not give experience
- Specific roles can be configured to make someone immune to EXP. This is useful for `/optout` or for punishing users who attempt to abuse the experience system
- For voice chats, if more than 2 people (configurable) are in a voice chat, timestamps of when they join get stored temporarily along with their user ID
- When someone leaves, deafen or switch VC, the time spent in minutes gets awarded at a rate of 6 exp/min (configurable). (People talk ~3x faster than they type so text is about 3x higher by default to accommodate)
- VC experience is separate from text exp, and VC exp caps out at 2h (configurable) per 23h period (also configurable), to limit the efficacy of sitting AFK in a VC with an alt overnight
- If someone is in a VC but muted, their **voice experience will still count but messages they send in a VC's text channel will not be counted**. Please keep this in mind and decide with your staff team whether you need to edit this
- `/ping` command for checking latency/uptime
- `/help` command and `/help staff` to see staff commands
- `/level [user_id]` - leave blank to view your own level/exp
- `/leaderboard n` to see the top `n` spots on the overall leaderboard, or `/leaderboard a-b` to view a specific range, capped at 30 per command use. You can also specify Weekly/Monthly to see where you stand compared to other people that are currently active 
- `/optout` command for those who want to delete all traces of their experience data. Assigns a "No Exp" role if it exists, to prevent future exp gain
- `/wear [role name]` command to switch which color/icon they use - only one role is added at a time.
- At configurable thresholds, roles can be granted to users as rewards for spending time in the server. If a config value starts with `reward_` it is automatically treated as a reward, and requires 3 parameters:
- - `threshold` (int) - the level that a role should be awarded at
- - `role_id` (int) - the ID of the role which should be awarded. Please note that all roles have to be underneath the bot's highest role
- - `message` (str) - a custom phrase enclosed in quotation marks that will be sent when a user unlocks a new role. Include `\n` if you wish to include line breaks. More info in the Editing Configs section.

### Staff-exclusive commands

This section assumes a prefix command of `!`, change it accordingly. The following commands & examples are for staff use only, for adjusting and maintaining people's experience data as needed:
- `!set [user_id] [value] <type>` - Set new value for someone's experience, including negatives if you really want. By default the command will edit `text` type of exp if you do not specify.
- `!award [user_id] [value] <type>` - Adds `value` amount of experience to a person's existing exp. Edits `text` type of experience by default.
- `!delete [user_id]` - Deletes all data associated with a user, as if they used `/optout` except without assigning them a "No Exp" role.
- `!transfer [filename]` - Command for doing a one-time bulk write using a JSON from Gaius Play. This is specifically using the file requested from the owner of the bot, and left in in case anybody else is migrating from Gaius. The JSON should be in the root directory where `main.py` sits.

### Editing Configs
No role rewards exist in the config by default. By default, the following values will be used for operation:
- `text_award` - `value=3`. Amount of experience awarded each time someone speaks after `time_increment` seconds passed since their last message
- `time_increment` - `value=10`. This is the minimum amount of seconds required between messages for experience to count, in order to prevent spam
- `voice_award` - `value=6`. Per-minute rate that users receive for being in a voice channel
- `vc_concurrent_members` - `value=2`. Minimum amount of non-deafened people required to be in a VC for anybody to start getting voice exp
- `immune_roles` - `list=[]`. Populate this list with role IDs that you want the bot to ignore messages from, separated by commas
- `vc_daily_cap` - `hours=2`. Number of hours that voice channel users should be able to gain experience, per `vc_window` period
- `vc_window` - `hours=23`. It's 23 instead of 24 in case people join a channel frequently and arrive slightly earlier than usual
- `debug` - `enabled=False` and `category_id=0`. Specify `enabled=True` and `category_id` to the ID of a category with private channel(s) if you wish to edit the code & test it

For this next section, it will assume you have a prefix set to `!`, since all staff-exclusive commands are prefix commands.
- To view a list of all existing configs, use `!config view`
- To view a specific config, use e.g. `!config view text_award`
- To refresh the database after updating a config, use `!config refresh`
- To delete a config (please note that this will cause configs to revert to their hard-coded backup values and may cause things to break) use `!config rm config_name`

To add/edit a config, use `key=value` notation surrounded with triple backticks, with each new key/value on a newline. Replace `key` with whatever name is specified, and do not deviate. The bot will explicitly look for e.g. `list=[1, 2, 3, 4, 5]` notation if you are editing `immune_roles`. Here is an example with `debug`:

~~~
!config edit debug ```enabled=True
category_id=1234567890```
~~~

Here is an example for creating role rewards (please note that all role reward-related configs must start their name with `reward_`):

~~~
!config add reward_A ```threshold=5
role_id=1234567890
message="Congratulations! You've leveled up enough to receive a reward. You now have the permissions to:\n- Attach Files\n- Embed Links"```
~~~

Because newlines will tell the bot that you're creating a new `key=value` pair, in order to insert newlines into the custom message you need to use `\n`. Quotation marks will be stripped.

# Database
Head over to MongoDB's website and look for Atlas. Once you make an account and create an organization, make a New Project, name it, and invite anybody you want to entrust with database access by email. 

Create a cluster. The Free tier is all you need. I would recommend choosing a provider/region close to the location where you will be hosting the bot. Then hit Create Deployment. 

Once created, copy your username and password that you will need to log into the database. For python/pymongo, your login URI will look something like `mongodb+srv://db_user:db_password@clustername.abcdefg.mongodb.net/`. If your password has special characters, ensure they are [URL-encoded](https://dochub.mongodb.org/core/atlas-url-encoding). This string is what you will need to put in your `.env` file for `MONGO_TOKEN`. **Do not share it unless you trust the recipient.**

Upon creating your cluster, Mongo will automatically restrict IP access to your database to the IP address you connected to the site with. If your intended host machine has a different IP address, you can grant it access by hovering over the sidebar on the left and visiting Security -> Database and Network Access and then adding the host machine's public IP address. If you do not know its IP address, you can find it in a terminal with commands like `curl ifconfig.me`

You can manually edit your database entries in the dashboard under Database > Data Explorer. This bot will store all entries in `ClusterName` > `database`. 
- `vc` collection holds temporary VC data of when someone has last joined/un-deafened.
- `users` collection holds all long-term experience data, including timestamps of when users last sent a message and when they last joined a VC.
- `recent` collection stores daily totals of the amount of experience each user has earned. These database entries auto-expire after 30 days have passed.

# Running the bot

The image for this bot is not posted on Docker Hub, you will have to build it after making all your changes to the code as you see fit. After you install Docker CE, you can run these in a terminal:

```
git clone git@github.com:ShadowindVIII/count-le-velle.git
cd /path/to/your/count-le-velle
docker build . -t levelbot
```

To check on the status of the bot, use `docker ps` and to check for errors during compile use `docker logs levelbot` while it is running (or desperately trying to).

It will be slow the first time you do it, and slow if you change/add any dependencies in `requirements.txt`. Unless you change the name of the tag from `levelbot`, you will not need to edit `docker-compose.yml`. What you will need to edit next is the `.env` file:
- Paste your Discord bot's token copied from the Developer portal
- The bot generates logs when it encounters runtime errors or when it starts/restarts. Choose a channel where you want these logs to collect and copy its channel ID into `LOG_CHANNEL`
- This bot is designed for running/existing in one server. Put the server's ID in `OPERATING_GUILD`
- In its current form, the `STAFF_ROLE_ID` and `ADMIN_ROLE_ID` that you specify will both carry identical permissions. You can change this in the code if you want to. If you only need one role to hold elevated permissions, you can put the same ID in both fields or leave one as a dummy.
- All publicly available commands are slash commands, while staff-only commands are prefix commands. Choose your prefix command and set it in `PREFIX`. Be aware that `=` as a prefix may cause problems due to the formatting that `.env` files use.
- All Discord bots with >10,000 users able to access it are required to apply for the privileged intents and keep a Privacy Policy publicly available. If you need it, specify it in `PRIVACY_POLICY_URL` so it will appear in `/help` commands.
- Choose how long you want your commands to be on cooldown via `COMMAND_COOLDOWN`
- Put your Mongo login URI in `MONGO_TOKEN`

Start up the bot with `docker compose up -d` with your working directory in the bot's root folder, where `main.py` sits.
