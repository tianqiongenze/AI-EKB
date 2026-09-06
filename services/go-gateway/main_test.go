package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sync"
	"testing"
	"time"
)

type stubEventAdapter struct{}

func (stubEventAdapter) PublishBatch(ctx context.Context, topic string, payloads []map[string]any) error {
	_ = ctx
	_ = topic
	_ = payloads
	return nil
}

type stubCapabilityAdapter struct{}

func (stubCapabilityAdapter) EvaluatePolicy(ctx context.Context, tenant string, region string, action string) (bool, error) {
	_ = ctx
	_ = tenant
	_ = region
	_ = action
	return true, nil
}

func (stubCapabilityAdapter) AggregateInsights(ctx context.Context, tenant string, query string) error {
	_ = ctx
	_ = tenant
	_ = query
	return nil
}

func (stubCapabilityAdapter) GovernanceDecision(ctx context.Context, tenant string, region string, action string) error {
	_ = ctx
	_ = tenant
	_ = region
	_ = action
	return nil
}

func (stubCapabilityAdapter) Mode() string { return "stub" }

type failingEventAdapter struct {
	mu             sync.Mutex
	failuresBefore int
	calls          int
}

func (adapter *failingEventAdapter) PublishBatch(ctx context.Context, topic string, payloads []map[string]any) error {
	_ = ctx
	_ = topic
	_ = payloads
	adapter.mu.Lock()
	defer adapter.mu.Unlock()
	adapter.calls++
	if adapter.calls <= adapter.failuresBefore {
		return errors.New("temporary_error")
	}
	return nil
}

type failingCacheAdapter struct{}

func (failingCacheAdapter) GetMany(ctx context.Context, keys []string) (map[string]string, error) {
	_ = ctx
	_ = keys
	return nil, errors.New("cache_error")
}

func (failingCacheAdapter) SetManyWithTTL(ctx context.Context, items map[string]string, ttl time.Duration) error {
	_ = ctx
	_ = items
	_ = ttl
	return errors.New("cache_error")
}

type mockCapabilityAdapter struct {
	allowPolicy bool
	policyErr   error
	aggErr      error
	govErr      error
}

func (adapter *mockCapabilityAdapter) Mode() string {
	return "mock"
}

func (adapter *mockCapabilityAdapter) EvaluatePolicy(ctx context.Context, tenant string, region string, action string) (bool, error) {
	_ = ctx
	_ = tenant
	_ = region
	_ = action
	if adapter.policyErr != nil {
		return false, adapter.policyErr
	}
	return adapter.allowPolicy, nil
}

func (adapter *mockCapabilityAdapter) AggregateInsights(ctx context.Context, tenant string, query string) error {
	_ = ctx
	_ = tenant
	_ = query
	return adapter.aggErr
}

func (adapter *mockCapabilityAdapter) GovernanceDecision(ctx context.Context, tenant string, region string, action string) error {
	_ = ctx
	_ = tenant
	_ = region
	_ = action
	return adapter.govErr
}

func newTestServer() GatewayServer {
	config := GatewayRuntimeConfig{
		GlobalRateLimitPerMinute:     100000,
		AuthzRateLimitPerMinute:      100000,
		RouteRateLimitPerMinute:      100000,
		AuthzTimeout:                 120 * time.Millisecond,
		RouteTimeout:                 180 * time.Millisecond,
		RetryMaxAttempts:             2,
		RetryBackoff:                 1 * time.Millisecond,
		MaxInflight:                  100,
		BreakerFailureThreshold:      2,
		BreakerOpenDuration:          1 * time.Second,
		BreakerHalfOpenMaxCalls:      1,
		CanaryPercent:                0,
		PrimaryRoute:                 "python-dialogue-service",
		CanaryRoute:                  "python-dialogue-service-canary",
		TenantRouteLimitsReloadEvery: 30 * time.Second,
		DegradeErrorRatePercent:      5.0,
		DegradeWindow:                60 * time.Second,
		DegradeDuration:              30 * time.Second,
		DegradeMinSamples:            50,
	}
	return GatewayServer{
		name:                "test",
		cache:               NoopCacheAdapter{},
		events:              NewPulsarEventAdapter(),
		graph:               NoopGraphAdapter{},
		vector:              NoopVectorAdapter{},
		config:              config,
		globalLimiter:       NewTokenBucketRateLimiter(config.GlobalRateLimitPerMinute),
		authzLimiter:        NewTokenBucketRateLimiter(config.AuthzRateLimitPerMinute),
		routeLimiter:        NewTokenBucketRateLimiter(config.RouteRateLimitPerMinute),
		authzBreaker:        NewCircuitBreaker("authz", config.BreakerFailureThreshold, config.BreakerOpenDuration, config.BreakerHalfOpenMaxCalls),
		routeBreaker:        NewCircuitBreaker("route", config.BreakerFailureThreshold, config.BreakerOpenDuration, config.BreakerHalfOpenMaxCalls),
		inflightSemaphore:   make(chan struct{}, config.MaxInflight),
		quotaProvider:       NewEnvQuotaProvider(config.TenantRouteLimitsReloadEvery),
		tenantRouteLimiters: map[string]*TokenBucketRateLimiter{},
		errorBudget:         NewErrorBudgetController(config.DegradeErrorRatePercent, config.DegradeWindow, config.DegradeDuration, config.DegradeMinSamples),
	}
}

