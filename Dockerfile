FROM python:3.13-slim

WORKDIR /telegram_assistant

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python", "-m", "app.main"]