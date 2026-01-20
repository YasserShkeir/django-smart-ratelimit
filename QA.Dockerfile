FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Copy the library source
COPY . /app/django-ratelimit

# Copy the integration test project
COPY tests/test_project /app/test_project

# Set up Python environment
WORKDIR /app/test_project
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
# Install the library in editable mode so changes in the volume mount are reflected
RUN pip install -e /app/django-ratelimit

# Create entrypoint script that runs migrations before starting server
RUN echo '#!/bin/bash\nset -e\npython manage.py migrate --noinput\nexec "$@"' > /entrypoint.sh && chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

# Default command
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
