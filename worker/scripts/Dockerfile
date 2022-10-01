FROM tunathu/tunasync-scripts

COPY tunasync /usr/bin/

RUN chmod +x /usr/bin/tunasync && git clone https://github.com/tuna/tunasync-scripts.git && mkdir /etc/tunasync/

VOLUME ["/var/log/tunasync", "/data/mirrors"]

EXPOSE 6000

ENTRYPOINT ["/bin/bash", "-c", "(tunasync worker --config /etc/tunasync/worker.conf)"]
