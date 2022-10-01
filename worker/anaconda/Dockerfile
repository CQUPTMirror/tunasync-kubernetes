FROM python:slim

COPY tunasync /usr/bin/

ADD anaconda.py /

RUN chmod +x /usr/bin/tunasync /anaconda.py && apt update && apt install -y curl && apt-get clean all && pip3 install --upgrade pip && STATIC_DEPS=true python3 -m pip install pyquery && python3 -m pip install requests[socks] && mkdir /etc/tunasync/

VOLUME ["/var/log/tunasync", "/data/mirrors"]

EXPOSE 6000

ENTRYPOINT ["/bin/bash", "-c", "(tunasync worker --config /etc/tunasync/worker.conf)"]
