import discord
from discord.ext import commands, tasks
import requests
import asyncio
import json
import pyipmi
import pyipmi.interfaces
import argparse


# Create an instance of discord.Intents
intents = discord.Intents.all()  # This allows all privileged intents

# Initialize the bot with the intents parameter
bot = commands.Bot(command_prefix='!', intents=intents)


# Create an ArgumentParser instance
parser = argparse.ArgumentParser(description='Discord bot for Proxmox VM power operations.')

# Add the --config-file argument
parser.add_argument('--config-file', dest='config_file', default='config.json',
                    help='Path to the configuration file')

# Parse the command-line arguments
args = parser.parse_args()

# Load configuration from config file
config_file_path = args.config_file
with open(config_file_path, 'r') as config_file:
    config = json.load(config_file)
    discord_config = config.get("discord", {})
    ipmi_config = config.get("ipmi", {})
    proxmox_config = config.get("proxmox", {})


# Discord Configurations
DISCORD_TOKEN = discord_config.get("token", "")
DISCORD_POWER_OPTIONS = discord_config.get("offer_power_options", True)
DISCORD_DELETE_MESSAGES = discord_config.get("delete_messages", True)
DISCORD_CLEAR_CHANNEL = discord_config.get("clear_channel", False)
DISCORD_CHANNEL_ID = int(discord_config.get("channel_id", ""))
discord_to_vm_mapping = discord_config.get("discord_to_vm_mapping", {})

# Proxmox Configurations
PROXMOX_BASE_URL = proxmox_config.get("base_url", "")
PROXMOX_TOKEN = proxmox_config.get("token", "")
PROXMOX_USERNAME = proxmox_config.get("username", "")
PROXMOX_REALM = proxmox_config.get("realm", "")
PROXMOX_TOKEN_NAME = proxmox_config.get("token_name", "")
PROXMOX_NODE_NAME = proxmox_config.get("node_name", "")
PROXMOX_STARTUP_TIME = proxmox_config.get("startup_time", 180)  # Default startup time is 3 minutes

# IPMI Configurations
IPMI_HOST = ipmi_config.get("host", "")
IPMI_USERNAME = ipmi_config.get("username", "")
IPMI_PASSWORD = ipmi_config.get("password", "")
IPMI_PORT = ipmi_config.get("port", 623)

# Constants for IPMI power control
IPMI_POWER_ON = 1  # IPMI Chassis Control Command: Power On
IPMI_POWER_OFF_SOFT = 5  # IPMI Chassis Control Command: Power Off (Soft)

interface = pyipmi.interfaces.create_interface('ipmitool', interface_type='lanplus')
ipmi = pyipmi.create_connection(interface)
ipmi.session.set_session_type_rmcp(IPMI_HOST, IPMI_PORT)
ipmi.session.set_auth_type_user(IPMI_USERNAME, IPMI_PASSWORD)
ipmi.session.establish()

async def id_not_found(ctx):
    idnotfoundmsg = await ctx.send(f"{ctx.author.mention}, no VM mapping found for your Discord ID.")
    if DISCORD_DELETE_MESSAGES:
        await asyncio.sleep(30)
        await idnotfoundmsg.delete()

