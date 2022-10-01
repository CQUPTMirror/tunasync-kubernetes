FROM python:slim

COPY tunasync /usr/bin/

ADD github-release.py /

RUN chmod +x /usr/bin/tunasync /github-release.py && pip install requests && mkdir /etc/tunasync/

VOLUME ["/var/log/tunasync", "/data/mirrors"]

EXPOSE 6000

ENTRYPOINT ["/bin/bash", "-c", "(tunasync worker --config /etc/tunasync/worker.conf)"]
