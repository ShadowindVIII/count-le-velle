# About this bot

This bot was purpose-built to migrate from Gaius Play, after its owner had been hacked and the bots experienced a downtime of several days. This repository is kept open-sourced and maintained in case anybody wishes to follow suit or otherwise wants to run their own Discord bot for tracking experience/levels. 

This bot relies on MongoDB Atlas for its database, and can be run in a docker container. This README assumes you know how to use Docker and either already have a Discord bot created in the Developer Portal, or that you know how to make one and configure it as needed. You will need to enable the Message Content and Server Members privileged intents in Discord's Developer Portal. 

Setup information can be found at the bottom of this README, starting at the Database section. 

MongoDB is chosen for the database because it already stores data in an encrypted format, both at-rest as well as in-transit, because it is required by Discord's Developer TOS. Docker is chosen as it creates a virtual environment so your `.env` file is not easily accessible by other softwares that might be running on your host machine, and so that any dependencies (most notably, the lack thereof) get handled by Docker.

Please note that this software is presented to the public **as-is, with no guarantees or assurances if separate functionality or different functionality is desired**. I will try my best to explain the systems herein to allow the bot to work as-is, but I am still a human.

# Experience System

- Every time someone sends a message, a timestamp is stored along with who sent the message 
- If a previous timestamp exists, it compares the time between their most recent message and the one stored
- If the difference is greater than 10 seconds (configurable), it awards 3 experience points (configurable) for a rate of 18exp/min, which serves to prevent people from spamming to grind experience quickly
- It also requires the message to be >1 character long, unless there is an image attached
- Posting stickers or sending messages that start with the bot's prefix will not give experience
- Specific roles can be configured to make someone immune to EXP. This is useful for `/optout` or for punishing users who attempt to abuse the experience system
- For voice chats, if more than 2 people (configurable) are in a voice chat, timestamps of when they join get stored temporarily along with their user ID
- When someone leaves, deafens, switches VC or gets muted by a moderator (red microphone icon), the time spent in minutes gets awarded at a rate of 6 exp/min (configurable). (People talk ~3x faster than they type so text is about 3x higher by default to accommodate)
- VC experience is separate from text exp, and VC exp caps out at 2h (configurable) per 23h period (also configurable), to limit the efficacy of sitting AFK in a VC with an alt overnight
- If someone is in a VC but self-muted, their **voice experience will still count but messages they send in a VC's text channel will not be counted**. Please keep this in mind and decide with your staff team whether you need to edit this
- `/ping` command for checking latency/uptime
- `/help` command and `/help staff` to see staff commands
- `/level [user_id]` - leave blank to view your own level/exp
- `/leaderboard [range] [timespan] [sort_type]` 
- - Results contain a "Show to everyone" button which users can press to post the results in chat, rather than keeping the results in an ephemeral message
- - `range`
- - `timespan` allows the user to show Overall leaderboards, or only results from the past 7 ("Weekly") or 30 ("Monthly") days
- - `sort_type` allows the user to specify whether leaderboards should sort by text only, voice only, both, or view "Around Me" to see where they stand in the leaderboards
- `/optout` command for those who want to delete all traces of their experience data. Assigns a "No Exp" role if it exists, to prevent future exp gain
- `/wear [role name]` command to switch which color/icon they use - only one role is added at a time
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
- `!apikey [create/remove/view/list] <label>` - Create keys with which to access the bot's API. More info in API section
- - **If you need to transfer a JSON, make sure to un-comment the `COPY` directive sitting in the Dockerfile when you build/run the bot so that the bot has access to it.**

### Editing Configs
No role rewards exist in the config by default. By default, the following values will be used for operation:
- `text_award` - `value=3`. Amount of experience awarded each time someone speaks after `time_increment` seconds passed since their last message
- `time_increment` - `value=10`. This is the minimum amount of seconds required between messages for experience to count, in order to prevent spam
- `voice_award` - `value=6`. Per-minute rate that users receive for being in a voice channel
- `vc_concurrent_members` - `value=2`. Minimum amount of non-deafened people required to be in a VC for anybody to start getting voice exp
- `immune_roles` - `list=[]`. Populate this list with role IDs that you want the bot to ignore messages from, separated by commas
- `vc_daily_cap` - `hours=2`. Number of hours that voice channel users should be able to gain experience, per `vc_window` period
- `vc_window` - `hours=23`. It's 23 instead of 24 in case people join a channel frequently and arrive slightly earlier than usual
- `debug` - `enabled=True` and `category_id=0`. Specify `enabled=True` and `category_id` to the ID of a category with private channel(s) if you wish to edit the code & test it in just a single category, otherwise it will watch all categories that the bot can view

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
role_name=Role Name Here
message="Congratulations! You've leveled up enough to receive a reward. You now have the permissions to:\n- Attach Files\n- Embed Links"
persistent=True```
~~~

All 5 parameters are required to define a reward. Because actual newlines will tell the bot that you're creating a new `key=value` pair, in order to insert newlines into the custom message you need to use `\n`. Quotation marks will be stripped.

The `persistent` option will specify whether you want the role to always remain enabled once a person reaches `threshold`, or whether you want users to be able to remove it with `/wear`.

## API
This bot has an API cog which will allow (as of writing this) users to interact with the bot via other automated systems beyond itself, if needed. You can send HTTP methods to `http://127.0.0.1:8080/API_ENDPOINT_YOU_CHOOSE` followed by the endpoints described herein. This was developed & implemented so that my team could integrate the [Rain World Server Challenge](https://leapzard.app/rwsc) sheet, since our server's vanity role system has a portion which involves doing in-game challenges and submitting proof to the server, resulting in time being spent on a server-related activity without the usual amount of chatting. As of right now, the `bonus` category of experience is only used when awarded by a staff or awarded through this API. You can handle "bonus" experience however you see fit.

If you do not change the `API_ENDPOINT` specified in the `.env` file and leave it as-is, this cog will not activate. The docker-compose only exposes `127.0.0.1:8080` because I am using a reverse proxy (nginx) which sits in front of the API. It `proxy_pass`es a pretty URL (https://leapzard.app/reginald/api) to the bot so that nginx can handle the rate limits, HTTPS certificates, etc. You can change the docker-compose to expose `8080:8080` if you want it accessible without HTTPS for some reason.

All API endpoints require an `Authorization: Bearer API_KEY_HERE` header. You can generate API keys as an admin with the command `!apikey create key_name_here`. The key will be sent to your DMs, so make sure you have them open. __The key will not be shown to you again and the DM will delete itself after 30 seconds__. The key is not stored in the database, only its hash.

### `/award`
Sending a `POST` method to this endpoint will look for a JSON object in the form `{"id": "1111111111111111111", "type": "type_of_exp_here", "amount": 1234}` and award it to the user. 
It returns a status of 200 and a string-ified JSON object with the affected user's latest data if successful.
It returns a status of 401 if no API key is given or an invalid/nonexistent key is given.
It returns a status of 400 if the formatting of the JSON object is not given as described above, or if parts of it are missing. An `amount` of 0 will do nothing and simply return the affected user's current experience stats. (Negative amounts are supported and will subtract exp.)

### `/user/{user_id_here}` 
Sending a `GET` method to this endpoint will return the user's current stats as a JSON object with status 200, if the user has data. If no data is associated with the id given, it returns status 404.

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
- If you do not intend to use/expose the bot's API endpoints, leave `API_ENDPOINT` as-is. If it remains as-is, a check will prevent the API from going online at all.

Start up the bot with `docker compose up -d` with your working directory in the bot's root folder, where `main.py` sits.
