FROM python:3.12-slim

# No .pyc files; output is sent straight away instead of held in a buffer, so
# log lines appear at once; no pip update check.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The build context is the repo root (see docker-compose.yml) so that
# SYSTEM_PROMPT.md, which lives next to the README, can be baked into the image.
COPY middleware/pyproject.toml middleware/constraints.txt ./
COPY middleware/app ./app
# -c pins every package to the version in constraints.txt.
RUN pip install --no-cache-dir -c constraints.txt .

COPY SYSTEM_PROMPT.md ./

RUN useradd --system --no-create-home --shell /usr/sbin/nologin middleware
USER middleware

EXPOSE 8000
# Access logging is off because the app emits its own request.completed event.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