async def check_proxmox_status(ctx, direct_command=False):
    discord_user_id = str(ctx.author.id)
    vm_id = discord_to_vm_mapping.get(discord_user_id)

    if vm_id:
        proxmox_url = f"{PROXMOX_BASE_URL}/nodes/{PROXMOX_NODE_NAME}/status"
        headers = {"Authorization": f"PVEAPIToken={PROXMOX_USERNAME}@{PROXMOX_REALM}!{PROXMOX_TOKEN_NAME}={PROXMOX_TOKEN}"}
        
        try:
            #todo: find a way to suppress ssl warning
            response = requests.get(proxmox_url, headers=headers, verify=False, timeout=5)
        except requests.exceptions.ConnectTimeout:
            error_message = f"{ctx.author.mention}, failed to connect to Proxmox: Connection timed out."
            print (f"{error_message}")
            error_msg = await ctx.send(error_message)
            async def delete_error_message(error_msg):
                if DISCORD_DELETE_MESSAGES:
                    await asyncio.sleep(30)
                    await error_msg.delete()
            asyncio.create_task(delete_error_message(error_msg))
            return None
        if response.status_code == 200:
            if direct_command:
                return response  # Return the full response for direct commands

            if "idle" in response.json().get("data", {}) and response.json()["data"]["idle"] == 0:
                await ctx.send("Proxmox server is ready. You can request VM power operations now.")
            else:
                await ctx.send("Proxmox server is not ready yet. Please wait.")
                await asyncio.sleep(60)  # Wait for 1 minute before checking Proxmox status again
                return None  # Return None to indicate that the server is not ready yet
        else:
            error_message = f"Failed to get Proxmox status. Error: {response.status_code}, Response: {response.text}"
            await ctx.send(error_message)
            return None  # Return None in case of an error
    else:
        await id_not_found(ctx)
        return None  # Return None if there is no VM mapping

async def check_vm_status(ctx):
    discord_user_id = str(ctx.author.id)
    vm_id = discord_to_vm_mapping.get(discord_user_id)

    if vm_id:
        proxmox_url = f"{PROXMOX_BASE_URL}/nodes/{PROXMOX_NODE_NAME}/qemu/{vm_id}/status/current"
        headers = {"Authorization": f"PVEAPIToken={PROXMOX_USERNAME}@{PROXMOX_REALM}!{PROXMOX_TOKEN_NAME}={PROXMOX_TOKEN}"}
        response = requests.get(proxmox_url, headers=headers, verify=False)

        if response.status_code == 200:
            vm_status = response.json().get('data', {}).get('status', '')
            return vm_status
        else:
            #todo: tag user in message and delete message after 30 seconds
            error_message = f"Failed to get VM status. Error: {response.status_code}, Response: {response.text}"
            await ctx.send(error_message)
            print(error_message)
    else:
        await id_not_found(ctx)

async def check_vm_status_by_id(vm_id):
    if vm_id:
        proxmox_url = f"{PROXMOX_BASE_URL}/nodes/{PROXMOX_NODE_NAME}/qemu/{vm_id}/status/current"
        headers = {"Authorization": f"PVEAPIToken={PROXMOX_USERNAME}@{PROXMOX_REALM}!{PROXMOX_TOKEN_NAME}={PROXMOX_TOKEN}"}
        response = requests.get(proxmox_url, headers=headers, verify=False)

        if response.status_code == 200:
            vm_status = response.json().get('data', {}).get('status', '')
            return vm_status
        else:
            #todo: Dump to logs
            print(f"Failed to get VM status. Error: {response.status_code}, Response: {response.text}")
            return None
    else:
        #todo: Dump to logs
        print("No VM ID provided.")
        return None

async def turn_on_vm(ctx):
    # Turn on Proxmox VM based on the user's Discord ID
    discord_user_id = str(ctx.author.id)
    vm_id = discord_to_vm_mapping.get(discord_user_id)

    if vm_id:
        proxmox_url = f"{PROXMOX_BASE_URL}/nodes/{PROXMOX_NODE_NAME}/qemu/{vm_id}/status/start"
        headers = {"Authorization": f"PVEAPIToken={PROXMOX_USERNAME}@{PROXMOX_REALM}!{PROXMOX_TOKEN_NAME}={PROXMOX_TOKEN}"}
        response = requests.post(proxmox_url, headers=headers, verify=False)

        if response.status_code == 200:
            startmessage = await ctx.send(f"{ctx.author.mention}, VM started successfully.")
            if DISCORD_DELETE_MESSAGES:
                await asyncio.sleep(30)
                await startmessage.delete()
        else:
            startfailmsg = await ctx.send(f"{ctx.author.mention}, failed to start VM. Error: {response.text}")
            if DISCORD_DELETE_MESSAGES:
                await asyncio.sleep(30)
                await startfailmsg.delete()
    else:
        await id_not_found(ctx)

