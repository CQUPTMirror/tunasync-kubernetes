FROM debian:11-slim

COPY tunasync /usr/bin/

RUN chmod +x /usr/bin/tunasync && apt update && apt install -y rsync && apt-get clean all && mkdir /etc/tunasync/

VOLUME ["/var/log/tunasync", "/data/mirrors"]

EXPOSE 6000

ENTRYPOINT ["/bin/bash", "-c", "(tunasync worker --config /etc/tunasync/worker.conf)"]
