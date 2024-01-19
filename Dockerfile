# Use an official Python runtime as the base image
FROM python:3.12.1

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt /app/requirements.txt

# Install the project dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN apt update && apt install -y ipmitool && apt clean && rm -rf /var/lib/apt/lists/*

# Copy the project files into the container
COPY main.py /app/proxmox_bot.py

# Set the entry point command for the container
CMD [ "python", "/app/proxmox_bot.py", "--config-file", "/config/config.json" ]
