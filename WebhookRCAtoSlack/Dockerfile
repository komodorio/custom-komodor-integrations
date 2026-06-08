FROM golang:1.25-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY go.sum ./
COPY *.go ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /webhook-komodor-rca .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /webhook-komodor-rca /webhook-komodor-rca
EXPOSE 8080
ENTRYPOINT ["/webhook-komodor-rca"]