func TestHealthzHandler(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	w := httptest.NewRecorder()

	handler := newTestServer().routes()
	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
}

func TestAuthzCheckHandler(t *testing.T) {
	server := newTestServer()
	server.config.AuthToken = "token"

	body := bytes.NewBufferString(`{"subject":"user-a"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/authz/check", body)
	req.Header.Set("Authorization", "Bearer token")
	w := httptest.NewRecorder()

	handler := server.routes()
	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var bodyResp map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &bodyResp); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if bodyResp["engine"] != "casbin-compatible" {
		t.Fatalf("expected engine casbin-compatible, got %v", bodyResp["engine"])
	}
}

func TestAuthzUnauthorized(t *testing.T) {
	server := newTestServer()
	server.config.AuthToken = "token"

	body := bytes.NewBufferString(`{"subject":"user-a"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/authz/check", body)
	w := httptest.NewRecorder()

	server.routes().ServeHTTP(w, req)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", w.Code)
	}
}

func TestDialogueRouteHandler(t *testing.T) {
	server := newTestServer()
	server.config.AuthToken = "token"
	body := bytes.NewBufferString(`{"tenant_id":"tenant-a","region_id":"cn-north-1"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/dialogue/route", body)
	req.Header.Set("Authorization", "Bearer token")
	w := httptest.NewRecorder()

	server.routes().ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var bodyResp map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &bodyResp); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if bodyResp["route"] != "python-dialogue-service" {
		t.Fatalf("expected python-dialogue-service route, got %v", bodyResp["route"])
	}
}

func TestAuthzCheckRetryOnEventPublish(t *testing.T) {
	server := newTestServer()
	server.config.AuthToken = "token"
	adapter := &failingEventAdapter{failuresBefore: 1}
	server.events = adapter

	body := bytes.NewBufferString(`{"subject":"user-a"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/authz/check", body)
	req.Header.Set("Authorization", "Bearer token")
	w := httptest.NewRecorder()

	server.routes().ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 after retry, got %d", w.Code)
	}
	if adapter.calls != 2 {
		t.Fatalf("expected 2 calls due to retry, got %d", adapter.calls)
	}
}

func TestAuthzCircuitBreakerOpen(t *testing.T) {
	server := newTestServer()
	server.config.AuthToken = "token"
	server.cache = failingCacheAdapter{}

	body := bytes.NewBufferString(`{"subject":"user-a"}`)

	for i := 0; i < 2; i++ {
		req := httptest.NewRequest(http.MethodPost, "/v1/authz/check", bytes.NewBuffer(body.Bytes()))
		req.Header.Set("Authorization", "Bearer token")
		w := httptest.NewRecorder()
		server.routes().ServeHTTP(w, req)
		if w.Code != http.StatusServiceUnavailable {
			t.Fatalf("expected 503 on cache failure, got %d", w.Code)
		}
	}

	req := httptest.NewRequest(http.MethodPost, "/v1/authz/check", bytes.NewBuffer(body.Bytes()))
	req.Header.Set("Authorization", "Bearer token")
	w := httptest.NewRecorder()
	server.routes().ServeHTTP(w, req)
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503 when breaker open, got %d", w.Code)
	}

	var payload map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &payload); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if payload["error"] != "authz_circuit_open" {
		t.Fatalf("expected authz_circuit_open, got %v", payload["error"])
	}
}

