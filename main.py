import asyncio
import datetime
import os
import discord
import json
import sqlite3
import time
from discord.ext import commands


with open('config.json', 'r') as f:
    config = json.load(f)

with open('pings.json', 'r') as f:
    ping_config = json.load(f)

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=config["prefix"], intents=intents)
bot.remove_command("help")
ping_violations = config.get('ping_violations', True)
slot_role_id = config['slot_role_id']
timeout_duration = 86400
conn = sqlite3.connect('slots.db')
c = conn.cursor()
tos_channel = config['tos_channel']
scam_log = 1228028395611357275


c.execute('''CREATE TABLE IF NOT EXISTS users (
             user_id TEXT PRIMARY KEY,
             internal_id INTEGER,
             slot_count INTEGER,
             slot_channel_id TEXT,
             last_ping_date TEXT DEFAULT '0000-00-00',
             ping_count INTEGER DEFAULT 0,
             expiration_date TEXT,
             slot_type TEXT,
             expired BOOLEAN DEFAULT 0)''')

conn.commit()

@bot.event
async def on_ready():
    print("Bot is ready.")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name="slot owners"))
    bot.loop.create_task(check_expired_slots())

@bot.command(aliases=['as', 'addslot'], brief="Adds a slot to the mentioned user")
@commands.has_role(slot_role_id)
async def add(ctx, member: discord.Member, category_type: str, duration: str):
    c.execute("INSERT OR IGNORE INTO users (user_id, slot_count, slot_channel_id, internal_id, last_ping_date, ping_count, expiration_date, slot_type, expired) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (str(member.id), 0, 0, '', '0000-00-00', 0, '', '', 0))
    conn.commit()
    
    if category_type.lower() not in ['p', 's', 's2']:
        await ctx.send("Invalid category type. Please use 'p' for premium, 's' for standard, or 's2' for standard 2.")
        return
    
    if duration.lower() == "lifetime":
        slot_type = "Lifetime"
        timeout_duration = datetime.timedelta(days=4000)
    elif duration.endswith('s'):
        slot_type = "non_lifetime"
        timeout_duration = datetime.timedelta(seconds=int(duration[:-1]))
    elif duration.endswith('d'):
        slot_type = "non_lifetime"
        timeout_duration = datetime.timedelta(days=int(duration[:-1]))
    else:
        await ctx.send("Invalid duration format. Example usage: '10d' for 10 days or 'lifetime' for a lifetime slot.")
        return
    
    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(send_messages=False),
        member: discord.PermissionOverwrite(send_messages=True)
    }

    if category_type.lower() == 'p':
        category_id = config["premium-category"]
    elif category_type.lower() == 's':
        category_id = config["standard-category"]
    elif category_type.lower() == 's2':
        category_id = config["third-category"]

    category = discord.utils.get(ctx.guild.categories, id=category_id)
    if not category:
        await ctx.send("Category not found. Please configure the correct category ID.")
        return

    channel = await ctx.guild.create_text_channel(name=f"・{member.name}", overwrites=overwrites, category=category)
    def process_string(string):
        new_duration = int(string.replace('d', ''))
        return new_duration
    def replace_d(string):
        int_duration = string.replace('d', ' days')
        return int_duration
    expiration_datetime = datetime.datetime.utcnow() + timeout_duration
    expiration_date = expiration_datetime.strftime('%Y-%m-%d %H:%M:%S')
    internal_id = f'internal_id_{c.lastrowid}'
    c.execute("UPDATE users SET slot_count = ?, slot_channel_id = ?, internal_id = ?, expiration_date = ?, slot_type = ?, expired = 0 WHERE user_id = ?", (1, str(channel.id), internal_id, expiration_date, slot_type, str(member.id)))
    conn.commit()


    if duration.lower() == "lifetime":
        current_unix = int(datetime.datetime.utcnow().timestamp()) #seconds since jan 1st 1970 12 am utc till now
        current_unix = f"<t:{current_unix}:f>"
        welcome_embed = discord.Embed(title=f"Welcome to your slot channel, {member.display_name}!", description=f"Read <#{tos_channel}> and feel free to start your activities here.\nPings: `3x @everyone pings` \n \n> Purchase Date: {current_unix} \n> Lifetime Slot \n \n- Username: `{member.name}` \n- Slot Owner ID: `{member.id}` \n- Slot Owner Tag: <@{member.id}> \n- Must follow the slot rules strictly! \n- Always accept middleman", color=discord.Color.blue())
    else:
        duration, int_duration = replace_d(duration), process_string(duration)
        seven_unix, current_unix = convert(int_duration)
        welcome_embed = discord.Embed(title=f"Welcome to your slot channel, {member.display_name}!", description=f"Read <#{tos_channel}> and feel free to start your activities here.\nPings: `3x @here pings` \n \n> Purchase Date: {current_unix} \n> End time: {seven_unix} \n \n- Username: `{member.name}` \n- Slot Owner ID:: `{member.id}` \n- Slot Owner Tag: <@{member.id}> \n- Must follow the slot rules strictly! \n- Always accept middleman", color=discord.Color.blue())
    welcome_embed.set_footer(text="Make sure to check the shiba vouches before dealing.")
    slot_message = await channel.send(embed=welcome_embed)
    await slot_message.pin()
    
    embed = discord.Embed(title="Slot Added", description=f"A {slot_type.lower()} slot has been added for {member.display_name}.", color=discord.Color.green())
    embed.add_field(name="Slot Channel", value=channel.mention)
    await ctx.send(embed=embed)
    if not await is_expired(member.id):
        await schedule_slot_timeout(member.id, expiration_datetime)


