package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/sirupsen/logrus"
)

func TestRCARequestFromNestedWebhookAlert(t *testing.T) {
	event := normalizeEvent(WebhookEvent{
		Alert: &WebhookAlert{
			Kind:    "StatefulSet",
			IssueID: "issue-123",
			Labels: map[string]any{
				"workload_name": "payments",
				"namespace":     "production",
				"clusterId":     "prod-eu",
			},
		},
	})

	got, err := rcaRequestFromEvent(event, "Deployment")
	if err != nil {
		t.Fatal(err)
	}
	if got.Kind != "StatefulSet" || got.Name != "payments" || got.Namespace != "production" || got.ClusterName != "prod-eu" {
		t.Fatalf("unexpected request: %+v", got)
	}
	if got.IssueID == nil || *got.IssueID != "issue-123" {
		t.Fatalf("unexpected issue ID: %+v", got.IssueID)
	}
}

func TestHandleWebhookRejectsMissingResourceFields(t *testing.T) {
	server := testServer(Config{DefaultKind: "Deployment", ProcessStatuses: statusSet("firing")})
	req := httptest.NewRequest(http.MethodPost, "/webhooks/groundcover", strings.NewReader(`{"alert":{"status":"firing","labels":{"namespace":"prod"}}}`))
	res := httptest.NewRecorder()

	server.handleWebhook(res, req)

	if res.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected 422, got %d: %s", res.Code, res.Body.String())
	}
}

func TestHandleWebhookIgnoresResolved(t *testing.T) {
	server := testServer(Config{DefaultKind: "Deployment", ProcessStatuses: statusSet("firing")})
	req := httptest.NewRequest(http.MethodPost, "/webhooks/groundcover", strings.NewReader(`{"alert":{"status":"resolved","labels":{"workload":"api","namespace":"prod","cluster":"main"}}}`))
	res := httptest.NewRecorder()

	server.handleWebhook(res, req)

	if res.Code != http.StatusAccepted || !strings.Contains(res.Body.String(), "ignored") {
		t.Fatalf("expected ignored 202, got %d: %s", res.Code, res.Body.String())
	}
}

func TestHandleWebhookIgnoresNonCriticalSeverity(t *testing.T) {
	server := testServer(Config{
		DefaultKind:       "Deployment",
		ProcessStatuses:   statusSet("firing"),
		ProcessSeverities: statusSet("critical"),
	})
	req := httptest.NewRequest(http.MethodPost, "/webhooks/rca", strings.NewReader(`{"status":"firing","severity":"warning","resource":{"kind":"Deployment","name":"api","namespace":"prod","clusterName":"main"}}`))
	res := httptest.NewRecorder()

	server.handleWebhook(res, req)

	if res.Code != http.StatusAccepted || !strings.Contains(res.Body.String(), "severity") {
		t.Fatalf("expected severity-filtered 202, got %d: %s", res.Code, res.Body.String())
	}
}

func TestWebhookTokenAuthentication(t *testing.T) {
	server := testServer(Config{WebhookToken: "expected-token"})

	unauthorized := httptest.NewRequest(http.MethodPost, "/webhooks/rca", nil)
	if server.authorized(unauthorized) {
		t.Fatal("expected request without token to be unauthorized")
	}

	authorized := httptest.NewRequest(http.MethodPost, "/webhooks/rca", nil)
	authorized.Header.Set("Authorization", "Bearer expected-token")
	if !server.authorized(authorized) {
		t.Fatal("expected bearer token to be authorized")
	}
}

func TestWebhookAuditLogIsStructuredAndPropagatesRequestID(t *testing.T) {
	var logs bytes.Buffer
	logger := newLogger("info")
	logger.SetOutput(&logs)
	server := testServer(Config{
		DefaultKind:       "Deployment",
		ProcessStatuses:   statusSet("firing"),
		ProcessSeverities: statusSet("critical"),
	})
	server.logger = logger

	req := httptest.NewRequest(http.MethodPost, "/webhooks/rca", strings.NewReader(`{"status":"firing","severity":"warning","resource":{"kind":"Deployment","name":"api","namespace":"prod","clusterName":"main"}}`))
	req.Header.Set("X-Request-ID", "audit-test-123")
	res := httptest.NewRecorder()
	server.handleWebhook(res, req)

	if res.Header().Get("X-Request-ID") != "audit-test-123" {
		t.Fatalf("request ID was not returned: %q", res.Header().Get("X-Request-ID"))
	}
	if !strings.Contains(logs.String(), `"event":"webhook_ignored"`) || !strings.Contains(logs.String(), `"request_id":"audit-test-123"`) {
		t.Fatalf("missing structured audit fields: %s", logs.String())
	}
	if strings.Contains(logs.String(), `"resource":{`) {
		t.Fatalf("unexpected full payload in audit log: %s", logs.String())
	}
}

