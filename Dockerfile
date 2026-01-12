FROM python:3.11-slim-bookworm

WORKDIR /TLE

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    sqlite3 \
    libcairo2-dev \
    libgirepository1.0-dev \
    libpango1.0-dev \
    pkg-config \
    python3-dev \
    gir1.2-pango-1.0 \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY ./requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Run script
RUN chmod +x run.sh

ENTRYPOINT ["/TLE/run.sh"]
