package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/sirupsen/logrus"
)

type Config struct {
	ListenAddr         string
	KomodorBaseURL     string
	KomodorAPIKey      string
	SlackBaseURL       string
	SlackBotToken      string
	SlackWebhookURI    string
	SlackChannel       string
	WebhookToken       string
	DefaultKind        string
	ProcessStatuses    map[string]bool
	ProcessSeverities  map[string]bool
	PublishCustomEvent bool
	Synchronous        bool
	PollInitial        time.Duration
	PollMax            time.Duration
	InvestigationTTL   time.Duration
	LogLevel           string
}

type Server struct {
	cfg    Config
	client *http.Client
	logger *logrus.Logger
}

type contextKey string

const requestIDKey contextKey = "request_id"

type WebhookEvent struct {
	Alert    *WebhookAlert `json:"alert"`
	Resource *Resource     `json:"resource"`

	Labels      map[string]any `json:"labels"`
	Status      string         `json:"status"`
	Fingerprint string         `json:"fingerprint"`
	Title       string         `json:"title"`
	AlertName   string         `json:"alertname"` // Legacy alert-provider alias for title.
	Kind        string         `json:"kind"`
	IssueID     string         `json:"issueId"`
	Severity    string         `json:"severity"`
	Metadata    map[string]any `json:"metadata"`
}

type WebhookAlert struct {
	Labels      map[string]any `json:"labels"`
	Status      string         `json:"status"`
	Fingerprint string         `json:"fingerprint"`
	Title       string         `json:"title"`
	AlertName   string         `json:"alertname"`
	Kind        string         `json:"kind"`
	IssueID     string         `json:"issueId"`
	Severity    string         `json:"severity"`
	Metadata    map[string]any `json:"metadata"`
}

type Resource struct {
	Kind        string `json:"kind"`
	Name        string `json:"name"`
	Namespace   string `json:"namespace"`
	ClusterName string `json:"clusterName"`
}

type RCARequest struct {
	Kind        string  `json:"kind"`
	Name        string  `json:"name"`
	Namespace   string  `json:"namespace"`
	ClusterName string  `json:"clusterName"`
	IssueID     *string `json:"issueId,omitempty"`
}

type RCAStartResponse struct {
	SessionID  string `json:"sessionId"`
	SessionURL string `json:"sessionUrl"`
}

type CustomEventRequest struct {
	EventType string           `json:"eventType"`
	Summary   string           `json:"summary"`
	Severity  string           `json:"severity"`
	Scope     CustomEventScope `json:"scope"`
}

type CustomEventScope struct {
	Clusters      []string          `json:"clusters,omitempty"`
	ServicesNames []string          `json:"servicesNames,omitempty"`
	Namespaces    []string          `json:"namespaces,omitempty"`
	Details       map[string]string `json:"details,omitempty"`
}

type Evidence struct {
	Snippet string `json:"snippet"`
	Query   string `json:"query"`
}

type Remediation struct {
	Explanation          string   `json:"explanation"`
	Reasoning            string   `json:"reasoning"`
	Recommendation       string   `json:"recommendation"`
	RawCommand           string   `json:"rawCommand"`
	RejectedAlternatives []string `json:"rejectedAlternatives"`
	LongTermRemediation  string   `json:"longTermRemediation"`
}

type RCAResult struct {
	SessionID             string       `json:"sessionId"`
	SessionURL            string       `json:"sessionUrl"`
	IsComplete            bool         `json:"isComplete"`
	IsStuck               bool         `json:"isStuck"`
	IsFailed              bool         `json:"isFailed"`
	Operations            []string     `json:"operations"`
	ProblemShort          string       `json:"problemShort"`
	WhatHappened          []string     `json:"whatHappened"`
	EvidenceCollection    []Evidence   `json:"evidenceCollection"`
	KnowledgeBaseEvidence []Evidence   `json:"knowledgeBaseEvidence"`
	Recommendation        string       `json:"recommendation"`
	Classification        string       `json:"classification"`
	Remediation           *Remediation `json:"remediation"`
}

type slackResponse struct {
	OK    bool   `json:"ok"`
	TS    string `json:"ts"`
	Error string `json:"error"`
}

