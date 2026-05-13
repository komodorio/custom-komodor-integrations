# Go middleware Dockerfile
FROM golang:1.26-alpine AS builder
WORKDIR /app
COPY . .
RUN go build -o webhook-middleware webhook-middleware.go

FROM alpine:3.19
WORKDIR /app
COPY --from=builder /app/webhook-middleware /usr/local/bin/webhook-middleware
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/webhook-middleware"]