async def shut_down_vm(ctx):
    # Shut down Proxmox VM based on the user's Discord ID
    discord_user_id = str(ctx.author.id)
    vm_id = discord_to_vm_mapping.get(discord_user_id)

    if vm_id:
        proxmox_url = f"{PROXMOX_BASE_URL}/nodes/{PROXMOX_NODE_NAME}/qemu/{vm_id}/status/shutdown"
        headers = {"Authorization": f"PVEAPIToken={PROXMOX_USERNAME}@{PROXMOX_REALM}!{PROXMOX_TOKEN_NAME}={PROXMOX_TOKEN}"}
        response = requests.post(proxmox_url, headers=headers, verify=False)

        if response.status_code == 200:
            shutdownmessge = await ctx.send(f"{ctx.author.mention}, VM is shutting down gracefully. Please wait.")
            if DISCORD_DELETE_MESSAGES:
                await asyncio.sleep(30)
                await shutdownmessge.delete()
        else:
            shutdownfailmsg = await ctx.send(f"{ctx.author.mention}, failed to shut down VM. Error: {response.text}")
            if DISCORD_DELETE_MESSAGES:
                await asyncio.sleep(30)
                await shutdownfailmsg.delete()
    else:
        await id_not_found(ctx)

async def power_on_host(ctx):
    try:
        ipmi.chassis_control(IPMI_POWER_ON)        
        poweronmsg = await ctx.send(f"{ctx.author.mention}, server is powering on. Please wait.")
        if DISCORD_DELETE_MESSAGES:
            await asyncio.sleep(PROXMOX_STARTUP_TIME)
            await poweronmsg.delete()
    except Exception as e:
        poweronfailmsg = await ctx.send(f"{ctx.author.mention}, failed to power on server. Error: {str(e)}")
        if DISCORD_DELETE_MESSAGES:
            await asyncio.sleep(60)
            await poweronfailmsg.delete()

async def power_off_host(ctx):
    # Check Proxmox server status
    server_status_response = await check_proxmox_status(ctx, direct_command=True)

    if server_status_response is not None and server_status_response.status_code == 200:
        # Proxmox server is online, proceed to check VM status
        running_vms = []

        for discord_user_id, vm_id in discord_to_vm_mapping.items():
            vm_status = await check_vm_status_by_id(vm_id)

            if vm_status == 'running':
                running_vms.append(discord_user_id)

        if not running_vms:
            # All VMs are already powered off, proceed with power off the host
            try:
                ipmi.chassis_control(IPMI_POWER_OFF_SOFT)
                poweroffmsg = await ctx.send(f"{ctx.author.mention}, server is powering off gracefully. Please wait.")
                if DISCORD_DELETE_MESSAGES:
                    await asyncio.sleep(180)
                    await poweroffmsg.delete()
            except Exception as e:
                powerofferrormsg = await ctx.send(f"{ctx.author.mention}, failed to power off server. Error: {str(e)}")
                if DISCORD_DELETE_MESSAGES:
                    await asyncio.sleep(60)
                    await powerofferrormsg.delete()
        else:
            # Highlight users with running VMs
            users_with_running_vms = ", ".join(f"<@{user_id}>" for user_id in running_vms)
            runningvmsmsg = await ctx.send(f"{ctx.author.mention}, the following VMs are still running: {users_with_running_vms}. You can't power off until all VMs are off.")
            if DISCORD_DELETE_MESSAGES:
                await asyncio.sleep(60)
                await runningvmsmsg.delete()
    elif server_status_response is None:
        # Proxmox server is not ready, inform the user
        poweroffresponseerrormsg = await ctx.send(f"{ctx.author.mention}, Proxmox server is not responding. It may be already offline.")
        if DISCORD_DELETE_MESSAGES:
            await asyncio.sleep(60)
            await poweroffresponseerrormsg.delete()
    else:
        # Handle other cases where Proxmox server status is not 200
        powerofferrorothermsg = await ctx.send(f"{ctx.author.mention}, failed to retrieve Proxmox server status.")
        if DISCORD_DELETE_MESSAGES:
            await asyncio.sleep(60)
            await powerofferrorothermsg.delete()

