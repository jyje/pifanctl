FROM python:3.13-slim AS builder

# Install debian packages
RUN apt-get update && \
    apt-get install -y gcc
        
# Install python dependencies
COPY ./sources/ /workspace
WORKDIR /workspace
RUN pip install --upgrade --no-cache-dir pip
RUN pip install --upgrade --no-cache-dir -r requirements.all.txt

# Run the command
CMD ["python", "main.py", "--help"]

# TODO: Add runner stage