func TestBackpressureMiddleware(t *testing.T) {
	server := newTestServer()
	server.config.AuthToken = "token"
	server.inflightSemaphore = make(chan struct{}, 1)
	server.inflightSemaphore <- struct{}{}

	body := bytes.NewBufferString(`{"subject":"user-a"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/authz/check", body)
	req.Header.Set("Authorization", "Bearer token")
	w := httptest.NewRecorder()

	server.routes().ServeHTTP(w, req)
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503 for overload, got %d", w.Code)
	}

	var payload map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &payload); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if payload["error"] != "gateway_overloaded" {
		t.Fatalf("expected gateway_overloaded, got %v", payload["error"])
	}
}

func TestCanaryRouting(t *testing.T) {
	server := newTestServer()
	server.config.CanaryPercent = 100
	server.config.PrimaryRoute = "primary"
	server.config.CanaryRoute = "canary"
	if route := server.pickRouteForTenant("tenant-a"); route != "canary" {
		t.Fatalf("expected canary route, got %s", route)
	}
}

func TestPolicyDenied(t *testing.T) {
	server := newTestServer()
	server.config.AuthToken = "token"
	server.capability = &mockCapabilityAdapter{allowPolicy: false}

	body := bytes.NewBufferString(`{"tenant_id":"tenant-a","region_id":"cn-north-1"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/dialogue/route", body)
	req.Header.Set("Authorization", "Bearer token")
	w := httptest.NewRecorder()

	server.routes().ServeHTTP(w, req)
	if w.Code != http.StatusForbidden {
		t.Fatalf("expected 403 policy denied, got %d", w.Code)
	}
	if server.routeBreaker.StateCode() != 0 {
		t.Fatalf("expected route breaker closed after policy deny, got %d", server.routeBreaker.StateCode())
	}
}

func TestCapabilityModeMetric(t *testing.T) {
	server := newTestServer()
	server.config.MetricsPath = "/metrics/gateway"
	server.capability = &mockCapabilityAdapter{allowPolicy: true}

	req := httptest.NewRequest(http.MethodGet, "/metrics/gateway", nil)
	w := httptest.NewRecorder()
	server.routes().ServeHTTP(w, req)

	var payload map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &payload); err != nil {
		t.Fatalf("unmarshal metrics: %v", err)
	}
	if payload["gateway_capability_mode"] != "mock" {
		t.Fatalf("expected capability mode mock, got %v", payload["gateway_capability_mode"])
	}
}

func TestGRPCCapabilityAdapterMode(t *testing.T) {
	adapter := &grpcCapabilityAdapter{}
	if adapter.Mode() != "grpc" {
		t.Fatalf("expected grpc mode, got %s", adapter.Mode())
	}
	legacy := &LegacyHTTPCapabilityAdapter{}
	if legacy.Mode() != "http-json" {
		t.Fatalf("expected http-json mode, got %s", legacy.Mode())
	}
}

func TestMetricsEndpoint(t *testing.T) {
	server := newTestServer()
	server.config.MetricsPath = "/metrics/gateway"
	server.canaryHits.Store(9)
	server.primaryHits.Store(91)
	server.degradeHits.Store(3)

	req := httptest.NewRequest(http.MethodGet, "/metrics/gateway", nil)
	w := httptest.NewRecorder()

	server.routes().ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 for metrics, got %d", w.Code)
	}

	var payload map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &payload); err != nil {
		t.Fatalf("unmarshal metrics: %v", err)
	}
	if payload["gateway_canary_hits"] != float64(9) {
		t.Fatalf("expected canary hits 9, got %v", payload["gateway_canary_hits"])
	}
	if payload["gateway_degrade_hits"] != float64(3) {
		t.Fatalf("expected degrade hits 3, got %v", payload["gateway_degrade_hits"])
	}
	if payload["gateway_canary_hit_ratio"] != float64(9)/float64(100) {
		t.Fatalf("expected canary ratio %v, got %v", float64(9)/float64(100), payload["gateway_canary_hit_ratio"])
	}
}

func TestParseBackendRouteMap(t *testing.T) {
	parsed := parseBackendRouteMap("python-dialogue-service=http://localhost:8080,canary=http://localhost:8081")
	if parsed["python-dialogue-service"] != "http://localhost:8080" {
		t.Fatalf("unexpected route map value: %v", parsed)
	}
	if parsed["canary"] != "http://localhost:8081" {
		t.Fatalf("unexpected canary route value: %v", parsed)
	}
}

func TestBuildRouteProxies(t *testing.T) {
	config := GatewayRuntimeConfig{
		BackendRouteMap: map[string]string{
			"python-dialogue-service": "http://localhost:8080",
		},
		ProxyMaxIdleConns:        100,
		ProxyMaxIdleConnsPerHost: 50,
		ProxyMaxConnsPerHost:     0,
		ProxyIdleConnTimeout:     30 * time.Second,
	}
	proxies := buildRouteProxies(config)
	if len(proxies) != 1 {
		t.Fatalf("expected 1 proxy, got %d", len(proxies))
	}
	rp, ok := proxies["python-dialogue-service"]
	if !ok || rp.proxy == nil {
		t.Fatalf("missing proxy for python-dialogue-service")
	}
	if _, err := url.Parse(rp.baseURL); err != nil {
		t.Fatalf("invalid proxy base URL: %v", err)
	}
}

func TestDialogueRouteProxyForwardsBody(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/mcp/invoke" {
			t.Fatalf("expected /mcp/invoke path, got %s", r.URL.Path)
		}
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatalf("decode body: %v", err)
		}
		if body["tenant_id"] != "tenant-a" {
			t.Fatalf("expected tenant-a payload, got %v", body["tenant_id"])
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	defer backend.Close()

	server := newTestServer()
	server.events = stubEventAdapter{}
	server.capability = stubCapabilityAdapter{}
	server.routeProxies = buildRouteProxies(GatewayRuntimeConfig{
		BackendRouteMap:          map[string]string{"python-dialogue-service": backend.URL},
		ProxyMaxIdleConns:        100,
		ProxyMaxIdleConnsPerHost: 50,
		ProxyMaxConnsPerHost:     0,
		ProxyIdleConnTimeout:     30 * time.Second,
	})

	body := bytes.NewBufferString(`{"tenant_id":"tenant-a","region_id":"cn-north-1"}`)
	req := httptest.NewRequest(http.MethodPost, "/v1/dialogue/route", body)
	w := httptest.NewRecorder()

	server.routes().ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("expected proxied 200, got %d", w.Code)
	}
}
