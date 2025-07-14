# syntax=docker/dockerfile:1.4
FROM python:3.11-slim

# instaliraj OS pakete
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg git \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# kopiraj dependencies pa instaliraj
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# kopiraj sav kod (main.py, yt.txt, output mape, ...)
COPY . .

# osiguraj da yt.txt ima ispravne permisije da yt-dlp može čitati cookieje
RUN chmod 600 yt.txt

# da container zna na kojem PORT-u Railway očekuje
ENV PORT ${PORT:-7860}

# expose bez obzira
EXPOSE $PORT

# koristi shell formu da $PORT zaživi
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
