FROM registry.redhat.io/rhel8/rust-toolset:1.47.0 as builder

WORKDIR /opt/app-root/src/
COPY . .
USER 0
RUN bash -c "source /opt/app-root/etc/scl_enable && cargo install --path graph-data.rs"

FROM registry.access.redhat.com/ubi8/ubi:latest

ENV RUST_LOG=actix_web=error,dkregistry=error

RUN yum update -y && \
    yum install -y openssl && \
    yum clean all

WORKDIR /code
COPY . .
COPY --from=builder /opt/app-root/src/.cargo/bin/cincinnati-graph-data /usr/local/bin/
COPY --from=builder /opt/app-root/src/graph-data.rs/public-keys /usr/local/share/public-keys

ENTRYPOINT ["/usr/local/bin/cincinnati-graph-data"]
