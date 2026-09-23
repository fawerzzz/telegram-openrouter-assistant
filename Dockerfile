FROM python:3.13-slim
WORKDIR /telegram_assistant
COPY . .
RUN pip install -r requirements.txt
ENTRYPOINT ["python", "main.py"]