func main() {
	logger := newLogger(env("LOG_LEVEL", "info"))
	cfg, err := loadConfig()
	if err != nil {
		logger.WithError(err).WithField("event", "configuration_invalid").Error("configuration invalid")
		os.Exit(1)
	}

	server := &Server{
		cfg:    cfg,
		client: &http.Client{Timeout: 20 * time.Second},
		logger: logger,
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	})
	mux.HandleFunc("POST /webhooks/rca", server.handleWebhook)
	mux.HandleFunc("POST /webhooks/groundcover", server.handleWebhook) // Backward-compatible alias.

	httpServer := &http.Server{
		Addr:              cfg.ListenAddr,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      15 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		logger.WithField("event", "service_stopping").Info("service stopping")
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		_ = httpServer.Shutdown(shutdownCtx)
	}()

	logger.WithFields(logrus.Fields{
		"event":                "service_started",
		"address":              cfg.ListenAddr,
		"log_level":            cfg.LogLevel,
		"processing_mode":      map[bool]string{true: "synchronous", false: "asynchronous"}[cfg.Synchronous],
		"slack_mode":           map[bool]string{true: "bot", false: "webhook"}[cfg.SlackBotToken != "" && cfg.SlackChannel != ""],
		"publish_custom_event": cfg.PublishCustomEvent,
		"process_statuses":     setKeys(cfg.ProcessStatuses),
		"process_severities":   setKeys(cfg.ProcessSeverities),
	}).Info("service started")
	if err := httpServer.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		logger.WithError(err).WithField("event", "service_failed").Error("service failed")
		os.Exit(1)
	}
	logger.WithField("event", "service_stopped").Info("service stopped")
}

func loadConfig() (Config, error) {
	komodorAPIKey, err := secretValue("KOMODOR_API_KEY")
	if err != nil {
		return Config{}, err
	}
	slackBotToken, err := secretValue("SLACK_BOT_TOKEN")
	if err != nil {
		return Config{}, err
	}
	slackWebhookURI, err := secretValue("SLACK_WEBHOOK_URI")
	if err != nil {
		return Config{}, err
	}
	webhookToken, err := secretValue("WEBHOOK_TOKEN")
	if err != nil {
		return Config{}, err
	}

	cfg := Config{
		ListenAddr:         env("LISTEN_ADDR", ":8080"),
		KomodorBaseURL:     strings.TrimRight(env("KOMODOR_BASE_URL", "https://api.komodor.com"), "/"),
		KomodorAPIKey:      komodorAPIKey,
		SlackBaseURL:       strings.TrimRight(env("SLACK_BASE_URL", "https://slack.com/api"), "/"),
		SlackBotToken:      slackBotToken,
		SlackWebhookURI:    slackWebhookURI,
		SlackChannel:       os.Getenv("SLACK_CHANNEL_ID"),
		WebhookToken:       webhookToken,
		DefaultKind:        env("DEFAULT_WORKLOAD_KIND", "Deployment"),
		ProcessStatuses:    statusSet(env("PROCESS_STATUSES", "firing")),
		ProcessSeverities:  statusSet(env("PROCESS_SEVERITIES", "critical")),
		PublishCustomEvent: boolEnv("PUBLISH_CUSTOM_EVENT", true),
		Synchronous:        boolEnv("SYNCHRONOUS_PROCESSING", false),
		PollInitial:        durationEnv("POLL_INITIAL_INTERVAL", 5*time.Second),
		PollMax:            durationEnv("POLL_MAX_INTERVAL", 10*time.Second),
		InvestigationTTL:   durationEnv("INVESTIGATION_TIMEOUT", 20*time.Minute),
		LogLevel:           env("LOG_LEVEL", "info"),
	}
	if cfg.KomodorAPIKey == "" {
		return Config{}, errors.New("KOMODOR_API_KEY is required")
	}
	if cfg.SlackWebhookURI == "" && (cfg.SlackBotToken == "" || cfg.SlackChannel == "") {
		return Config{}, errors.New("SLACK_WEBHOOK_URI or both SLACK_BOT_TOKEN and SLACK_CHANNEL_ID are required")
	}
	if cfg.PollInitial <= 0 || cfg.PollMax < cfg.PollInitial || cfg.InvestigationTTL <= 0 {
		return Config{}, errors.New("poll intervals and investigation timeout must be positive, and POLL_MAX_INTERVAL must not be less than POLL_INITIAL_INTERVAL")
	}
	return cfg, nil
}

func secretValue(key string) (string, error) {
	if value := os.Getenv(key); value != "" {
		return value, nil
	}
	path := os.Getenv(key + "_FILE")
	if path == "" {
		return "", nil
	}
	value, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("read %s_FILE: %w", key, err)
	}
	return strings.TrimSpace(string(value)), nil
}

