package main

import (
    "context"
    "testing"
    "time"
)

func TestPulsarEventAdapterFallbackBuffer(t *testing.T) {
    adapter := NewPulsarEventAdapter()
    err := adapter.PublishBatch(context.Background(), "persistent://group/control/test", []map[string]any{{"k": "v"}})
    if err != nil {
        t.Fatalf("publish batch failed: %v", err)
    }
}

func TestTokenBucketRateLimiterAllowsTokens(t *testing.T) {
    limiter := NewTokenBucketRateLimiter(60)
    if !limiter.Allow(1) {
        t.Fatalf("expected first token to be allowed")
    }
    time.Sleep(20 * time.Millisecond)
    _ = limiter.Allow(1)
}