func TestRCARequestFromGenericResource(t *testing.T) {
	event := WebhookEvent{
		Title:   "Checkout failure",
		IssueID: "external-123",
		Resource: &Resource{
			Kind:        "Deployment",
			Name:        "checkout",
			Namespace:   "production",
			ClusterName: "primary",
		},
	}

	got, err := rcaRequestFromEvent(event, "Deployment")
	if err != nil {
		t.Fatal(err)
	}
	if got.Name != "checkout" || got.ClusterName != "primary" || got.IssueID == nil || *got.IssueID != "external-123" {
		t.Fatalf("unexpected request: %+v", got)
	}
}

func TestSynchronousWebhookWaitsForInvestigation(t *testing.T) {
	var slackPosts atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/v2/klaudia/rca/sessions":
			writeJSON(w, http.StatusOK, RCAStartResponse{SessionID: "session-1", SessionURL: "https://komodor/session-1"})
		case r.URL.Path == "/api/v2/klaudia/rca/sessions/session-1":
			writeJSON(w, http.StatusOK, RCAResult{IsComplete: true, SessionURL: "https://komodor/session-1"})
		default:
			slackPosts.Add(1)
			w.WriteHeader(http.StatusOK)
		}
	}))
	defer upstream.Close()

	server := testServer(Config{
		KomodorBaseURL:   upstream.URL,
		SlackWebhookURI:  upstream.URL + "/slack",
		DefaultKind:      "Deployment",
		ProcessStatuses:  statusSet("firing"),
		Synchronous:      true,
		PollInitial:      time.Millisecond,
		PollMax:          time.Millisecond,
		InvestigationTTL: time.Second,
	})
	req := httptest.NewRequest(http.MethodPost, "/webhooks/rca", strings.NewReader(`{"resource":{"kind":"Deployment","name":"api","namespace":"prod","clusterName":"main"}}`))
	res := httptest.NewRecorder()

	server.handleWebhook(res, req)

	if res.Code != http.StatusOK || slackPosts.Load() != 1 {
		t.Fatalf("expected completed synchronous request, got status %d and %d Slack posts", res.Code, slackPosts.Load())
	}
}

func TestEndToEndInvestigationPostsSummaryThenThread(t *testing.T) {
	var polls atomic.Int32
	var slackPosts atomic.Int32
	var loadingAdded atomic.Bool
	var loadingRemoved atomic.Bool
	var completeAdded atomic.Bool
	done := make(chan struct{})

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/v2/klaudia/rca/sessions" && r.Method == http.MethodPost:
			if r.Header.Get("X-API-KEY") != "komodor-key" {
				t.Error("missing Komodor API key")
			}
			body, _ := io.ReadAll(r.Body)
			if !strings.Contains(string(body), `"clusterName":"main"`) {
				t.Errorf("unexpected RCA request: %s", body)
			}
			writeJSON(w, http.StatusOK, RCAStartResponse{SessionID: "session-1", SessionURL: "https://komodor/session-1"})
		case r.URL.Path == "/api/v2/klaudia/rca/sessions/session-1":
			count := polls.Add(1)
			writeJSON(w, http.StatusOK, RCAResult{
				SessionID:    "session-1",
				SessionURL:   "https://komodor/session-1",
				IsComplete:   count >= 2,
				ProblemShort: "bad rollout",
				WhatHappened: []string{"deployment changed", "pods crashed"},
				Remediation:  &Remediation{Recommendation: "roll back"},
			})
		case r.URL.Path == "/api/chat.postMessage":
			var payload map[string]any
			_ = json.NewDecoder(r.Body).Decode(&payload)
			count := slackPosts.Add(1)
			if count == 1 {
				if _, ok := payload["thread_ts"]; ok {
					t.Error("summary unexpectedly posted in a thread")
				}
				if !strings.Contains(payload["text"].(string), "RCA triggered") {
					t.Errorf("first message was not the initial RCA message: %+v", payload)
				}
			} else if payload["thread_ts"] != "123.456" {
				t.Errorf("detail missing thread_ts: %+v", payload)
			}
			writeJSON(w, http.StatusOK, slackResponse{OK: true, TS: "123.456"})
		case r.URL.Path == "/api/reactions.add" || r.URL.Path == "/api/reactions.remove":
			var payload map[string]string
			_ = json.NewDecoder(r.Body).Decode(&payload)
			switch {
			case r.URL.Path == "/api/reactions.add" && payload["name"] == "hourglass_flowing_sand":
				loadingAdded.Store(true)
			case r.URL.Path == "/api/reactions.remove" && payload["name"] == "hourglass_flowing_sand":
				loadingRemoved.Store(true)
			case r.URL.Path == "/api/reactions.add" && payload["name"] == "white_check_mark":
				completeAdded.Store(true)
				close(done)
			}
			writeJSON(w, http.StatusOK, slackResponse{OK: true})
		default:
			http.NotFound(w, r)
		}
	}))
	defer upstream.Close()

	server := testServer(Config{
		KomodorBaseURL:   upstream.URL,
		KomodorAPIKey:    "komodor-key",
		SlackBaseURL:     upstream.URL + "/api",
		SlackBotToken:    "slack-token",
		SlackChannel:     "C123",
		DefaultKind:      "Deployment",
		ProcessStatuses:  statusSet("firing"),
		PollInitial:      time.Millisecond,
		PollMax:          2 * time.Millisecond,
		InvestigationTTL: time.Second,
	})
	event := WebhookEvent{AlertName: "Pods crashed"}
	rca := RCARequest{Kind: "Deployment", Name: "api", Namespace: "prod", ClusterName: "main"}

	go server.investigate(context.Background(), event, rca)

	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for Slack posts")
	}
	if polls.Load() != 2 {
		t.Fatalf("expected 2 polls, got %d", polls.Load())
	}
	if !loadingAdded.Load() || !loadingRemoved.Load() || !completeAdded.Load() {
		t.Fatalf("unexpected reaction lifecycle: loading added=%v removed=%v complete=%v", loadingAdded.Load(), loadingRemoved.Load(), completeAdded.Load())
	}
}