func (s *Server) handleWebhook(w http.ResponseWriter, r *http.Request) {
	started := time.Now()
	requestID := truncate(firstNonEmpty(r.Header.Get("X-Request-ID"), newRequestID()), 128)
	w.Header().Set("X-Request-ID", requestID)
	ctx := context.WithValue(r.Context(), requestIDKey, requestID)
	r = r.WithContext(ctx)
	s.audit(ctx, logrus.Fields{
		"event":       "webhook_received",
		"http_method": r.Method,
		"http_path":   r.URL.Path,
		"remote_ip":   remoteIP(r),
	}).Info("webhook received")

	if !s.authorized(r) {
		s.audit(ctx, logrus.Fields{"event": "webhook_rejected", "reason": "unauthorized", "status_code": http.StatusUnauthorized, "duration_ms": time.Since(started).Milliseconds()}).Warn("webhook rejected")
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}

	var event WebhookEvent
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20))
	if err := decoder.Decode(&event); err != nil {
		s.audit(ctx, logrus.Fields{"event": "webhook_rejected", "reason": "invalid_json", "status_code": http.StatusBadRequest, "duration_ms": time.Since(started).Milliseconds()}).WithError(err).Warn("webhook rejected")
		http.Error(w, "invalid JSON payload", http.StatusBadRequest)
		return
	}
	event = normalizeEvent(event)
	if event.Severity == "" {
		event.Severity = firstLabel(event.Labels, "severity", "priority")
	}
	if len(event.Labels) == 0 && event.Resource == nil {
		s.audit(ctx, eventFields(event, RCARequest{})).WithFields(logrus.Fields{"event": "webhook_rejected", "reason": "missing_resource", "status_code": http.StatusBadRequest, "duration_ms": time.Since(started).Milliseconds()}).Warn("webhook rejected")
		http.Error(w, "event must contain resource, labels, or alert.labels", http.StatusBadRequest)
		return
	}
	if event.Status != "" && !s.cfg.ProcessStatuses[strings.ToLower(event.Status)] {
		s.audit(ctx, eventFields(event, RCARequest{})).WithFields(logrus.Fields{"event": "webhook_ignored", "reason": "status_filtered", "duration_ms": time.Since(started).Milliseconds()}).Info("webhook ignored")
		writeJSON(w, http.StatusAccepted, map[string]string{"status": "ignored", "reason": "alert status is not configured for processing"})
		return
	}
	if len(s.cfg.ProcessSeverities) > 0 && !s.cfg.ProcessSeverities[strings.ToLower(event.Severity)] {
		s.audit(ctx, eventFields(event, RCARequest{})).WithFields(logrus.Fields{"event": "webhook_ignored", "reason": "severity_filtered", "duration_ms": time.Since(started).Milliseconds()}).Info("webhook ignored")
		writeJSON(w, http.StatusAccepted, map[string]string{"status": "ignored", "reason": "event severity is not configured for processing"})
		return
	}

	rca, err := rcaRequestFromEvent(event, s.cfg.DefaultKind)
	if err != nil {
		s.audit(ctx, eventFields(event, RCARequest{})).WithFields(logrus.Fields{"event": "webhook_rejected", "reason": "invalid_resource", "status_code": http.StatusUnprocessableEntity, "duration_ms": time.Since(started).Milliseconds()}).WithError(err).Warn("webhook rejected")
		http.Error(w, err.Error(), http.StatusUnprocessableEntity)
		return
	}

	if s.cfg.Synchronous {
		s.audit(ctx, eventFields(event, rca)).WithFields(logrus.Fields{"event": "webhook_accepted", "processing_mode": "synchronous", "status_code": http.StatusOK}).Info("webhook accepted")
		s.investigate(ctx, event, rca)
		s.audit(ctx, eventFields(event, rca)).WithFields(logrus.Fields{"event": "webhook_completed", "duration_ms": time.Since(started).Milliseconds()}).Info("webhook completed")
		writeJSON(w, http.StatusOK, map[string]string{"status": "completed"})
		return
	}

	s.audit(ctx, eventFields(event, rca)).WithFields(logrus.Fields{"event": "webhook_accepted", "processing_mode": "asynchronous", "status_code": http.StatusAccepted, "duration_ms": time.Since(started).Milliseconds()}).Info("webhook accepted")
	go s.investigate(context.WithoutCancel(ctx), event, rca)
	writeJSON(w, http.StatusAccepted, map[string]string{"status": "accepted"})
}

func (s *Server) authorized(r *http.Request) bool {
	if s.cfg.WebhookToken == "" {
		return true
	}
	provided := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	if provided == "" {
		provided = r.Header.Get("X-Webhook-Token")
	}
	return subtle.ConstantTimeCompare([]byte(provided), []byte(s.cfg.WebhookToken)) == 1
}

func normalizeEvent(event WebhookEvent) WebhookEvent {
	if event.Alert == nil {
		return event
	}
	event.Labels = event.Alert.Labels
	event.Status = event.Alert.Status
	event.Fingerprint = event.Alert.Fingerprint
	event.Title = firstNonEmpty(event.Alert.Title, event.Alert.AlertName)
	event.AlertName = event.Alert.AlertName
	event.Kind = event.Alert.Kind
	event.IssueID = event.Alert.IssueID
	event.Severity = event.Alert.Severity
	event.Metadata = event.Alert.Metadata
	return event
}

