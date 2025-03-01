FROM python:3.9-slim

COPY requirements.txt .

RUN pip3 install -r requirements.txt

COPY icons_scraper.py .


# CMD ["python", "icons_scraper.py"]