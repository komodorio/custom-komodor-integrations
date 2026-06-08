package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"syscall"
	"time"

	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/secretsmanager"
	"github.com/sirupsen/logrus"
)

type secretMapping struct {
	arnEnv  string
	fileEnv string
	name    string
}

func main() {
	logrus.SetFormatter(&logrus.JSONFormatter{TimestampFormat: time.RFC3339Nano})
	if level, err := logrus.ParseLevel(os.Getenv("LOG_LEVEL")); err == nil {
		logrus.SetLevel(level)
	}
	if len(os.Args) < 2 {
		fatal(errors.New("usage: aws-secret-init command [args...]"))
	}

	ctx := context.Background()
	cfg, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		fatal(fmt.Errorf("load AWS configuration: %w", err))
	}
	client := secretsmanager.NewFromConfig(cfg)

	dir := "/tmp/secrets"
	if err := os.MkdirAll(dir, 0o700); err != nil {
		fatal(fmt.Errorf("create secrets directory: %w", err))
	}

	mappings := []secretMapping{
		{arnEnv: "KOMODOR_API_KEY_SECRET_ARN", fileEnv: "KOMODOR_API_KEY_FILE", name: "komodor-api-key"},
		{arnEnv: "SLACK_WEBHOOK_URI_SECRET_ARN", fileEnv: "SLACK_WEBHOOK_URI_FILE", name: "slack-webhook-uri"},
		{arnEnv: "SLACK_BOT_TOKEN_SECRET_ARN", fileEnv: "SLACK_BOT_TOKEN_FILE", name: "slack-bot-token"},
		{arnEnv: "WEBHOOK_TOKEN_SECRET_ARN", fileEnv: "WEBHOOK_TOKEN_FILE", name: "webhook-token"},
	}
	for _, mapping := range mappings {
		arn := os.Getenv(mapping.arnEnv)
		if arn == "" {
			continue
		}
		result, err := client.GetSecretValue(ctx, &secretsmanager.GetSecretValueInput{SecretId: &arn})
		if err != nil {
			fatal(fmt.Errorf("fetch %s: %w", mapping.arnEnv, err))
		}
		if result.SecretString == nil {
			fatal(fmt.Errorf("%s must contain a string secret", mapping.arnEnv))
		}
		path := filepath.Join(dir, mapping.name)
		if err := os.WriteFile(path, []byte(*result.SecretString), 0o600); err != nil {
			fatal(fmt.Errorf("write %s: %w", mapping.fileEnv, err))
		}
		if err := os.Setenv(mapping.fileEnv, path); err != nil {
			fatal(fmt.Errorf("set %s: %w", mapping.fileEnv, err))
		}
		logrus.WithFields(logrus.Fields{"event": "secret_materialized", "secret_reference_env": mapping.arnEnv, "secret_file_env": mapping.fileEnv}).Info("secret materialized")
	}

	logrus.WithField("event", "application_starting").Info("application starting")
	command, err := filepath.Abs(os.Args[1])
	if err != nil {
		fatal(err)
	}
	if err := syscall.Exec(command, os.Args[1:], os.Environ()); err != nil {
		fatal(fmt.Errorf("start application: %w", err))
	}
}

func fatal(err error) {
	logrus.WithError(err).WithField("event", "bootstrap_failed").Error("bootstrap failed")
	os.Exit(1)
}
