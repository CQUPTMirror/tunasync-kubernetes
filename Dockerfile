FROM python:slim

WORKDIR /usr/src/app

ADD requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

ADD *.py ./

EXPOSE 8080

CMD ["python", "app.py"]