FROM python:slim

COPY tunasync /usr/bin/

ADD pypi.sh /

RUN chmod +x /usr/bin/tunasync /pypi.sh && pip install bandersnatch && mkdir /etc/tunasync/

VOLUME ["/var/log/tunasync", "/data/mirrors"]

EXPOSE 6000

ENTRYPOINT ["/bin/bash", "-c", "(tunasync worker --config /etc/tunasync/worker.conf)"]