async def schedule_slot_timeout(user_id, expiration_datetime):
    current_time = datetime.datetime.utcnow()
    time_difference = expiration_datetime - current_time
    seconds_to_sleep = time_difference.total_seconds()

    await asyncio.sleep(seconds_to_sleep)

    guild = bot.get_guild(config["guild_id"])
    member = guild.get_member(int(user_id))
    if member:
        channel_id = c.execute("SELECT slot_channel_id FROM users WHERE user_id=?", (str(user_id),)).fetchone()[0]
        channel = bot.get_channel(int(channel_id))
        if channel:
            overwrites = channel.overwrites
            overwrites[channel.guild.default_role] = discord.PermissionOverwrite(send_messages=False)
            overwrites[member] = discord.PermissionOverwrite(send_messages=False)
            await channel.edit(overwrites=overwrites)
            embed = discord.Embed(
                title="Slot Expired",
                description=f"Your slot in {channel.mention} has expired. If you want to renew it, please open a ticket.",
                color=discord.Color.red()
            )
            await channel.send(embed=embed)
        else:
            print(f"Unable to find channel for user with ID {user_id}")
    else:
        print(f"Unable to find member for user with ID {user_id}")


async def is_expired(user_id):
    c.execute("SELECT expired FROM users WHERE user_id=?", (str(user_id),))
    result = c.fetchone()
    return result[0] if result or result == 1 else False

