package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/samber/lo"
)

const (
	defaultListenAddr     = ":8080"
	defaultKomodorURL     = "https://api.komodor.com/mgmt/v1/events"
	defaultRequestTimeout = 10 * time.Second
)

type AlertmanagerPayload struct {
	Receiver string              `json:"receiver"`
	Status   string              `json:"status"`
	Alerts   []AlertmanagerAlert `json:"alerts"`
	GroupKey string              `json:"groupKey"`
}

type AlertmanagerAlert struct {
	Status       string            `json:"status"`
	Labels       map[string]string `json:"labels"`
	Annotations  map[string]string `json:"annotations"`
	StartsAt     string            `json:"startsAt"`
	EndsAt       string            `json:"endsAt"`
	GeneratorURL string            `json:"generatorURL"`
	Fingerprint  string            `json:"fingerprint"`
}

type KomodorEvent struct {
	EventType string            `json:"eventType"`
	Summary   string            `json:"summary"`
	Scope     KomodorScope      `json:"scope"`
	Severity  string            `json:"severity,omitempty"`
	Details   map[string]string `json:"details,omitempty"`
}

type KomodorScope struct {
	Clusters      []string `json:"clusters"`
	Namespaces    []string `json:"namespaces,omitempty"`
	ServicesNames []string `json:"servicesNames,omitempty"`
}

type Server struct {
	logger     *slog.Logger
	client     *retryablehttp.Client
	komodorURL string
	komodorKey string
}

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))

	retryClient := retryablehttp.NewClient()
	retryClient.RetryMax = 3
	retryClient.Logger = nil // disable retryablehttp's own logging
	retryClient.HTTPClient.Timeout = envDuration("REQUEST_TIMEOUT", defaultRequestTimeout)

	server := &Server{
		logger:     logger,
		client:     retryClient,
		komodorURL: envString("KOMODOR_API_URL", defaultKomodorURL),
		komodorKey: os.Getenv("KOMODOR_API_KEY"),
	}

	if server.komodorKey == "" {
		logger.Error("KOMODOR_API_KEY is not set, exiting")
		os.Exit(1)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", server.healthzHandler)
	mux.HandleFunc("/alertmanager", server.alertmanagerHandler)

	listenAddr := envString("LISTEN_ADDR", defaultListenAddr)

	logger.Info("starting alertmanager komodor adapter", "listen_addr", listenAddr)

	if err := http.ListenAndServe(listenAddr, mux); err != nil {
		logger.Error("server stopped", "error", err)
		os.Exit(1)
	}
}

func (s *Server) healthzHandler(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *Server) alertmanagerHandler(w http.ResponseWriter, r *http.Request) {
	if s.komodorKey == "" {
		http.Error(w, "KOMODOR_API_KEY is not configured", http.StatusInternalServerError)
		return
	}

	var payload AlertmanagerPayload
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		http.Error(w, "invalid alertmanager payload", http.StatusBadRequest)
		return
	}

	sent := 0

	for _, alert := range payload.Alerts {
		event, err := buildKomodorEvent(alert)
		if err != nil {
			s.logger.Warn(
				"skipping alert without required cluster label",
				"alertname", alert.Labels["alertname"],
				"fingerprint", alert.Fingerprint,
			)
			continue
		}

		if err := s.sendKomodorEvent(r.Context(), event); err != nil {
			s.logger.Error(
				"failed to send komodor event",
				"alertname", alert.Labels["alertname"],
				"fingerprint", alert.Fingerprint,
				"error", err,
			)

			http.Error(w, "failed to send komodor event", http.StatusBadGateway)
			return
		}

		sent++
	}

	writeJSON(w, http.StatusOK, map[string]int{
		"received": len(payload.Alerts),
		"sent":     sent,
	})
}

func buildKomodorEvent(alert AlertmanagerAlert) (KomodorEvent, error) {
	cluster := strings.TrimSpace(alert.Labels["cluster"])
	if cluster == "" {
		return KomodorEvent{}, errors.New("missing required cluster label")
	}

	alertName := lo.Ternary(strings.TrimSpace(alert.Labels["alertname"]) != "", alert.Labels["alertname"], "AlertmanagerAlert")
	eventType := lo.Substring(alertName, 0, 30)

	summary, _ := lo.Find([]string{
		alert.Annotations["summary"],
		alert.Annotations["description"],
		strings.ToTitle(alert.Status) + ": " + alertName,
	}, func(s string) bool { return strings.TrimSpace(s) != "" })

	namespace, _ := lo.Find([]string{
		alert.Labels["namespace"],
		alert.Labels["kubernetes_namespace"],
	}, func(s string) bool { return strings.TrimSpace(s) != "" })

	service, _ := lo.Find([]string{
		alert.Labels["service"],
		alert.Labels["service_name"],
		alert.Labels["app"],
		alert.Labels["app_kubernetes_io_name"],
		alert.Labels["deployment"],
		alert.Labels["statefulset"],
		alert.Labels["daemonset"],
	}, func(s string) bool { return strings.TrimSpace(s) != "" })

	var details = map[string]string{}
	for key, value := range alert.Labels {
		details["label_"+key] = value
	}

	for key, value := range alert.Annotations {
		details["annotation_"+key] = value
	}

	return KomodorEvent{
		EventType: eventType,
		Summary:   summary,
		Scope: KomodorScope{
			Clusters:      []string{cluster},
			Namespaces:    lo.Ternary(namespace != "", []string{namespace}, nil),
			ServicesNames: lo.Ternary(service != "", []string{service}, nil),
		},
		Severity: mapSeverity(alert.Labels["severity"], alert.Status),
		Details:  details,
	}, nil
}

func (s *Server) sendKomodorEvent(ctx context.Context, event KomodorEvent) error {
	body, err := json.Marshal(event)
	if err != nil {
		return err
	}

	req, err := retryablehttp.NewRequestWithContext(
		ctx,
		http.MethodPost,
		s.komodorURL,
		bytes.NewReader(body),
	)
	if err != nil {
		return err
	}

	req.Header.Set("content-type", "application/json")
	req.Header.Set("x-api-key", s.komodorKey)

	resp, err := s.client.Do(req)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusCreated {
		responseBody, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return errors.New("komodor api returned " + resp.Status + ": " + string(responseBody))
	}

	return nil
}

func mapSeverity(severity string, status string) string {
	if status == "resolved" {
		return "information"
	}

	switch strings.ToLower(severity) {
	case "critical", "error", "page":
		return "error"
	case "warning", "warn":
		return "warning"
	default:
		return "information"
	}
}

func envString(key string, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}

	return value
}

func envDuration(key string, fallback time.Duration) time.Duration {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}

	duration, err := time.ParseDuration(value)
	if err != nil {
		return fallback
	}

	return duration
}

func writeJSON(w http.ResponseWriter, statusCode int, body any) {
	w.Header().Set("content-type", "application/json")
	w.WriteHeader(statusCode)

	_ = json.NewEncoder(w).Encode(body)
}
