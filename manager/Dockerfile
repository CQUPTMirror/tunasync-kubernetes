FROM debian:11-slim

COPY tunasync /usr/bin/

RUN chmod +x /usr/bin/tunasync && mkdir /etc/tunasync/

COPY manager.conf /etc/tunasync/

VOLUME ["/var/lib/tunasync"]

EXPOSE 14242

ENTRYPOINT ["/bin/bash", "-c", "(tunasync manager --config /etc/tunasync/manager.conf)"]
