# Use an official Python runtime as the base image
FROM python:3.12.1-alpine

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt /app/requirements.txt

# Install the project dependencies
RUN apk update && \
    apk add --no-cache ipmitool gcc python3-dev musl-dev libffi-dev && \
    pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    apk del gcc python3-dev musl-dev libffi-dev

# Copy the project files into the container
COPY main.py /app/proxmox_bot.py

# Set the entry point command for the container
CMD [ "python", "/app/proxmox_bot.py", "--config-file", "/config/config.json" ]