func rcaRequestFromEvent(event WebhookEvent, defaultKind string) (RCARequest, error) {
	labels := event.Labels
	rca := RCARequest{
		Kind:        firstLabel(labels, "kind", "workload_kind", "resource_kind"),
		Name:        firstLabel(labels, "name", "workload_name", "workload", "service_name", "pod_name"),
		Namespace:   firstLabel(labels, "namespace", "k8s_namespace"),
		ClusterName: firstLabel(labels, "clusterName", "cluster_name", "cluster", "clusterId", "cluster_id"),
	}
	if event.Resource != nil {
		rca.Kind = firstNonEmpty(event.Resource.Kind, rca.Kind)
		rca.Name = firstNonEmpty(event.Resource.Name, rca.Name)
		rca.Namespace = firstNonEmpty(event.Resource.Namespace, rca.Namespace)
		rca.ClusterName = firstNonEmpty(event.Resource.ClusterName, rca.ClusterName)
	}
	if rca.Kind == "" {
		rca.Kind = firstNonEmpty(event.Kind, defaultKind)
	}
	issueID := firstNonEmpty(event.IssueID, firstLabel(labels, "issueId", "issue_id"))
	if issueID != "" {
		rca.IssueID = &issueID
	}

	var missing []string
	if rca.Kind == "" {
		missing = append(missing, "kind")
	}
	if rca.Name == "" {
		missing = append(missing, "name/workload_name/workload")
	}
	if rca.Namespace == "" {
		missing = append(missing, "namespace")
	}
	if rca.ClusterName == "" {
		missing = append(missing, "clusterName/cluster/clusterId")
	}
	if len(missing) > 0 {
		return RCARequest{}, fmt.Errorf("missing required resource fields or labels: %s", strings.Join(missing, ", "))
	}
	return rca, nil
}

func (s *Server) investigate(parent context.Context, event WebhookEvent, rca RCARequest) {
	started := time.Now()
	ctx, cancel := context.WithTimeout(parent, s.cfg.InvestigationTTL)
	defer cancel()
	log := s.audit(ctx, eventFields(event, rca))
	log.WithField("event", "rca_investigation_started").Info("RCA investigation started")

	start, err := s.startRCA(ctx, rca)
	if err != nil {
		log.WithError(err).WithFields(logrus.Fields{"event": "rca_session_create_failed", "duration_ms": time.Since(started).Milliseconds()}).Error("RCA session creation failed")
		_, _ = s.postSlack(ctx, failureMessage(event, rca, "Could not start Komodor RCA: "+err.Error()), "")
		return
	}

	log = log.WithField("session_id", start.SessionID)
	log.WithFields(logrus.Fields{"event": "rca_session_created", "duration_ms": time.Since(started).Milliseconds()}).Info("RCA session created")
	if s.cfg.PublishCustomEvent {
		if err := s.publishRCAStartedEvent(ctx, event, rca, start); err != nil {
			log.WithError(err).WithField("event", "custom_event_publish_failed").Warn("custom event publication failed")
		} else {
			log.WithField("event", "custom_event_published").Info("custom event published")
		}
	}

	threadTS := ""
	if s.cfg.SlackBotToken != "" && s.cfg.SlackChannel != "" {
		threadTS, err = s.postSlack(ctx, initialMessage(event, rca, start), "")
		if err != nil {
			log.WithError(err).WithField("event", "slack_initial_post_failed").Error("Slack initial post failed")
			threadTS = ""
		} else {
			log.WithField("event", "slack_initial_posted").Info("Slack initial message posted")
			if err := s.slackReaction(ctx, "add", "hourglass_flowing_sand", threadTS); err != nil {
				log.WithError(err).WithField("event", "slack_loading_reaction_failed").Warn("Slack loading reaction failed")
			}
		}
	}

	result, err := s.pollRCA(ctx, start.SessionID)
	if err != nil {
		log.WithError(err).WithFields(logrus.Fields{"event": "rca_investigation_failed", "duration_ms": time.Since(started).Milliseconds()}).Error("RCA investigation failed")
		_, _ = s.postSlack(context.WithoutCancel(ctx), failureMessage(event, rca, "Komodor RCA did not complete: "+err.Error()+"\n"+start.SessionURL), threadTS)
		s.finishSlackReaction(context.WithoutCancel(ctx), log, threadTS, "x")
		return
	}
	log.WithFields(logrus.Fields{
		"event":           "rca_investigation_completed",
		"duration_ms":     time.Since(started).Milliseconds(),
		"classification":  result.Classification,
		"operation_count": len(result.Operations),
		"evidence_count":  len(result.EvidenceCollection),
		"has_remediation": result.Remediation != nil,
	}).Info("RCA investigation completed")

	summary := summaryMessage(event, rca, result)
	details := detailMessages(event, result)
	if s.cfg.SlackBotToken == "" || s.cfg.SlackChannel == "" {
		if len(details) > 0 {
			summary += "\n\n" + strings.Join(details, "\n\n")
		}
		_, err := s.postSlack(ctx, summary, "")
		if err != nil {
			log.WithError(err).WithField("event", "slack_result_post_failed").Error("Slack result post failed")
		} else {
			log.WithField("event", "slack_result_posted").Info("Slack result posted")
		}
		return
	}

	if threadTS == "" {
		threadTS, err = s.postSlack(ctx, initialMessage(event, rca, start), "")
		if err != nil {
			log.WithError(err).WithField("event", "slack_initial_post_failed").Error("Slack initial post failed")
			return
		}
		if err := s.slackReaction(ctx, "add", "hourglass_flowing_sand", threadTS); err != nil {
			log.WithError(err).WithField("event", "slack_loading_reaction_failed").Warn("Slack loading reaction failed")
		}
	}
	if _, err := s.postSlack(ctx, summary, threadTS); err != nil {
		log.WithError(err).WithField("event", "slack_summary_reply_failed").Error("Slack summary reply failed")
		s.finishSlackReaction(ctx, log, threadTS, "x")
		return
	}
	log.WithField("event", "slack_summary_replied").Info("Slack summary posted to thread")
	for _, detail := range details {
		if _, err := s.postSlack(ctx, detail, threadTS); err != nil {
			log.WithError(err).WithField("event", "slack_detail_reply_failed").Error("Slack detail reply failed")
			s.finishSlackReaction(ctx, log, threadTS, "x")
			return
		}
	}
	log.WithFields(logrus.Fields{"event": "slack_details_replied", "detail_count": len(details)}).Info("Slack details posted to thread")
	s.finishSlackReaction(ctx, log, threadTS, "white_check_mark")
}

