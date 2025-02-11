FROM python:3.13-slim AS builder

# Install debian packages
# RUN apt-get update && \
#     apt-get install -y git
        
# Install python dependencies
COPY ./sources/ /workspace
WORKDIR /workspace
RUN pip install --upgrade --no-cache-dir pip
RUN pip install --upgrade --no-cache-dir -r requirements.txt

# Create user with UID 1000
RUN useradd -m -u 1000 user
USER user

# Run the command
CMD ["python", "main.py", "--help"]

# TODO: Add runner stage
