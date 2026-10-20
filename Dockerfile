FROM python:3.12-slim

WORKDIR /levelbot

COPY requirements.txt .

RUN python -m pip install --upgrade pip
RUN python -m pip install -r requirements.txt

COPY main.py .
COPY cogs cogs
COPY *.json .

CMD ["python3", "main.py"]