func initialMessage(event WebhookEvent, rca RCARequest, start RCAStartResponse) string {
	severity := firstNonEmpty(event.Severity, "unspecified")
	return fmt.Sprintf("*RCA triggered* — %s\n*Resource:* `%s/%s` in `%s` (`%s`)\n*Severity:* `%s`\n<%s|Open RCA session>",
		firstNonEmpty(event.Title, event.AlertName, "Webhook event"), rca.Kind, rca.Name, rca.Namespace, rca.ClusterName, severity, start.SessionURL)
}

func (s *Server) publishRCAStartedEvent(ctx context.Context, event WebhookEvent, rca RCARequest, start RCAStartResponse) error {
	details := metadataStrings(event.Metadata)
	details["rcaSessionId"] = start.SessionID
	details["rcaSessionUrl"] = start.SessionURL
	if event.Fingerprint != "" {
		details["fingerprint"] = event.Fingerprint
	}
	if event.IssueID != "" {
		details["issueId"] = event.IssueID
	}
	payload := CustomEventRequest{
		EventType: "klaudia-rca-triggered",
		Summary:   truncate(firstNonEmpty(event.Title, event.AlertName, "RCA triggered for "+rca.Name), 100),
		Severity:  komodorEventSeverity(event.Severity),
		Scope: CustomEventScope{
			Clusters:      []string{rca.ClusterName},
			ServicesNames: []string{rca.Name},
			Namespaces:    []string{rca.Namespace},
			Details:       details,
		},
	}
	var response map[string]any
	return s.komodorJSON(ctx, http.MethodPost, "/api/v2/services/k8s-events", payload, &response)
}

func (s *Server) startRCA(ctx context.Context, payload RCARequest) (RCAStartResponse, error) {
	var response RCAStartResponse
	err := s.komodorJSON(ctx, http.MethodPost, "/api/v2/klaudia/rca/sessions", payload, &response)
	if err == nil && response.SessionID == "" {
		return RCAStartResponse{}, errors.New("Komodor response did not include sessionId")
	}
	return response, err
}

func (s *Server) pollRCA(ctx context.Context, sessionID string) (RCAResult, error) {
	delay := s.cfg.PollInitial
	attempt := 0
	for {
		select {
		case <-ctx.Done():
			return RCAResult{}, ctx.Err()
		case <-time.After(delay):
		}

		var result RCAResult
		attempt++
		path := "/api/v2/klaudia/rca/sessions/" + url.PathEscape(sessionID)
		if err := s.komodorJSON(ctx, http.MethodGet, path, nil, &result); err != nil {
			s.audit(ctx, logrus.Fields{"event": "rca_poll_failed", "session_id": sessionID, "attempt": attempt, "next_delay_ms": delay.Milliseconds()}).WithError(err).Warn("RCA poll failed")
		} else {
			s.audit(ctx, logrus.Fields{"event": "rca_polled", "session_id": sessionID, "attempt": attempt, "is_complete": result.IsComplete, "is_stuck": result.IsStuck, "is_failed": result.IsFailed}).Debug("RCA polled")
			if result.IsFailed {
				return result, errors.New("investigation failed")
			}
			if result.IsStuck {
				return result, errors.New("investigation is stuck")
			}
			if result.IsComplete {
				return result, nil
			}
		}
		delay = time.Duration(math.Min(float64(s.cfg.PollMax), float64(delay)*1.5))
	}
}