async def offer_vm_power_options(ctx):
    # Check the current status of the VM
    vm_status = await check_vm_status(ctx)

    if vm_status == 'running':
        message = await ctx.send(f"{ctx.author.mention}, Proxmox server is online. React with ⏹️ to shut down your VM.")
        await message.add_reaction("⏹️")  # Add the stop button emoji as a reaction
        expected_reaction = "⏹️"
        opposite_action = shut_down_vm
    else:
        message = await ctx.send(f"{ctx.author.mention}, Proxmox server is online. React with ▶️ to start your VM.")
        await message.add_reaction("▶️")  # Add the play button emoji as a reaction
        expected_reaction = "▶️"
        opposite_action = turn_on_vm

    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) == expected_reaction

    try:
        reaction, _ = await bot.wait_for("reaction_add", timeout=60.0, check=check)
    except asyncio.TimeoutError:
        if DISCORD_DELETE_MESSAGES:
            await message.delete()
        timeoutmessage = await ctx.send(f"{ctx.author.mention}, reaction timed out. No VM action will be taken.")
        if DISCORD_DELETE_MESSAGES:
            await asyncio.sleep(30)
            await timeoutmessage.delete()
        return
    else:
        if str(reaction.emoji) == expected_reaction:
            if DISCORD_DELETE_MESSAGES:
                await message.delete()
            await opposite_action(ctx)
        else:
            if DISCORD_DELETE_MESSAGES:
                await message.delete()
            invreactionmsg = await ctx.send(f"{ctx.author.mention}, invalid reaction. No VM action will be taken.")
            if DISCORD_DELETE_MESSAGES:
                await asyncio.sleep(30)
                await invreactionmsg.delete()
            return

async def offer_host_power_options(ctx):
    if not DISCORD_POWER_OPTIONS:
        poweroptionsmsg = await ctx.send(f"{ctx.author.mention}, Host power options are disabled. Please reach out to the server admin if you need to change the power state of the host.")
        if DISCORD_DELETE_MESSAGES:
            await asyncio.sleep(60)
            await poweroptionsmsg.delete()
        return

    message = await ctx.send(f"{ctx.author.mention}, Do you want to start the host? (React with ⚡ to start or ❌ to cancel)")
    # Add reactions to the message
    await message.add_reaction("⚡")
    await message.add_reaction("❌")

    def check_reaction(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ["⚡", "❌"] and reaction.message.id == message.id

    try:
        reaction, _ = await bot.wait_for("reaction_add", timeout=30.0, check=check_reaction)
    except asyncio.TimeoutError:
        if DISCORD_DELETE_MESSAGES:
            await message.delete()
        powerreactiontimeoutmsg = await ctx.send(f"{ctx.author.mention}, Reaction timed out. No action will be taken.")
        if DISCORD_DELETE_MESSAGES:
            await asyncio.sleep(30)
            await powerreactiontimeoutmsg.delete()
        return
    else:
        if str(reaction.emoji) == "⚡":
            if DISCORD_DELETE_MESSAGES:
                await message.delete()
            await power_on_host(ctx)
        elif str(reaction.emoji) == "❌":
            if DISCORD_DELETE_MESSAGES:
                await message.delete()
            powerreactionmsg = await ctx.send(f"{ctx.author.mention}, No action will be taken.")
            async def delete_powerreactionmsg(powerreactionmsg):
                if DISCORD_DELETE_MESSAGES:
                    await asyncio.sleep(30)
                    await powerreactionmsg.delete()
            asyncio.create_task(delete_powerreactionmsg(powerreactionmsg))
            return "reaction_cancelled"           
        else:
            if DISCORD_DELETE_MESSAGES:
                await message.delete()
            powerreactionothermsg = await ctx.send(f"{ctx.author.mention}, Invalid reaction. No action will be taken.")
            async def delete_powerreactionothermsg(powerreactionothermsg):
                if DISCORD_DELETE_MESSAGES:
                    await asyncio.sleep(30)
                    await powerreactionothermsg.delete()
            asyncio.create_task(delete_powerreactionothermsg(powerreactionothermsg))
            return "reaction_cancelled"


@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user.name}')
    
    if DISCORD_CLEAR_CHANNEL:
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        
        if channel:
            try:
                await channel.purge(check=lambda msg: not msg.pinned)
                print(f'Cleared non-pinned messages in #{channel.name}')
            except discord.Forbidden:
                print(f"Bot doesn't have 'Manage Messages' permission in #{channel.name}")
            except discord.HTTPException as e:
                print(f"An error occurred while purging messages: {e}")

