FROM golang:1.22 AS builder

WORKDIR /src/services/go-gateway
COPY services/go-gateway/go.mod services/go-gateway/go.sum ./
RUN go mod download
COPY services/go-gateway/. .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /out/go-gateway .

FROM alpine:3.20
RUN adduser -D -H -u 10001 appuser
COPY --from=builder /out/go-gateway /usr/local/bin/go-gateway
USER appuser
EXPOSE 8090
ENTRYPOINT ["/usr/local/bin/go-gateway"]