func (s *Server) komodorJSON(ctx context.Context, method, path string, payload any, result any) error {
	started := time.Now()
	endpoint := komodorEndpoint(path)
	var body io.Reader
	if payload != nil {
		data, err := json.Marshal(payload)
		if err != nil {
			return err
		}
		body = bytes.NewReader(data)
	}
	req, err := http.NewRequestWithContext(ctx, method, s.cfg.KomodorBaseURL+path, body)
	if err != nil {
		return err
	}
	req.Header.Set("X-API-KEY", s.cfg.KomodorAPIKey)
	req.Header.Set("Accept", "application/json")
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	res, err := s.client.Do(req)
	if err != nil {
		s.audit(ctx, logrus.Fields{"event": "komodor_api_call_failed", "provider": "komodor", "endpoint": endpoint, "http_method": method, "duration_ms": time.Since(started).Milliseconds()}).WithError(err).Warn("Komodor API call failed")
		return err
	}
	defer res.Body.Close()
	fields := logrus.Fields{"event": "komodor_api_called", "provider": "komodor", "endpoint": endpoint, "http_method": method, "status_code": res.StatusCode, "duration_ms": time.Since(started).Milliseconds()}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		message, _ := io.ReadAll(io.LimitReader(res.Body, 4096))
		fields["event"] = "komodor_api_call_failed"
		s.audit(ctx, fields).Warn("Komodor API returned error")
		return fmt.Errorf("Komodor returned %s: %s", res.Status, strings.TrimSpace(string(message)))
	}
	if err := json.NewDecoder(res.Body).Decode(result); err != nil {
		fields["event"] = "komodor_response_decode_failed"
		s.audit(ctx, fields).WithError(err).Warn("Komodor API response decode failed")
		return err
	}
	s.audit(ctx, fields).Info("Komodor API call completed")
	return nil
}

func (s *Server) postSlack(ctx context.Context, text, threadTS string) (string, error) {
	started := time.Now()
	mode := "bot"
	messageType := "parent"
	if threadTS != "" {
		messageType = "thread_reply"
	}
	if s.cfg.SlackBotToken == "" || s.cfg.SlackChannel == "" {
		mode = "webhook"
		data, err := json.Marshal(map[string]string{"text": text})
		if err != nil {
			return "", err
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.cfg.SlackWebhookURI, bytes.NewReader(data))
		if err != nil {
			return "", err
		}
		req.Header.Set("Content-Type", "application/json")
		res, err := s.client.Do(req)
		if err != nil {
			s.audit(ctx, logrus.Fields{"event": "slack_post_failed", "slack_mode": mode, "message_type": messageType, "duration_ms": time.Since(started).Milliseconds()}).WithError(err).Warn("Slack post failed")
			return "", err
		}
		defer res.Body.Close()
		if res.StatusCode < 200 || res.StatusCode >= 300 {
			message, _ := io.ReadAll(io.LimitReader(res.Body, 4096))
			s.audit(ctx, logrus.Fields{"event": "slack_post_failed", "slack_mode": mode, "message_type": messageType, "status_code": res.StatusCode, "duration_ms": time.Since(started).Milliseconds()}).Warn("Slack post failed")
			return "", fmt.Errorf("Slack webhook returned %s: %s", res.Status, strings.TrimSpace(string(message)))
		}
		s.audit(ctx, logrus.Fields{"event": "slack_posted", "slack_mode": mode, "message_type": messageType, "status_code": res.StatusCode, "duration_ms": time.Since(started).Milliseconds()}).Info("Slack message posted")
		return "", nil
	}

	payload := map[string]any{
		"channel":      s.cfg.SlackChannel,
		"text":         text,
		"unfurl_links": false,
		"unfurl_media": false,
	}
	if threadTS != "" {
		payload["thread_ts"] = threadTS
	}
	data, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.cfg.SlackBaseURL+"/chat.postMessage", bytes.NewReader(data))
	if err != nil {
		return "", err
	}
	req.Header.Set("Authorization", "Bearer "+s.cfg.SlackBotToken)
	req.Header.Set("Content-Type", "application/json; charset=utf-8")
	res, err := s.client.Do(req)
	if err != nil {
		s.audit(ctx, logrus.Fields{"event": "slack_post_failed", "slack_mode": mode, "message_type": messageType, "duration_ms": time.Since(started).Milliseconds()}).WithError(err).Warn("Slack post failed")
		return "", err
	}
	defer res.Body.Close()
	var response slackResponse
	if err := json.NewDecoder(res.Body).Decode(&response); err != nil {
		s.audit(ctx, logrus.Fields{"event": "slack_response_decode_failed", "slack_mode": mode, "message_type": messageType, "status_code": res.StatusCode, "duration_ms": time.Since(started).Milliseconds()}).WithError(err).Warn("Slack response decode failed")
		return "", err
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 || !response.OK {
		s.audit(ctx, logrus.Fields{"event": "slack_post_failed", "slack_mode": mode, "message_type": messageType, "status_code": res.StatusCode, "duration_ms": time.Since(started).Milliseconds(), "slack_error": response.Error}).Warn("Slack post failed")
		return "", fmt.Errorf("Slack returned %s: %s", res.Status, response.Error)
	}
	s.audit(ctx, logrus.Fields{"event": "slack_posted", "slack_mode": mode, "message_type": messageType, "status_code": res.StatusCode, "duration_ms": time.Since(started).Milliseconds()}).Info("Slack message posted")
	return response.TS, nil
}