@tasks.loop(hours=24)
async def clear_channel():

    if DISCORD_CLEAR_CHANNEL:
        channel = bot.get_channel(DISCORD_CHANNEL_ID)

        if channel:
            try:
                await channel.purge(check=lambda msg: not msg.pinned)
                print(f'Cleared non-pinned messages in #{channel.name}')
            except discord.Forbidden:
                print(f"Bot doesn't have 'Manage Messages' permission in #{channel.name}")
            except discord.HTTPException as e:
                print(f"An error occurred while purging messages: {e}")

@bot.command(name='serverstatus', brief="Check Proxmox server status.")
async def server_status_command(ctx):
    if DISCORD_DELETE_MESSAGES:
        await ctx.message.delete()
    response = await check_proxmox_status(ctx, direct_command=True)
    if response is not None and response.status_code == 200:
        await offer_vm_power_options(ctx)
    elif response is None:
        statusoffermsg = await ctx.send(f"{ctx.author.mention}, Proxmox server may be offline.")
        async def delete_statusoffermsg(statusoffermsg):
            if DISCORD_DELETE_MESSAGES:
                await asyncio.sleep(30)
                await statusoffermsg.delete()
        asyncio.create_task(delete_statusoffermsg(statusoffermsg))
        offerpower = await offer_host_power_options(ctx)
        if offerpower == "reaction_cancelled":
            return
        await asyncio.sleep(PROXMOX_STARTUP_TIME)
        response = await check_proxmox_status(ctx, direct_command=True)
        if response is None:
            statuserrormsg = await ctx.send(f"{ctx.author.mention}, Something went wrong. Please reach out to the server admin.")
            if DISCORD_DELETE_MESSAGES:
                await asyncio.sleep(60)
                await statuserrormsg.delete()
        elif response.status_code == 200:
            await offer_vm_power_options(ctx)
    else:
        statuserrorothermsg = await ctx.send(f"{ctx.author.mention}, Failed to retrieve Proxmox server status.")
        if DISCORD_DELETE_MESSAGES:
            await asyncio.sleep(60)
            await statuserrorothermsg.delete()

