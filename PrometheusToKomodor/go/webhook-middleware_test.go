package main

import "testing"

func TestBuildKomodorEventMissingCluster(t *testing.T) {
	alert := AlertmanagerAlert{
		Status: "firing",
		Labels: map[string]string{
			"alertname": "HighErrorRate",
		},
	}

	_, err := buildKomodorEvent(alert)
	if err == nil {
		t.Fatal("expected error when cluster label is missing")
	}
}

func TestBuildKomodorEventMapsExpectedFields(t *testing.T) {
	alert := AlertmanagerAlert{
		Status: "firing",
		Labels: map[string]string{
			"alertname":              "VeryLongAlertNameThatShouldBeTruncatedAtThirtyCharacters",
			"cluster":                "prod-eks-01",
			"kubernetes_namespace":   "payments",
			"app_kubernetes_io_name": "checkout-api",
			"severity":               "warning",
		},
		Annotations: map[string]string{
			"description": "checkout api is reporting elevated errors",
		},
		StartsAt:     "2026-05-08T12:00:00Z",
		EndsAt:       "2026-05-08T12:10:00Z",
		GeneratorURL: "http://prometheus.example/graph",
		Fingerprint:  "abc123",
	}

	event, err := buildKomodorEvent(alert)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if event.EventType != "VeryLongAlertNameThatShouldBeT" {
		t.Fatalf("unexpected event type: %q", event.EventType)
	}

	if event.Summary != "checkout api is reporting elevated errors" {
		t.Fatalf("unexpected summary: %q", event.Summary)
	}

	if event.Severity != "warning" {
		t.Fatalf("unexpected severity: %q", event.Severity)
	}

	if len(event.Scope.Clusters) != 1 || event.Scope.Clusters[0] != "prod-eks-01" {
		t.Fatalf("unexpected clusters scope: %#v", event.Scope.Clusters)
	}

	if len(event.Scope.Namespaces) != 1 || event.Scope.Namespaces[0] != "payments" {
		t.Fatalf("unexpected namespaces scope: %#v", event.Scope.Namespaces)
	}

	if len(event.Scope.ServicesNames) != 1 || event.Scope.ServicesNames[0] != "checkout-api" {
		t.Fatalf("unexpected services scope: %#v", event.Scope.ServicesNames)
	}

	if event.Details["label_cluster"] != "prod-eks-01" {
		t.Fatalf("expected label_cluster in details, got: %#v", event.Details)
	}

	if event.Details["annotation_description"] != "checkout api is reporting elevated errors" {
		t.Fatalf("expected annotation_description in details, got: %#v", event.Details)
	}
}

func TestMapSeverity(t *testing.T) {
	testCases := []struct {
		name     string
		severity string
		status   string
		expect   string
	}{
		{name: "resolved always information", severity: "critical", status: "resolved", expect: "information"},
		{name: "critical maps to error", severity: "critical", status: "firing", expect: "error"},
		{name: "warn maps to warning", severity: "warn", status: "firing", expect: "warning"},
		{name: "default maps to information", severity: "note", status: "firing", expect: "information"},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			got := mapSeverity(tc.severity, tc.status)
			if got != tc.expect {
				t.Fatalf("mapSeverity(%q, %q) = %q, want %q", tc.severity, tc.status, got, tc.expect)
			}
		})
	}
}