func (s *Server) finishSlackReaction(ctx context.Context, log *logrus.Entry, messageTS, finalReaction string) {
	if messageTS == "" {
		return
	}
	if err := s.slackReaction(ctx, "remove", "hourglass_flowing_sand", messageTS); err != nil {
		log.WithError(err).WithField("event", "slack_loading_reaction_remove_failed").Warn("Slack loading reaction removal failed")
	}
	if err := s.slackReaction(ctx, "add", finalReaction, messageTS); err != nil {
		log.WithError(err).WithFields(logrus.Fields{"event": "slack_final_reaction_failed", "reaction": finalReaction}).Warn("Slack final reaction failed")
	}
}

func (s *Server) slackReaction(ctx context.Context, action, reaction, messageTS string) error {
	started := time.Now()
	payload := map[string]string{
		"channel":   s.cfg.SlackChannel,
		"name":      reaction,
		"timestamp": messageTS,
	}
	data, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.cfg.SlackBaseURL+"/reactions."+action, bytes.NewReader(data))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+s.cfg.SlackBotToken)
	req.Header.Set("Content-Type", "application/json; charset=utf-8")
	res, err := s.client.Do(req)
	if err != nil {
		s.audit(ctx, logrus.Fields{"event": "slack_reaction_failed", "reaction_action": action, "reaction": reaction, "duration_ms": time.Since(started).Milliseconds()}).WithError(err).Warn("Slack reaction failed")
		return err
	}
	defer res.Body.Close()
	var response slackResponse
	if err := json.NewDecoder(res.Body).Decode(&response); err != nil {
		return err
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 || !response.OK {
		return fmt.Errorf("Slack reactions.%s returned %s: %s", action, res.Status, response.Error)
	}
	s.audit(ctx, logrus.Fields{"event": "slack_reaction_updated", "reaction_action": action, "reaction": reaction, "status_code": res.StatusCode, "duration_ms": time.Since(started).Milliseconds()}).Info("Slack reaction updated")
	return nil
}

func summaryMessage(event WebhookEvent, rca RCARequest, result RCAResult) string {
	state := "Complete"
	if result.IsFailed {
		state = "Failed"
	} else if result.IsStuck {
		state = "Stuck"
	}
	title := firstNonEmpty(event.Title, event.AlertName, "Webhook event")
	problem := firstNonEmpty(result.ProblemShort, "No root-cause summary was returned")
	severity := ""
	if event.Severity != "" {
		severity = "\n*Severity:* `" + event.Severity + "`"
	}
	return fmt.Sprintf("*Komodor RCA: %s* — %s\n*Resource:* `%s/%s` in `%s` (`%s`)%s\n*Root cause:* %s\n<%s|Open RCA session>",
		state, title, rca.Kind, rca.Name, rca.Namespace, rca.ClusterName, severity, problem, result.SessionURL)
}

func detailMessages(event WebhookEvent, result RCAResult) []string {
	var messages []string
	if len(event.Metadata) > 0 {
		var metadata []string
		for key, value := range metadataStrings(event.Metadata) {
			metadata = append(metadata, fmt.Sprintf("• `%s`: %s", key, value))
		}
		sort.Strings(metadata)
		messages = append(messages, "*Event metadata*\n"+strings.Join(metadata, "\n"))
	}
	if result.Classification != "" {
		messages = append(messages, "*Classification*\n"+result.Classification)
	}
	if len(result.WhatHappened) > 0 {
		messages = append(messages, "*What happened*\n"+bulletList(result.WhatHappened))
	}
	if result.Remediation != nil {
		r := result.Remediation
		var sections []string
		if r.Recommendation != "" {
			sections = append(sections, "*Recommendation*\n"+r.Recommendation)
		}
		if r.Reasoning != "" {
			sections = append(sections, "*Reasoning*\n"+r.Reasoning)
		}
		if r.RawCommand != "" {
			sections = append(sections, "*Suggested command*\n```"+r.RawCommand+"```")
		}
		if r.LongTermRemediation != "" {
			sections = append(sections, "*Long-term remediation*\n"+r.LongTermRemediation)
		}
		if len(sections) > 0 {
			messages = append(messages, strings.Join(sections, "\n\n"))
		}
	} else if result.Recommendation != "" {
		messages = append(messages, "*Recommendation*\n"+result.Recommendation)
	}
	if len(result.EvidenceCollection) > 0 {
		var evidence []string
		for _, item := range result.EvidenceCollection {
			evidence = append(evidence, "• "+firstNonEmpty(item.Snippet, item.Query))
		}
		messages = append(messages, "*Evidence*\n"+strings.Join(evidence, "\n"))
	}
	if len(result.Operations) > 0 {
		messages = append(messages, "*Investigation operations*\n"+bulletList(result.Operations))
	}
	return messages
}