@bot.command(name='startvm', brief="Start your Proxmox VM.")
async def start_vm_command(ctx):
    if DISCORD_DELETE_MESSAGES:
        await ctx.message.delete()
    # Check Proxmox server status
    server_status_response = await check_proxmox_status(ctx, direct_command=True)
    
    if server_status_response is not None and server_status_response.status_code == 200:
        # Proxmox server is online, proceed to check VM status
        vm_status = await check_vm_status(ctx)
        
        if vm_status == 'running':
            vmrunningmsg = await ctx.send(f"{ctx.author.mention}, VM is already running.")
            if DISCORD_DELETE_MESSAGES:
                await asyncio.sleep(30)
                await vmrunningmsg.delete()
        else:
            await turn_on_vm(ctx)
    elif server_status_response is None:
        poweroffermsg = await ctx.send(f"{ctx.author.mention}, Proxmox server may be offline. Would you like to try to power on the host?")
        async def delete_poweroffermsg(poweroffermsg):
            if DISCORD_DELETE_MESSAGES:
                await asyncio.sleep(30)
                await poweroffermsg.delete()
        asyncio.create_task(delete_poweroffermsg(poweroffermsg))
        await offer_host_power_options(ctx)
        server_status_response = await check_proxmox_status(ctx, direct_command=True)
        if server_status_response is None:
            poweroffererrormsg = await ctx.send(f"{ctx.author.mention}, something went wrong. Please reach out to the server admin.")
            if DISCORD_DELETE_MESSAGES:
                await asyncio.sleep(60)
                await poweroffererrormsg.delete()
        elif server_status_response.status_code == 200:
            vm_status = await check_vm_status(ctx)
            if vm_status == 'running':
                vmrunningmsg = await ctx.send(f"{ctx.author.mention}, VM is already running.")
                if DISCORD_DELETE_MESSAGES:
                    await asyncio.sleep(30)
                    await vmrunningmsg.delete()
            else:
                await turn_on_vm(ctx)
                vmstartmsg = await ctx.send(f"{ctx.author.mention}, VM started successfully.")
                if DISCORD_DELETE_MESSAGES:
                    await asyncio.sleep(30)
                    await vmstartmsg.delete()
    else:
        # Handle other cases where Proxmox server status is not 200
        startvmerrorothermsg = await ctx.send(f"{ctx.author.mention}, failed to retrieve Proxmox server status.")
        if DISCORD_DELETE_MESSAGES:
            await asyncio.sleep(60)
            await startvmerrorothermsg.delete()

@bot.command(name='stopvm', brief="Stop your Proxmox VM.")
async def stop_vm_command(ctx):
    if DISCORD_DELETE_MESSAGES:
        await ctx.message.delete()
    # Check Proxmox server status
    server_status_response = await check_proxmox_status(ctx, direct_command=True)
    
    if server_status_response.status_code == 200:
        # Proxmox server is online, proceed to check VM status
        vm_status = await check_vm_status(ctx)
        
        if vm_status != 'running':
            notrunningmsg = await ctx.send(f"{ctx.author.mention}, VM is not running.")
            if DISCORD_DELETE_MESSAGES:
                await asyncio.sleep(30)
                await notrunningmsg.delete()
        else:
            await shut_down_vm(ctx)
    else:
        stoperrormsg = await ctx.send(f"{ctx.author.mention}, Proxmox server is not responding. It may be already offline.")
        if DISCORD_DELETE_MESSAGES:
            await asyncio.sleep(60)
            await stoperrormsg.delete()

@bot.event
async def on_command_error(ctx, error):
    if DISCORD_DELETE_MESSAGES:
        await ctx.message.delete()
    if isinstance(error, commands.CommandNotFound):
        invalid_cmd_msg = await ctx.send(f"{ctx.author.mention}, invalid command. Here is a list of available commands:\n```{', '.join([command.name for command in bot.commands])}``` use the `!help` command for more information.")
        
        if DISCORD_DELETE_MESSAGES:
            await asyncio.sleep(60)
            await invalid_cmd_msg.delete()
    else :
        print(error)

@bot.command(name='poweron', brief="Power on the Proxmox host.")
async def power_on_command(ctx):
    if DISCORD_DELETE_MESSAGES:
        await ctx.message.delete()

    if DISCORD_POWER_OPTIONS:
        await power_on_host(ctx)
    else:
        power_off_disabled_msg = await ctx.send(f"{ctx.author.mention}, Host power options are disabled.")
        if DISCORD_DELETE_MESSAGES:
            await asyncio.sleep(60)
            await power_off_disabled_msg.delete()

@bot.command(name='poweroff', brief="Power off the Proxmox host.")
async def power_off_command(ctx):
    if DISCORD_DELETE_MESSAGES:
        await ctx.message.delete()

    if DISCORD_POWER_OPTIONS:
        await power_off_host(ctx)
    else:
        power_off_disabled_msg = await ctx.send(f"{ctx.author.mention}, Host power options are disabled.")
        if DISCORD_DELETE_MESSAGES:
            await asyncio.sleep(60)
            await power_off_disabled_msg.delete()

bot.run(DISCORD_TOKEN)