func testServer(cfg Config) *Server {
	return &Server{
		cfg:    cfg,
		client: &http.Client{Timeout: time.Second},
		logger: func() *logrus.Logger {
			logger := logrus.New()
			logger.SetOutput(io.Discard)
			return logger
		}(),
	}
}

func TestPollStopsWhenInvestigationIsStuck(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, RCAResult{IsStuck: true})
	}))
	defer upstream.Close()
	server := testServer(Config{
		KomodorBaseURL:   upstream.URL,
		PollInitial:      time.Millisecond,
		PollMax:          time.Millisecond,
		InvestigationTTL: time.Second,
	})

	_, err := server.pollRCA(context.Background(), "stuck")
	if err == nil || !strings.Contains(err.Error(), "stuck") {
		t.Fatalf("expected stuck error, got %v", err)
	}
}

func TestPostSlackWebhook(t *testing.T) {
	var body string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		data, _ := io.ReadAll(r.Body)
		body = string(data)
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()

	server := testServer(Config{SlackWebhookURI: upstream.URL})
	if _, err := server.postSlack(context.Background(), "RCA complete", "ignored-thread"); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(body, "RCA complete") {
		t.Fatalf("unexpected webhook body: %s", body)
	}
}

func TestPublishRCAStartedCustomEventIncludesMetadata(t *testing.T) {
	var payload CustomEventRequest
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v2/services/k8s-events" {
			http.NotFound(w, r)
			return
		}
		_ = json.NewDecoder(r.Body).Decode(&payload)
		writeJSON(w, http.StatusCreated, map[string]string{"id": "event-1"})
	}))
	defer upstream.Close()

	server := testServer(Config{KomodorBaseURL: upstream.URL, KomodorAPIKey: "key"})
	event := WebhookEvent{
		Title:       "Production API unavailable",
		Severity:    "critical",
		Fingerprint: "fp-1",
		Metadata:    map[string]any{"source": "monitor", "attempt": float64(2)},
	}
	rca := RCARequest{Kind: "Deployment", Name: "api", Namespace: "prod", ClusterName: "main"}

	err := server.publishRCAStartedEvent(context.Background(), event, rca, RCAStartResponse{
		SessionID:  "session-1",
		SessionURL: "https://komodor/session-1",
	})
	if err != nil {
		t.Fatal(err)
	}
	if payload.Severity != "error" || payload.Scope.Details["source"] != "monitor" || payload.Scope.Details["rcaSessionId"] != "session-1" {
		t.Fatalf("unexpected custom event: %+v", payload)
	}
}

func TestSecretValueReadsFileAndPrefersEnvironment(t *testing.T) {
	path := t.TempDir() + "/secret"
	if err := os.WriteFile(path, []byte("from-file\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("TEST_SECRET_FILE", path)

	got, err := secretValue("TEST_SECRET")
	if err != nil || got != "from-file" {
		t.Fatalf("expected file secret, got %q, %v", got, err)
	}

	t.Setenv("TEST_SECRET", "from-env")
	got, err = secretValue("TEST_SECRET")
	if err != nil || got != "from-env" {
		t.Fatalf("expected environment secret, got %q, %v", got, err)
	}
}
