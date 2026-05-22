package main

import (
	"testing"

	"github.com/go-jose/go-jose/v4/testutils/assert"
	"github.com/go-jose/go-jose/v4/testutils/require"
)

func TestBuildKomodorEventMissingCluster(t *testing.T) {
	alert := AlertmanagerAlert{
		Status: "firing",
		Labels: map[string]string{
			"alertname": "HighErrorRate",
		},
	}

	_, err := buildKomodorEvent(alert)
	assert.Error(t, err)
}

func TestBuildKomodorEventConflictingLabelAnnotations(t *testing.T) {
	alert := AlertmanagerAlert{
		Status: "firing",
		Labels: map[string]string{
			"alertname": "HighErrorRate",
			"cluster":   "prod-eks-01",
			"severity":  "critical",
		},
		Annotations: map[string]string{
			"cluster":     "annotation-cluster-value",
			"severity":    "warning", // This should not overwrite the label value.
			"description": "Errors are above 5%",
		},
	}

	event, err := buildKomodorEvent(alert)
	require.NoError(t, err)

	assert.Equal(t, event.Details["cluster"], alert.Labels["cluster"])
	assert.Equal(t, event.Details["annotation_cluster"], alert.Annotations["cluster"])
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
	require.NoError(t, err)

	assert.Equal(t, event.EventType, "VeryLongAlertNameThatShouldBeT")

	// if event.EventType != "VeryLongAlertNameThatShouldBeT" {
	// 	t.Fatalf("unexpected event type: %q", event.EventType)
	// }
	assert.Equal(t, event.Summary, "checkout api is reporting elevated errors")
	assert.Equal(t, event.Severity, "warning")

	// Scope
	assert.Len(t, event.Scope.Clusters, 1)
	assert.Len(t, event.Scope.Namespaces, 1)
	assert.Len(t, event.Scope.ServicesNames, 1)
	assert.Equal(t, event.Scope.Clusters[0], "prod-eks-01")
	assert.Equal(t, event.Scope.Namespaces[0], "payments")
	assert.Equal(t, event.Scope.ServicesNames[0], "checkout-api")

	assert.Equal(t, event.Details["cluster"], "prod-eks-01")
	assert.Equal(t, event.Details["description"], "checkout api is reporting elevated errors")
	assert.Equal(t, event.Details["generator_url"], "http://prometheus.example/graph")
	assert.Equal(t, event.Details["starts_at"], "08 May 26 12:00 UTC")
	assert.Equal(t, event.Details["ends_at"], "08 May 26 12:10 UTC")
	assert.Equal(t, event.Details["fingerprint"], "abc123")
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
