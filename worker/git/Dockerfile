FROM debian:11-slim

COPY tunasync /usr/bin/

ADD git.sh /

RUN chmod +x /usr/bin/tunasync /git.sh && apt update && apt install git -y && apt-get clean all && mkdir /etc/tunasync/

VOLUME ["/var/log/tunasync", "/data/mirrors"]

EXPOSE 6000

ENTRYPOINT ["/bin/bash", "-c", "(tunasync worker --config /etc/tunasync/worker.conf)"]