async def check_expired_slots():
    await bot.wait_until_ready()
    while not bot.is_closed():
        c.execute("SELECT user_id, expiration_date FROM users WHERE expiration_date != '' AND expiration_date <= datetime('now') AND expired = 0")
        expired_slots = c.fetchall()
        for user_id, expiration_date_str in expired_slots:
            expiration_date = datetime.datetime.strptime(expiration_date_str, '%Y-%m-%d %H:%M:%S')
            if not await is_expired(user_id):
                await schedule_slot_timeout(user_id, expiration_date)
            c.execute("UPDATE users SET expired = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
        await asyncio.sleep(12 * 3600)

@bot.command(aliases=['transfer'], brief="Reassigns a slot to another user or channel using user IDs")
@commands.has_role(slot_role_id)
async def reassign(ctx, person1: discord.User, person2: discord.User):
    # Check if person1 is the owner of any slot
    c.execute("SELECT internal_id, slot_channel_id FROM users WHERE user_id=?", (str(person1.id),))
    result = c.fetchall()
    if not result:
        await ctx.send(f"{person1.display_name} does not own any slots.")
        return

    # Update the owner of the slot to person2
    c.execute("UPDATE users SET user_id = ? WHERE user_id = ?", (str(person2.id), str(person1.id)))
    conn.commit()

    # Update channel permissions
    for slot in result:
        slot_channel_id = int(slot[1])
        slot_channel = bot.get_channel(slot_channel_id)
        if slot_channel:
            overwrites = slot_channel.overwrites
            if person1 in slot_channel.members:
                overwrites[person1] = discord.PermissionOverwrite(send_messages=False)
            overwrites[person2] = discord.PermissionOverwrite(send_messages=True)
            await slot_channel.edit(overwrites=overwrites)

    embed = discord.Embed(title="Slot Reassigned", color=discord.Color.green())
    embed.description = f"All slots owned by {person1.display_name} have been reassigned to {person2.display_name}. Channel permissions updated."

    await ctx.send(embed=embed)        
        
@bot.command(aliases=['rs', 'removeslot'], brief="Removes the slot of the mentioned user")
@commands.has_role(slot_role_id)
async def remove(ctx, member: discord.Member):
    c.execute("SELECT slot_channel_id FROM users WHERE user_id=?", (str(member.id),))
    result = c.fetchone()
    if result:
        channel_id = int(result[0])
        channel = ctx.guild.get_channel(channel_id)
        if channel:
            embed = discord.Embed(title="Slot Removed", description=f"The slot for {member.display_name} has been removed.", color=discord.Color.red())
            await ctx.send(embed=embed)
            await asyncio.sleep(5)
            await channel.delete()
            c.execute("DELETE FROM users WHERE user_id=?", (str(member.id),))
            conn.commit()
        else:
            await ctx.send(f"Slot channel not found for {member.display_name}.")
    else:
        await ctx.send(f"No slot found for {member.display_name}.")
        
@bot.command(aliases=['rv', 'revokeslot'], brief="Revokes the slot permission to write for the mentioned user")
@commands.has_role(slot_role_id)
async def revoke(ctx, member: discord.Member):
    c.execute("SELECT slot_channel_id FROM users WHERE user_id=?", (str(member.id),))
    result = c.fetchone()
    if result:
        channel_id = result[0]
        if channel_id:
            try:
                channel_id = int(channel_id)
            except ValueError:
                await ctx.send(f"Invalid slot channel ID found for {member.display_name}.")
                return
                
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                overwrites = channel.overwrites
                overwrites = {
                    ctx.guild.default_role: discord.PermissionOverwrite(send_messages=False),
                    member: discord.PermissionOverwrite(send_messages=False)
                }
                embed = discord.Embed(title="Slot Permission Revoked", description=f"The slot permission to write for {member.display_name} has been revoked.", color=discord.Color.red())
                await channel.send(embed=embed)
    
                await channel.edit(overwrites=overwrites)
                
                embed = discord.Embed(title="Slot Permission Revoked", description=f"The slot permission to write for {member.display_name} has been revoked.", color=discord.Color.red())
                await ctx.send(embed=embed)
            else:
                await ctx.send(f"Slot channel not found for {member.display_name}.")
        else:
            await ctx.send(f"No slot channel associated with {member.display_name}.")
    else:
        await ctx.send(f"No slot found for {member.display_name}.")        

@bot.command(aliases=['re', 'resumeslot'], brief="Readd the slot permission to write for the mentioned user")
@commands.has_role(slot_role_id)
async def resume(ctx, member: discord.Member, duration: str):
    c.execute("SELECT slot_channel_id, expiration_date FROM users WHERE user_id=?", (str(member.id),))
    result = c.fetchone()
    if result:
        channel_id, expiration_date = result
        if channel_id:
            try:
                channel_id = int(channel_id)
            except ValueError:
                await ctx.send(f"Invalid slot channel ID found for {member.display_name}.")
                return
                
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                overwrites = channel.overwrites
                overwrites = {
                    ctx.guild.default_role: discord.PermissionOverwrite(send_messages=False),
                    member: discord.PermissionOverwrite(send_messages=True)
                }
    
                await channel.edit(overwrites=overwrites)
                
                if duration.endswith('d'):
                    timeout_duration = datetime.timedelta(days=7)
                elif duration.endswith('m'):
                    timeout_duration = datetime.timedelta(days=30)
                else:
                    await ctx.send("Invalid duration format. Please use 'd' for days or 'm' for months.")
                    return
                
                if duration == "d":
                    duration = "7 Days"
                else:
                    duration = "30 Days"

                    
                embed = discord.Embed(title="Slot Resumed", description=f"The slot permission to write for {member.display_name} has been resumed.", color=discord.Color.green())
                await ctx.send(embed=embed)       

                
@bot.command()
async def ltc(ctx, amount):
        await ctx.message.delete()
        embed=discord.Embed(title='`LTC`', description=f'**LMETpwanj5sDmkkeM5c4r5XMgPxz1mqCvo**', color=0x206694)
        embed.add_field(name='`Amount`', value=f'**${amount}**', inline=True)
        embed.set_thumbnail(url='https://cdn.discordapp.com/emojis/1209401154006421524.webp?size=96&quality=lossless')
        await ctx.send(embed=embed, mention_author=False)
        await ctx.message.delete()                    

@bot.command()
async def cashapp(ctx, amount):
        await ctx.message.delete()
        embed=discord.Embed(title='`Cashapp`', description=f'**$Vlxneidot**', color=0x206694)
        embed.add_field(name='`Amount`', value=f'**${amount}**', inline=True)
        embed.set_thumbnail(url='https://cdn.discordapp.com/emojis/1217380956260929546.webp?size=96&quality=lossless')
        await ctx.send(embed=embed, mention_author=False)
        await ctx.message.delete()       

@bot.command()
async def paypal(ctx, amount):
        await ctx.message.delete()
        embed=discord.Embed(title='`Paypal`', description=f'**solarisadev@gmail.com**', color=0x206694)
        embed.add_field(name='`Method`', value=f'**Friends & Family.**', inline=True)
        embed.add_field(name='`Amount`', value=f'**${amount}**', inline=True)
        embed.set_thumbnail(url='https://cdn.discordapp.com/attachments/1010853154600005692/1024494395057254430/paypal_PNG7.png')
        await ctx.send(embed=embed, mention_author=False)
        await ctx.message.delete()          
        
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    user_id = str(message.author.id)
    channel_id = str(message.channel.id)

    c.execute("SELECT slot_channel_id, slot_type FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    if result and channel_id == result[0]:
        slot_type = result[1]
        if ping_violations:
            ping_settings = ping_config.get(slot_type.lower(), {})
            max_pings = ping_settings.get("max_pings", 0)
            max_here = ping_settings.get("max_here", 0)
            max_everyone = ping_settings.get("max_everyone", 0)

            try:
                if message.mention_everyone:
                    ping_type = "everyone"
                    await handle_ping_violation(message, user_id, max_pings, max_here, max_everyone, ping_type, slot_type)
                elif message.mention_here:
                    ping_type = "here"
                    await handle_ping_violation(message, user_id, max_pings, max_here, max_everyone, ping_type, slot_type)
                else:
                    print("Something else than everyone/here")
            except Exception as e:
                pass

    await bot.process_commands(message)


async def handle_ping_violation(message, user_id, max_pings, max_here, max_everyone, ping_type, slot_type):
    print("Handling ping violation")
    c.execute("SELECT last_ping_date, ping_count FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    last_ping_date, ping_count = result if result else ('0000-00-00', 0)
    if slot_type.lower() == "lifetime":
        slot_type = "lifetime"
    elif slot_type.lower() == "non_lifetime":
        slot_type = "non lifetime"
    if last_ping_date == str(message.created_at.date()):
        if ping_type == "everyone" and ping_count >= max_everyone:
            print("Max @everyone pings exceeded")
            embed = discord.Embed(
                title="Ping Violation",
                description=f"{message.author.mention}, You have exceeded the amount of pings you're now muted",
                color=discord.Color.red()
            )
            await message.channel.send(embed=embed)
            timeout_duration = datetime.timedelta(days=1)
            await message.author.timeout(timeout_duration, reason=f"@everyone ping violation in {slot_type.lower()} slot channel")
        elif ping_type == "here" and ping_count >= max_here:
            print("Max @here pings exceeded")
            embed = discord.Embed(
                title="Ping Violation",
                description=f"{message.author.mention}, you have exceeded the maximum number of @here pings allowed per day in your {slot_type.lower()} slot channel. You are timed out for a day.",
                color=discord.Color.red()
            )
            await message.channel.send(embed=embed)
            timeout_duration = datetime.timedelta(days=1)
            await message.author.timeout(timeout_duration, reason=f"@here ping violation in {slot_type.lower()} slot channel")
        elif ping_count >= max_pings:
            print("Max pings exceeded")
            embed = discord.Embed(
                title="Ping Violation",
                description=f"{message.author.mention}, you have exceeded the maximum number of pings allowed per day in your {slot_type.lower()} slot channel. You are timed out for a day.",
                color=discord.Color.red()
            )
            await message.channel.send(embed=embed)
            timeout_duration = datetime.timedelta(days=1)
            await message.author.timeout(timeout_duration, reason=f"Ping violation in {slot_type.lower()} slot channel")
        else:
            ping_count += 1
            left = max_pings - ping_count
            c.execute("UPDATE users SET ping_count = ? WHERE user_id = ?", (ping_count, user_id))
            conn.commit()
            embed = discord.Embed(
                title="Ping Count",
                description=f"{message.author.mention}, You have {left} pings left for today. | Use MM",
                color=discord.Color.blue()
            )
            await message.channel.send(embed=embed)
    else:
        c.execute("UPDATE users SET last_ping_date = ?, ping_count = 1 WHERE user_id = ?", (str(message.created_at.date()), user_id))
        conn.commit()
        embed = discord.Embed(
            title="Ping Count",
            description=f"{message.author.mention}, You have {max_pings - 1} pings left for today. | Use MM",
            color=discord.Color.blue()
        )
        await message.channel.send(embed=embed)
        
def convert(str):
    if int(str):
        current_time = int(time.time())
        current_formatted = f"<t:{current_time}:f>"
        target_time = current_time + (str * 24 * 60 * 60)
        target_formatted = f"<t:{target_time}:f>"
        return target_formatted, current_formatted
    else:
        print("Invalid converting input!")        

@bot.command()
async def mark(ctx, guildid, *, reason):
        blacklist1 = open('blacklist.txt', 'r').read()
        if guildid in blacklist1:
            embed=discord.Embed(title='**Error**', description=f'**{guildid}** is already blacklisted.', color=0x206694)
            embed.set_footer(text='JaY', icon_url='https://cdn.discordapp.com/attachments/1218828642310815818/1234798805585756241/Untitled_design_5.png?ex=664f0c80&is=664dbb00&hm=1ec98e7530dc183e8557b4f253a004a740a17552f58b245cf270bb68bbcce1ab&')
            embed.timestamp = datetime.datetime.now()
            await ctx.send(embed=embed, mention_author=False)
        else:
            with open('blacklist.txt', 'a') as f:
                f.write(f'{guildid}\n')
                embed=discord.Embed(title='**Scam Alert**', description=f'Scammer **{guildid}**.\n\n Reason: {reason}', color=0x206694)
                embed.set_thumbnail(url='https://cdn.discordapp.com/attachments/1218828642310815818/1234798805585756241/Untitled_design_5.png?ex=664f0c80&is=664dbb00&hm=1ec98e7530dc183e8557b4f253a004a740a17552f58b245cf270bb68bbcce1ab&')
                embed.set_footer(text='Sukh Slots', icon_url='https://cdn.discordapp.com/attachments/1218828642310815818/1234798805585756241/Untitled_design_5.png?ex=664f0c80&is=664dbb00&hm=1ec98e7530dc183e8557b4f253a004a740a17552f58b245cf270bb68bbcce1ab&')
                embed.timestamp = datetime.datetime.now()
                await ctx.send(embed=embed, mention_author=False)
                message = str(guildid)
                await ctx.guild.get_channel(scam_log).send(message)
                embed=discord.Embed(title='**Scam Alert**', description=f'Moderator:{ctx.author.mention}, Scammer:**{guildid}**\n\n Reason: {reason}', color=0x206694)
                embed.set_thumbnail(url='https://cdn.discordapp.com/attachments/1218828642310815818/1234798805585756241/Untitled_design_5.png?ex=664f0c80&is=664dbb00&hm=1ec98e7530dc183e8557b4f253a004a740a17552f58b245cf270bb68bbcce1ab&')
                embed.set_footer(text='Sukh Slots', icon_url='https://cdn.discordapp.com/attachments/1218828642310815818/1234798805585756241/Untitled_design_5.png?ex=664f0c80&is=664dbb00&hm=1ec98e7530dc183e8557b4f253a004a740a17552f58b245cf270bb68bbcce1ab&')
                embed.timestamp = datetime.datetime.now()
                await ctx.guild.get_channel(scam_log).send(embed=embed)   

@bot.command(name="ts", brief="Get a transcript of a certain slot")
@commands.has_role(slot_role_id)
async def get_transcript(ctx, channel: discord.TextChannel):
    c.execute("SELECT user_id FROM users WHERE slot_channel_id=?", (str(channel.id),))
    result = c.fetchone()
    if result:
        user_id = int(result[0])
        user = bot.get_user(user_id)
        if user:
            messages = []
            async for message in channel.history(limit=None):
                messages.append(message)
            
            transcript = "\n".join([f"{message.author.display_name}: {message.content}" for message in messages])

            embed = discord.Embed(title=f"Transcript for {channel.name}", description=transcript, color=discord.Color.blue())
            await ctx.send(embed=embed)
        else:
            await ctx.send("Unable to fetch user information.")
    else:
        await ctx.send(f"This channel ({channel.mention}) is not a slot channel.")

@bot.command(name='help', brief='Displays information about available slot commands.')
async def help_command(ctx, *args):
    if not args:
        embed = discord.Embed(title="Slot Command Help (Run ,guide for more help)", description="Made by Sukh", color=discord.Color.blurple())
        commands_info = [
            ("rs, removeslot", "Removes the slot of the mentioned user."),
            ("ts, transcript,", "Get a transcript of a certain slot."),
            ("as, addslot", "Adds a slot to the mentioned user."),
            ("revokeslot, rv", "Revokes a slot of the mentioned user"),
            ("re, resumeslot", "Resumes a slot of the mentioned user"),
            ("c, purge", "Purges the message of the chat / an user"),
        ]
        for command_name, command_description in commands_info:
            embed.add_field(name=command_name, value=command_description, inline=False)
        await ctx.send(embed=embed)                
                
@bot.command()
async def snipe(ctx):
    channel = ctx.channel
    if channel.id in sniped_messages:
        message = sniped_messages[channel.id]
        embed = discord.Embed(
            title="Sniped Message",
            description=message.content,
            color=discord.Color.green()
        )
        embed.set_author(name=f"Message sent by: {message.author.name}")
        await ctx.send(embed=embed)
    else:
        await ctx.send("There are no recently deleted messages to snipe sum dum.")

@bot.command(aliases=['guide'])
async def r(ctx):
    embed = discord.Embed(description="**Slot Bot Guide**", color=0x00ff00)
    embed.add_field(name="Adding a Slot", value="To add a slot it is ,as @user s/p 30d", inline=False)
    embed.add_field(name="Removing a slot", value="to delete a slot you must ,rs @user", inline=False)
    embed.add_field(name="Resuming a slot", value="to resume a slot that you have revoked you must ,re @user d", inline=False)
    embed.add_field(name="Revoking a slot", value="to revoke you must ,rv @user", inline=False)
    embed.add_field(name="Clearing / Purge", value="to purge message you can ,clear Amount", inline=False)
    embed.add_field(name="Nuke", value="to nuke a channel you can ,nuke very simple command", inline=False)
    embed.add_field(name="Snipe", value="to snipe any deleted msgs you can run ,snipe", inline=False)
    await ctx.send(embed=embed)

@bot.command(aliases=['rules'])
async def f(ctx):
	embed = discord.Embed(description="**Slot Rules**", color=0x00FF00)
	embed.add_field(name="Pings", value="3x everyone pings a day (they rest 24h after the first ping)", inline=False)
	embed.add_field(name="Invite Links", value="No server invite links (Unless Vip Slot)", inline=False)
	embed.add_field(name="Slot Sharing", value="Slot sharing is forbidden", inline=False)
	embed.add_field(name="Scamming", value="No scamming users here or outside the server", inline=False)
	embed.add_field(name="Pinging Violations", value="Ping violations are unappealable unless issue with the bot", inline=False)
	await ctx.send(embed=embed)          
        
@bot.command(name='clear', aliases=['c', 'purge'], brief='Clear specified number of messages')
@commands.has_any_role(config["mod_role_id"], config["admin_role_id"])
async def clear(ctx, limit: int, member: discord.Member = None):
    if member:
        def check(message):
            return message.author == member
        deleted = await ctx.channel.purge(limit=limit, check=check)
        await ctx.send(f"Cleared {len(deleted)} message(s).", delete_after=5)
    else:
        deleted = await ctx.channel.purge(limit=limit)
        await ctx.send(f"Cleared {len(deleted)} message(s).", delete_after=5)        
        
@bot.command(name='nuke', aliases=['n','clean'], brief='Deletes non-bot messages in the slot channel')
async def clean_channel(ctx):
    # Check if the user has the specified role or is the owner of the slot channel
    c.execute("SELECT user_id, slot_channel_id FROM users WHERE user_id=?", (str(ctx.author.id),))
    result = c.fetchone()
    if result:
        user_id, slot_channel_id = result
        if str(ctx.channel.id) == slot_channel_id:
            if str(ctx.author.id) == user_id or any(role.id == 1209079684898496574 for role in ctx.author.roles):
                deleted_count = 0
                async for message in ctx.channel.history(limit=None):
                    if not message.author.bot:
                        await message.delete()
                        deleted_count += 1
                await ctx.send(f"{deleted_count} non-slotbot message(s) have been deleted.")
            else:
                await ctx.send("You are not authorized to use this command.")
        else:
            await ctx.send("This command can only be used in a slot channel.")
    else:
        await ctx.send("You don't have a slot channel.")  
            
async def setup_hook() -> None:
    """Initialization of cogs"""
    for filename in os.listdir(path='./cogs'):
        if filename.endswith('.py'):
            await bot.load_extension(name=f'cogs.{filename[:-3]}')

if __name__ == "__main__":
    asyncio.run(main=setup_hook())
    bot.run(config['bot'])