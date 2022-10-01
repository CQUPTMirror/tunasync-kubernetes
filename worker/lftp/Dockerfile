FROM python:slim

COPY tunasync /usr/bin/

RUN chmod +x /usr/bin/tunasync && apt update && apt install lftp git -y && apt-get clean all && pip install requests[socks] && git clone https://github.com/tuna/tunasync-scripts.git && mkdir /etc/tunasync/

VOLUME ["/var/log/tunasync", "/data/mirrors"]

EXPOSE 6000

ENTRYPOINT ["/bin/bash", "-c", "(tunasync worker --config /etc/tunasync/worker.conf)"]
