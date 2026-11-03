FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    PYTHONPATH=/app \
    TZ=Asia/Karachi

# Install compilers and the utilities used inside disposable execution containers.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    bubblewrap \
    procps \
    libcap2-bin \
    util-linux \
    time \
    curl \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged judge sandbox user
RUN useradd -m -u 10001 -s /bin/bash judge_sandbox

# Set up app directory
WORKDIR /app

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and selftest files
COPY . .

# Ensure sandbox user has permissions to run binaries in temp dirs
RUN chmod 755 /app

CMD ["pytest", "-v"]
