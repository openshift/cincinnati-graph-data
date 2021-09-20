FROM registry.access.redhat.com/ubi8/ubi:8.1
WORKDIR /home
COPY . graph-data
RUN mkdir -p /var/lib/cincinnati/graph-data
CMD cp -rp graph-data/* /var/lib/cincinnati/graph-data
