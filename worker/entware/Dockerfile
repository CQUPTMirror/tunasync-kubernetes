FROM debian:11-slim

COPY tunasync /usr/bin/

ADD entware.sh /

RUN chmod +x /usr/bin/tunasync /entware.sh && apt update && apt install -y wget && apt-get clean all && mkdir /etc/tunasync/

VOLUME ["/var/log/tunasync", "/data/mirrors"]

EXPOSE 6000

ENTRYPOINT ["/bin/bash", "-c", "(tunasync worker --config /etc/tunasync/worker.conf)"]
