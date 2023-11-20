# Proxmox Discord Bot

## Discord Integration
- The bot connects to Discord using the `discord.py` library.
- It initializes the bot with a command prefix and privileged intents.
- Configuration settings are loaded from a `config.json` file.

## Proxmox Integration
- The bot interacts with a Proxmox server using the Proxmox API.
- It retrieves the server status and performs VM power operations.
- Users can request power operations if the Proxmox server is ready.
- Error handling is implemented to provide appropriate messages.

## IPMI Integration
- The bot establishes a connection with an IPMI-enabled device using the `pyipmi` library.
- Constants for IPMI power control commands are provided.
- IPMI session setup includes host, username, password, and port.

## Discord-to-VM Mapping
- The bot maintains a mapping between Discord user IDs and VM IDs.
- Users can request VM power operations based on their Discord ID and the corresponding VM ID.

## Additional Configurations
- The bot supports various configuration options, such as message deletion, channel clearing, and power options.
