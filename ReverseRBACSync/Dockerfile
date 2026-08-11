# Komodor Reverse RBAC Sync — scheduled sync image
#
# Build:  docker build -t <registry>/komodor-rbac-sync:latest .
# Runs:   sync_once.py (see CONTINUOUS_SYNC.md for the CronJob manifest)

FROM python:3.12-slim

ARG TARGETARCH=amd64

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && KUBECTL_VERSION="$(curl -Ls https://dl.k8s.io/release/stable.txt)" \
 && curl -Lo /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl" \
 && chmod +x /usr/local/bin/kubectl \
 && apt-get purge -y curl

RUN pip install --no-cache-dir requests

WORKDIR /opt/rbac-sync
COPY *.py ./

# Writable workdir for run artifacts (mount an emptyDir here)
ENV RBAC_SYNC_WORKDIR=/tmp/rbac-sync

USER 65534:65534

ENTRYPOINT ["python3", "/opt/rbac-sync/sync_once.py"]