func failureMessage(event WebhookEvent, rca RCARequest, reason string) string {
	return fmt.Sprintf("*Komodor RCA failed* — %s\n*Resource:* `%s/%s` in `%s` (`%s`)\n%s",
		firstNonEmpty(event.Title, event.AlertName, "Webhook event"), rca.Kind, rca.Name, rca.Namespace, rca.ClusterName, reason)
}

func bulletList(items []string) string {
	return "• " + strings.Join(items, "\n• ")
}

func firstLabel(labels map[string]any, keys ...string) string {
	for _, key := range keys {
		if value, ok := labels[key]; ok {
			switch typed := value.(type) {
			case string:
				if typed != "" {
					return typed
				}
			case json.Number:
				return typed.String()
			case float64:
				return strconv.FormatFloat(typed, 'f', -1, 64)
			}
		}
	}
	return ""
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

func metadataStrings(metadata map[string]any) map[string]string {
	result := make(map[string]string, len(metadata)+2)
	for key, value := range metadata {
		switch typed := value.(type) {
		case string:
			result[key] = truncate(typed, 1000)
		default:
			data, err := json.Marshal(typed)
			if err == nil {
				result[key] = truncate(string(data), 1000)
			}
		}
	}
	return result
}

func komodorEventSeverity(severity string) string {
	switch strings.ToLower(severity) {
	case "critical", "high", "error":
		return "error"
	case "medium", "warning", "warn":
		return "warning"
	default:
		return "information"
	}
}

func truncate(value string, max int) string {
	if len(value) <= max {
		return value
	}
	return value[:max]
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func env(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func durationEnv(key string, fallback time.Duration) time.Duration {
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

func boolEnv(key string, fallback bool) bool {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseBool(value)
	if err != nil {
		return fallback
	}
	return parsed
}

func newLogger(level string) *logrus.Logger {
	logger := logrus.New()
	logger.SetOutput(os.Stdout)
	logger.SetFormatter(&logrus.JSONFormatter{
		TimestampFormat: time.RFC3339Nano,
		FieldMap: logrus.FieldMap{
			logrus.FieldKeyTime:  "timestamp",
			logrus.FieldKeyLevel: "severity",
			logrus.FieldKeyMsg:   "message",
		},
	})
	parsed, err := logrus.ParseLevel(strings.ToLower(level))
	if err != nil {
		parsed = logrus.InfoLevel
	}
	logger.SetLevel(parsed)
	return logger
}

func (s *Server) audit(ctx context.Context, fields logrus.Fields) *logrus.Entry {
	fields["service"] = "webhook-komodor-rca"
	if requestID, ok := ctx.Value(requestIDKey).(string); ok && requestID != "" {
		fields["request_id"] = requestID
	}
	return s.logger.WithFields(fields)
}

func eventFields(event WebhookEvent, rca RCARequest) logrus.Fields {
	fields := logrus.Fields{
		"fingerprint":    event.Fingerprint,
		"issue_id":       event.IssueID,
		"event_status":   event.Status,
		"event_severity": event.Severity,
		"metadata_count": len(event.Metadata),
		"resource_kind":  rca.Kind,
		"resource_name":  rca.Name,
		"namespace":      rca.Namespace,
		"cluster_name":   rca.ClusterName,
	}
	for key, value := range fields {
		if value == "" {
			delete(fields, key)
		}
	}
	return fields
}

func newRequestID() string {
	value := make([]byte, 16)
	if _, err := rand.Read(value); err != nil {
		return strconv.FormatInt(time.Now().UnixNano(), 36)
	}
	return fmt.Sprintf("%x", value)
}

func remoteIP(r *http.Request) string {
	if forwarded := strings.TrimSpace(strings.Split(r.Header.Get("X-Forwarded-For"), ",")[0]); forwarded != "" {
		return forwarded
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err == nil {
		return host
	}
	return r.RemoteAddr
}

func komodorEndpoint(path string) string {
	if strings.HasPrefix(path, "/api/v2/klaudia/rca/sessions/") {
		return "get_rca_session"
	}
	switch path {
	case "/api/v2/klaudia/rca/sessions":
		return "create_rca_session"
	case "/api/v2/services/k8s-events":
		return "create_custom_event"
	default:
		return "unknown"
	}
}

func statusSet(raw string) map[string]bool {
	statuses := make(map[string]bool)
	for _, status := range strings.Split(raw, ",") {
		statuses[strings.ToLower(strings.TrimSpace(status))] = true
	}
	return statuses
}

func setKeys(values map[string]bool) []string {
	keys := make([]string, 0, len(values))
	for key, enabled := range values {
		if enabled {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	return keys
}
