FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the hermes package into /app/hermes so `python -m hermes` resolves correctly
COPY . hermes/

CMD ["python", "-m", "hermes"]
