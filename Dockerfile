FROM golang:1.24.1 AS go-toolchain

FROM python:3.11.10-slim AS backend-build
COPY --from=go-toolchain /usr/local/go /usr/local/go
ENV PATH="/usr/local/go/bin:${PATH}"
WORKDIR /build
COPY route_go/security route_go/security
ARG TARGETARCH
RUN python route_go/security/build_backend.py --target "linux-${TARGETARCH:-amd64}"

FROM python:3.11.10-slim



ENV NAMU_DB_TYPE sqlite
ENV NAMU_DB data
ENV NAMU_HOST 0.0.0.0
ENV NAMU_PORT 3000
ENV NAMU_GOLANGPORT 3001
ENV NAMU_LANG en-US
ENV NAMU_MARKUP namumark
ENV NAMU_ENCRYPT sha3
ENV NAMU_DOCKER O

ADD . /app
COPY --from=backend-build /build/route_go/bin /app/route_go/bin
COPY --from=backend-build /build/route_go/security/manifest.json /app/route_go/security/manifest.json
WORKDIR /app

RUN pip install -r requirements.txt
EXPOSE 3000

CMD [ "python", "./app.py" ]
