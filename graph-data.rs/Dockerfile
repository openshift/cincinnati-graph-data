FROM registry.access.redhat.com/ubi8/ubi:latest as builder

WORKDIR /opt/app-root/src/
COPY . .
USER 0
RUN dnf update -y \
    && dnf install -y rust cargo openssl-devel \
    && dnf clean all

RUN cargo test --manifest-path graph-data.rs/Cargo.toml \
    && cargo install --locked --path graph-data.rs

FROM registry.access.redhat.com/ubi8/ubi:latest

ENV RUST_LOG=actix_web=error,dkregistry=error

RUN yum update -y && \
    yum install -y openssl && \
    yum clean all

WORKDIR /code
COPY . .
COPY --from=builder /root/.cargo/bin/cincinnati-graph-data /usr/local/bin/
COPY --from=builder /opt/app-root/src/graph-data.rs/public-keys /usr/local/share/public-keys

ENTRYPOINT ["/usr/local/bin/cincinnati-graph-data"]
