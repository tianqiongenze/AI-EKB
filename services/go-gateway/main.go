package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"hash/fnv"
	"io"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/apache/pulsar-client-go/pulsar"
	"github.com/patrickmn/go-cache"
	"github.com/redis/go-redis/v9"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/protobuf/types/known/structpb"
)

type HealthResponse struct {
	Status string `json:"status"`
	Name   string `json:"name"`
}

type GatewayRuntimeConfig struct {
	AuthToken                    string
	GlobalRateLimitPerMinute     int
	AuthzRateLimitPerMinute      int
	RouteRateLimitPerMinute      int
	AuthzTimeout                 time.Duration
	RouteTimeout                 time.Duration
	RetryMaxAttempts             int
	RetryBackoff                 time.Duration
	MaxInflight                  int
	BreakerFailureThreshold      int
	BreakerOpenDuration          time.Duration
	BreakerHalfOpenMaxCalls      int
	CanaryPercent                int
	PrimaryRoute                 string
	CanaryRoute                  string
	TenantRouteLimitsReloadEvery time.Duration
	DegradeErrorRatePercent      float64
	DegradeWindow                time.Duration
	DegradeDuration              time.Duration
	DegradeMinSamples            int
	MetricsPath                  string
	CapabilityGRPCAddress        string
	CapabilityGRPCTimeout        time.Duration
	BackendRouteMap              map[string]string
	ProxyMaxIdleConns            int
	ProxyMaxIdleConnsPerHost     int
	ProxyMaxConnsPerHost         int
	ProxyIdleConnTimeout         time.Duration
}

type routeProxy struct {
	baseURL string
	proxy   *httputil.ReverseProxy
}

type statusRecorder struct {
	http.ResponseWriter
	statusCode int
}

func (rec *statusRecorder) WriteHeader(statusCode int) {
	rec.statusCode = statusCode
	rec.ResponseWriter.WriteHeader(statusCode)
}

type CacheAdapter interface {
	GetMany(ctx context.Context, keys []string) (map[string]string, error)
	SetManyWithTTL(ctx context.Context, items map[string]string, ttl time.Duration) error
}

type EventAdapter interface {
	PublishBatch(ctx context.Context, topic string, payloads []map[string]any) error
}

type GraphAdapter interface {
	BatchUpsertRelations(ctx context.Context, edges []GraphEdge) error
}

type VectorAdapter interface {
	Search(ctx context.Context, namespace string, vector []float32, topK int) ([]VectorHit, error)
}

type GraphEdge struct {
	Source string `json:"source"`
	Target string `json:"target"`
	Type   string `json:"type"`
}

type VectorHit struct {
	ID    string  `json:"id"`
	Score float32 `json:"score"`
}

type RedisCacheAdapter struct {
	client *redis.Client
}

func NewRedisCacheAdapter(redisURL string) (*RedisCacheAdapter, error) {
	opts, err := redis.ParseURL(redisURL)
	if err != nil {
		return nil, err
	}
	client := redis.NewClient(opts)
	return &RedisCacheAdapter{client: client}, nil
}

func (adapter *RedisCacheAdapter) GetMany(ctx context.Context, keys []string) (map[string]string, error) {
	if len(keys) == 0 {
		return map[string]string{}, nil
	}
	result, err := adapter.client.MGet(ctx, keys...).Result()
	if err != nil {
		return nil, err
	}
	data := make(map[string]string, len(result))
	for idx, item := range result {
		if item == nil {
			continue
		}
		if value, ok := item.(string); ok {
			data[keys[idx]] = value
		}
	}
	return data, nil
}

func (adapter *RedisCacheAdapter) SetManyWithTTL(ctx context.Context, items map[string]string, ttl time.Duration) error {
	pipe := adapter.client.Pipeline()
	for key, value := range items {
		pipe.SetEx(ctx, key, value, ttl)
	}
	_, err := pipe.Exec(ctx)
	return err
}

type PulsarEventAdapter struct {
	buffer    *cache.Cache
	client    pulsar.Client
	producers map[string]pulsar.Producer
	mu        sync.Mutex
	required  bool
}

func NewPulsarEventAdapter() *PulsarEventAdapter {
	required := strings.EqualFold(strings.TrimSpace(os.Getenv("EKB_GATEWAY_PULSAR_REQUIRED")), "true")
	serviceURL := os.Getenv("EKB_PULSAR_SERVICE_URL")
	if serviceURL != "" {
		if client, err := pulsar.NewClient(pulsar.ClientOptions{URL: serviceURL}); err == nil {
			return &PulsarEventAdapter{
				buffer:    cache.New(2*time.Minute, 30*time.Second),
				client:    client,
				producers: map[string]pulsar.Producer{},
				required:  required,
			}
		}
	}
	return &PulsarEventAdapter{
		buffer:    cache.New(2*time.Minute, 30*time.Second),
		producers: map[string]pulsar.Producer{},
		required:  required,
	}
}

func (adapter *PulsarEventAdapter) PublishBatch(ctx context.Context, topic string, payloads []map[string]any) error {
	if adapter.client == nil {
		if adapter.required {
			return errors.New("pulsar_client_unavailable")
		}
		key := "buffer:" + topic
		adapter.buffer.Set(key, payloads, time.Minute)
		return nil
	}

	producer, err := adapter.getOrCreateProducer(topic)
	if err != nil {
		return err
	}

	for _, payload := range payloads {
		data, marshalErr := json.Marshal(payload)
		if marshalErr != nil {
			return marshalErr
		}
		_, sendErr := producer.Send(ctx, &pulsar.ProducerMessage{Payload: data})
		if sendErr != nil {
			return sendErr
		}
	}
	return nil
}

func (adapter *PulsarEventAdapter) getOrCreateProducer(topic string) (pulsar.Producer, error) {
	adapter.mu.Lock()
	defer adapter.mu.Unlock()
	if producer, ok := adapter.producers[topic]; ok {
		return producer, nil
	}
	if adapter.client == nil {
		return nil, errors.New("pulsar_client_unavailable")
	}
	producer, err := adapter.client.CreateProducer(pulsar.ProducerOptions{
		Topic:                   topic,
		BatchingMaxPublishDelay: 20 * time.Millisecond,
		BatchingMaxMessages:     1000,
		DisableBlockIfQueueFull: false,
	})
	if err != nil {
		return nil, err
	}
	adapter.producers[topic] = producer
	return producer, nil
}

type HTTPGraphAdapter struct {
	endpoint  string
	authToken string
	client    *http.Client
}

func NewHTTPGraphAdapter(endpoint string, authToken string, timeout time.Duration) *HTTPGraphAdapter {
	return &HTTPGraphAdapter{
		endpoint:  endpoint,
		authToken: authToken,
		client:    &http.Client{Timeout: timeout},
	}
}

func (adapter *HTTPGraphAdapter) BatchUpsertRelations(ctx context.Context, edges []GraphEdge) error {
	type row struct {
		Source       string `json:"source"`
		Target       string `json:"target"`
		RelationType string `json:"relation_type"`
	}
	payloadRows := make([]row, 0, len(edges))
	for _, edge := range edges {
		payloadRows = append(payloadRows, row{Source: edge.Source, Target: edge.Target, RelationType: edge.Type})
	}
	bodyBytes, err := json.Marshal(map[string]any{"rows": payloadRows})
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, adapter.endpoint, bytes.NewBuffer(bodyBytes))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if adapter.authToken != "" {
		req.Header.Set("Authorization", "Bearer "+adapter.authToken)
	}
	resp, err := adapter.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return errors.New("graph_upsert_failed")
	}
	_, _ = io.Copy(io.Discard, resp.Body)
	return nil
}

type HTTPVectorAdapter struct {
	endpoint  string
	authToken string
	client    *http.Client
}

type CapabilityAdapter interface {
	EvaluatePolicy(ctx context.Context, tenant string, region string, action string) (bool, error)
	AggregateInsights(ctx context.Context, tenant string, query string) error
	GovernanceDecision(ctx context.Context, tenant string, region string, action string) error
	Mode() string
}

type NoopCapabilityAdapter struct{}

func (NoopCapabilityAdapter) EvaluatePolicy(ctx context.Context, tenant string, region string, action string) (bool, error) {
	_ = ctx
	_ = tenant
	_ = region
	_ = action
	return true, nil
}

func (NoopCapabilityAdapter) AggregateInsights(ctx context.Context, tenant string, query string) error {
	_ = ctx
	_ = tenant
	_ = query
	return nil
}

func (NoopCapabilityAdapter) GovernanceDecision(ctx context.Context, tenant string, region string, action string) error {
	_ = ctx
	_ = tenant
	_ = region
	_ = action
	return nil
}

func (NoopCapabilityAdapter) Mode() string {
	return "noop"
}

type LegacyHTTPCapabilityAdapter struct {
	client *ServiceCapabilityClient
}

func NewLegacyHTTPCapabilityAdapter(baseURL string, authToken string, timeout time.Duration) *LegacyHTTPCapabilityAdapter {
	return &LegacyHTTPCapabilityAdapter{client: NewServiceCapabilityClient(baseURL, authToken, timeout)}
}

func (adapter *LegacyHTTPCapabilityAdapter) EvaluatePolicy(ctx context.Context, tenant string, region string, action string) (bool, error) {
	if adapter == nil || adapter.client == nil {
		return true, nil
	}
	return adapter.client.EvaluatePolicy(ctx, tenant, region, action)
}

func (adapter *LegacyHTTPCapabilityAdapter) AggregateInsights(ctx context.Context, tenant string, query string) error {
	if adapter == nil || adapter.client == nil {
		return nil
	}
	return adapter.client.AggregateInsights(ctx, tenant, query)
}

func (adapter *LegacyHTTPCapabilityAdapter) GovernanceDecision(ctx context.Context, tenant string, region string, action string) error {
	if adapter == nil || adapter.client == nil {
		return nil
	}
	return adapter.client.GovernanceDecision(ctx, tenant, region, action)
}

func (adapter *LegacyHTTPCapabilityAdapter) Mode() string {
	return "http-json"
}

type ServiceCapabilityClient struct {
	policyURL     string
	aggregateURL  string
	governanceURL string
	authToken     string
	client        *http.Client
}

type grpcCapabilityAdapter struct {
	conn    *grpc.ClientConn
	timeout time.Duration

	policyMethod     string
	aggregateMethod  string
	governanceMethod string
}

func (adapter *grpcCapabilityAdapter) Mode() string {
	return "grpc"
}

func NewGRPCCapabilityAdapter(address string, timeout time.Duration) (*grpcCapabilityAdapter, error) {
	if strings.TrimSpace(address) == "" {
		return nil, errors.New("grpc_address_empty")
	}
	if timeout <= 0 {
		timeout = 200 * time.Millisecond
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	conn, err := grpc.DialContext(ctx, address, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, err
	}
	return &grpcCapabilityAdapter{
		conn:             conn,
		timeout:          timeout,
		policyMethod:     "/ekb.contracts.CapabilityGatewayService/EvaluatePolicy",
		aggregateMethod:  "/ekb.contracts.CapabilityGatewayService/AggregateInsights",
		governanceMethod: "/ekb.contracts.CapabilityGatewayService/GovernanceDecision",
	}, nil
}

func (adapter *grpcCapabilityAdapter) EvaluatePolicy(ctx context.Context, tenant string, region string, action string) (bool, error) {
	attrs, err := structpb.NewStruct(map[string]any{
		"criticalAsset": false,
		"emergency":     false,
		"operation":     action,
		"region":        region,
	})
	if err != nil {
		return false, err
	}
	request, err := structpb.NewStruct(map[string]any{
		"tenant_id":     tenant,
		"policy_domain": "safety",
		"attributes":    attrs.AsMap(),
	})
	if err != nil {
		return false, err
	}
	resp, err := adapter.invokeStruct(ctx, adapter.policyMethod, request)
	if err != nil {
		return false, err
	}
	allowedValue, ok := resp.AsMap()["allowed"]
	if !ok {
		return false, errors.New("grpc_policy_response_missing_allowed")
	}
	allowed, ok := allowedValue.(bool)
	if !ok {
		return false, errors.New("grpc_policy_response_invalid_allowed")
	}
	return allowed, nil
}

func (adapter *grpcCapabilityAdapter) AggregateInsights(ctx context.Context, tenant string, query string) error {
	request, err := structpb.NewStruct(map[string]any{
		"tenant_id":     tenant,
		"query":         query,
		"evidence_refs": []any{"gateway-route"},
	})
	if err != nil {
		return err
	}
	_, err = adapter.invokeStruct(ctx, adapter.aggregateMethod, request)
	return err
}

func (adapter *grpcCapabilityAdapter) GovernanceDecision(ctx context.Context, tenant string, region string, action string) error {
	request, err := structpb.NewStruct(map[string]any{
		"tenant_id":  tenant,
		"region_id":  region,
		"action":     action,
		"risk_score": 40,
	})
	if err != nil {
		return err
	}
	_, err = adapter.invokeStruct(ctx, adapter.governanceMethod, request)
	return err
}

func (adapter *grpcCapabilityAdapter) invokeStruct(ctx context.Context, method string, request *structpb.Struct) (*structpb.Struct, error) {
	deadlineCtx, cancel := context.WithTimeout(ctx, adapter.timeout)
	defer cancel()
	response := &structpb.Struct{}
	if err := adapter.conn.Invoke(deadlineCtx, method, request, response); err != nil {
		return nil, err
	}
	return response, nil
}

func (adapter *grpcCapabilityAdapter) Close() error {
	if adapter.conn != nil {
		return adapter.conn.Close()
	}
	return nil
}

func NewServiceCapabilityClient(baseURL string, authToken string, timeout time.Duration) *ServiceCapabilityClient {
	base := strings.TrimRight(baseURL, "/")
	return &ServiceCapabilityClient{
		policyURL:     base + "/kgraph/policy/evaluate",
		aggregateURL:  base + "/kgraph/aggregate/insights",
		governanceURL: base + "/kgraph/governance/decision",
		authToken:     authToken,
		client:        &http.Client{Timeout: timeout},
	}
}

func (client *ServiceCapabilityClient) EvaluatePolicy(ctx context.Context, tenant string, region string, action string) (bool, error) {
	payload := map[string]any{
		"tenantId":     tenant,
		"policyDomain": "safety",
		"attributes": map[string]any{
			"criticalAsset": false,
			"emergency":     false,
			"operation":     action,
			"region":        region,
		},
	}
	respBody, err := client.postJSON(ctx, client.policyURL, payload)
	if err != nil {
		return false, err
	}
	var parsed map[string]any
	if err := json.Unmarshal(respBody, &parsed); err != nil {
		return false, err
	}
	allowed, ok := parsed["allowed"].(bool)
	if !ok {
		return false, errors.New("policy_response_invalid")
	}
	return allowed, nil
}

func (client *ServiceCapabilityClient) AggregateInsights(ctx context.Context, tenant string, query string) error {
	payload := map[string]any{
		"tenantId":     tenant,
		"query":        query,
		"evidenceRefs": []string{"gateway-route"},
	}
	_, err := client.postJSON(ctx, client.aggregateURL, payload)
	return err
}

func (client *ServiceCapabilityClient) GovernanceDecision(ctx context.Context, tenant string, region string, action string) error {
	payload := map[string]any{
		"tenantId":  tenant,
		"regionId":  region,
		"action":    action,
		"riskScore": 40,
	}
	_, err := client.postJSON(ctx, client.governanceURL, payload)
	return err
}

func (client *ServiceCapabilityClient) postJSON(ctx context.Context, url string, payload map[string]any) ([]byte, error) {
	bodyBytes, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewBuffer(bodyBytes))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	if client.authToken != "" {
		req.Header.Set("Authorization", "Bearer "+client.authToken)
	}
	resp, err := client.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode >= 300 {
		return nil, errors.New("capability_service_error")
	}
	return body, nil
}

func NewHTTPVectorAdapter(endpoint string, authToken string, timeout time.Duration) *HTTPVectorAdapter {
	return &HTTPVectorAdapter{
		endpoint:  endpoint,
		authToken: authToken,
		client:    &http.Client{Timeout: timeout},
	}
}

func (adapter *HTTPVectorAdapter) Search(ctx context.Context, namespace string, vector []float32, topK int) ([]VectorHit, error) {
	v := make([]float64, 0, len(vector))
	for _, f := range vector {
		v = append(v, float64(f))
	}
	bodyBytes, err := json.Marshal(map[string]any{
		"collection_name": namespace,
		"vectors":         [][]float64{v},
		"limit":           topK,
	})
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, adapter.endpoint, bytes.NewBuffer(bodyBytes))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	if adapter.authToken != "" {
		req.Header.Set("Authorization", "Bearer "+adapter.authToken)
	}
	resp, err := adapter.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return nil, errors.New("vector_search_failed")
	}
	_, _ = io.Copy(io.Discard, resp.Body)
	return []VectorHit{}, nil
}

type NoopCacheAdapter struct{}

func (NoopCacheAdapter) GetMany(ctx context.Context, keys []string) (map[string]string, error) {
	_ = ctx
	_ = keys
	return map[string]string{}, nil
}

func (NoopCacheAdapter) SetManyWithTTL(ctx context.Context, items map[string]string, ttl time.Duration) error {
	_ = ctx
	_ = items
	_ = ttl
	return nil
}

type NoopEventAdapter struct{}

func (NoopEventAdapter) PublishBatch(ctx context.Context, topic string, payloads []map[string]any) error {
	_ = ctx
	_ = topic
	_ = payloads
	return nil
}

type NoopGraphAdapter struct{}

func (NoopGraphAdapter) BatchUpsertRelations(ctx context.Context, edges []GraphEdge) error {
	_ = ctx
	_ = edges
	return nil
}

type NoopVectorAdapter struct{}

func (NoopVectorAdapter) Search(ctx context.Context, namespace string, vector []float32, topK int) ([]VectorHit, error) {
	_ = ctx
	_ = namespace
	_ = vector
	_ = topK
	return []VectorHit{}, nil
}

type TokenBucketRateLimiter struct {
	capacity float64
	tokens   float64
	rate     float64
	last     time.Time
	mu       sync.Mutex
}

func NewTokenBucketRateLimiter(tokensPerMinute int) *TokenBucketRateLimiter {
	if tokensPerMinute <= 0 {
		tokensPerMinute = 6000
	}
	now := time.Now()
	return &TokenBucketRateLimiter{
		capacity: float64(tokensPerMinute),
		tokens:   float64(tokensPerMinute),
		rate:     float64(tokensPerMinute) / 60.0,
		last:     now,
	}
}

func (limiter *TokenBucketRateLimiter) Allow(tokens int) bool {
	limiter.mu.Lock()
	defer limiter.mu.Unlock()

	now := time.Now()
	elapsed := now.Sub(limiter.last).Seconds()
	limiter.tokens = min(limiter.capacity, limiter.tokens+elapsed*limiter.rate)
	limiter.last = now
	if limiter.tokens >= float64(tokens) {
		limiter.tokens -= float64(tokens)
		return true
	}
	return false
}

func min(a float64, b float64) float64 {
	if a < b {
		return a
	}
	return b
}

type breakerState int32

const (
	breakerClosed breakerState = iota
	breakerOpen
	breakerHalfOpen
)

type CircuitBreaker struct {
	name             string
	failureThreshold int
	openDuration     time.Duration
	halfOpenMaxCalls int

	state            atomic.Int32
	failureCount     int
	openUntil        time.Time
	halfOpenInflight int
	mu               sync.Mutex
}

func NewCircuitBreaker(name string, failureThreshold int, openDuration time.Duration, halfOpenMaxCalls int) *CircuitBreaker {
	if failureThreshold <= 0 {
		failureThreshold = 20
	}
	if openDuration <= 0 {
		openDuration = 15 * time.Second
	}
	if halfOpenMaxCalls <= 0 {
		halfOpenMaxCalls = 10
	}
	breaker := &CircuitBreaker{
		name:             name,
		failureThreshold: failureThreshold,
		openDuration:     openDuration,
		halfOpenMaxCalls: halfOpenMaxCalls,
	}
	breaker.state.Store(int32(breakerClosed))
	return breaker
}

func (breaker *CircuitBreaker) Allow() bool {
	breaker.mu.Lock()
	defer breaker.mu.Unlock()

	state := breakerState(breaker.state.Load())
	now := time.Now()
	if state == breakerOpen {
		if now.After(breaker.openUntil) {
			breaker.state.Store(int32(breakerHalfOpen))
			breaker.halfOpenInflight = 0
		} else {
			return false
		}
	}

	if breakerState(breaker.state.Load()) == breakerHalfOpen {
		if breaker.halfOpenInflight >= breaker.halfOpenMaxCalls {
			return false
		}
		breaker.halfOpenInflight++
	}
	return true
}

func (breaker *CircuitBreaker) Report(success bool) {
	breaker.mu.Lock()
	defer breaker.mu.Unlock()

	state := breakerState(breaker.state.Load())
	if state == breakerHalfOpen {
		if breaker.halfOpenInflight > 0 {
			breaker.halfOpenInflight--
		}
		if success {
			breaker.failureCount = 0
			breaker.state.Store(int32(breakerClosed))
			return
		}
		breaker.state.Store(int32(breakerOpen))
		breaker.openUntil = time.Now().Add(breaker.openDuration)
		return
	}

	if success {
		breaker.failureCount = 0
		return
	}

	breaker.failureCount++
	if breaker.failureCount >= breaker.failureThreshold {
		breaker.state.Store(int32(breakerOpen))
		breaker.openUntil = time.Now().Add(breaker.openDuration)
	}
}

func (breaker *CircuitBreaker) StateCode() int32 {
	return breaker.state.Load()
}

type EnvQuotaProvider struct {
	mu          sync.RWMutex
	data        map[string]int
	reloadEvery time.Duration
	lastReload  time.Time
}

func NewEnvQuotaProvider(reloadEvery time.Duration) *EnvQuotaProvider {
	provider := &EnvQuotaProvider{reloadEvery: reloadEvery, data: map[string]int{}}
	provider.reloadIfNeeded()
	return provider
}

func (provider *EnvQuotaProvider) Get(tenant string, route string, defaultRate int) int {
	provider.reloadIfNeeded()
	provider.mu.RLock()
	defer provider.mu.RUnlock()
	key := tenant + "|" + route
	if value, ok := provider.data[key]; ok && value > 0 {
		return value
	}
	return defaultRate
}

func (provider *EnvQuotaProvider) reloadIfNeeded() {
	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.reloadEvery > 0 && !provider.lastReload.IsZero() && time.Since(provider.lastReload) < provider.reloadEvery {
		return
	}
	raw := os.Getenv("EKB_GATEWAY_TENANT_ROUTE_LIMITS_JSON")
	provider.data = parseTenantRouteLimits(raw)
	provider.lastReload = time.Now()
}

func parseTenantRouteLimits(raw string) map[string]int {
	parsed := map[string]int{}
	if strings.TrimSpace(raw) == "" {
		return parsed
	}
	temp := map[string]int{}
	if err := json.Unmarshal([]byte(raw), &temp); err != nil {
		return parsed
	}
	for k, v := range temp {
		if v > 0 {
			parsed[k] = v
		}
	}
	return parsed
}

type ErrorBudgetController struct {
	errorRatePercent float64
	window           time.Duration
	degradeDuration  time.Duration
	minSamples       int

	mu          sync.Mutex
	windowStart time.Time
	total       int
	failures    int
	degradeTill time.Time
}

func NewErrorBudgetController(errorRatePercent float64, window time.Duration, degradeDuration time.Duration, minSamples int) *ErrorBudgetController {
	if errorRatePercent <= 0 {
		errorRatePercent = 5.0
	}
	if window <= 0 {
		window = 60 * time.Second
	}
	if degradeDuration <= 0 {
		degradeDuration = 30 * time.Second
	}
	if minSamples <= 0 {
		minSamples = 50
	}
	return &ErrorBudgetController{
		errorRatePercent: errorRatePercent,
		window:           window,
		degradeDuration:  degradeDuration,
		minSamples:       minSamples,
		windowStart:      time.Now(),
	}
}

func (controller *ErrorBudgetController) Report(success bool) {
	controller.mu.Lock()
	defer controller.mu.Unlock()
	controller.rotateWindowIfNeeded()
	controller.total++
	if !success {
		controller.failures++
	}
	if controller.total >= controller.minSamples {
		rate := (float64(controller.failures) / float64(controller.total)) * 100.0
		if rate >= controller.errorRatePercent {
			controller.degradeTill = time.Now().Add(controller.degradeDuration)
		}
	}
}

func (controller *ErrorBudgetController) IsDegraded() bool {
	controller.mu.Lock()
	defer controller.mu.Unlock()
	controller.rotateWindowIfNeeded()
	return time.Now().Before(controller.degradeTill)
}

func (controller *ErrorBudgetController) rotateWindowIfNeeded() {
	if time.Since(controller.windowStart) >= controller.window {
		controller.windowStart = time.Now()
		controller.total = 0
		controller.failures = 0
	}
}

type GatewayServer struct {
	name   string
	cache  CacheAdapter
	events EventAdapter
	graph  GraphAdapter
	vector VectorAdapter

	config GatewayRuntimeConfig

	globalLimiter *TokenBucketRateLimiter
	authzLimiter  *TokenBucketRateLimiter
	routeLimiter  *TokenBucketRateLimiter

	authzBreaker *CircuitBreaker
	routeBreaker *CircuitBreaker

	inflightSemaphore chan struct{}

	quotaProvider       *EnvQuotaProvider
	tenantRouteLimiters map[string]*TokenBucketRateLimiter
	tenantLimiterMu     sync.Mutex

	errorBudget *ErrorBudgetController
	capability  CapabilityAdapter

	canaryHits  atomic.Uint64
	primaryHits atomic.Uint64

	degradeHits atomic.Uint64

	authzBreakerOpenHits atomic.Uint64
	routeBreakerOpenHits atomic.Uint64

	routeProxies map[string]routeProxy
}

func main() {
	name := os.Getenv("SERVICE_NAME")
	if name == "" {
		name = "go-dialogue-authz-gateway"
	}
	config := loadGatewayRuntimeConfig()

	var cacheAdapter CacheAdapter = NoopCacheAdapter{}
	if redisURL := os.Getenv("EKB_REDIS_URL"); redisURL != "" {
		if redisAdapter, err := NewRedisCacheAdapter(redisURL); err == nil {
			cacheAdapter = redisAdapter
		}
	}

	var graphAdapter GraphAdapter = NoopGraphAdapter{}
	if graphURL := os.Getenv("EKB_GATEWAY_GRAPH_UPSERT_URL"); graphURL != "" {
		graphAdapter = NewHTTPGraphAdapter(graphURL, config.AuthToken, config.RouteTimeout)
	}

	var vectorAdapter VectorAdapter = NoopVectorAdapter{}
	if vectorURL := os.Getenv("EKB_GATEWAY_VECTOR_SEARCH_URL"); vectorURL != "" {
		vectorAdapter = NewHTTPVectorAdapter(vectorURL, config.AuthToken, config.RouteTimeout)
	}

	server := GatewayServer{
		name:                name,
		cache:               cacheAdapter,
		events:              NewPulsarEventAdapter(),
		graph:               graphAdapter,
		vector:              vectorAdapter,
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
		routeProxies:        map[string]routeProxy{},
	}

	server.routeProxies = buildRouteProxies(config)

	if capabilityURL := os.Getenv("EKB_GATEWAY_CAPABILITY_SERVICE_URL"); capabilityURL != "" {
		if config.CapabilityGRPCAddress != "" {
			if grpcAdapter, err := NewGRPCCapabilityAdapter(config.CapabilityGRPCAddress, config.CapabilityGRPCTimeout); err == nil {
				server.capability = grpcAdapter
			} else {
				server.capability = NewLegacyHTTPCapabilityAdapter(capabilityURL, config.AuthToken, config.RouteTimeout)
			}
		} else {
			server.capability = NewLegacyHTTPCapabilityAdapter(capabilityURL, config.AuthToken, config.RouteTimeout)
		}
	} else if config.CapabilityGRPCAddress != "" {
		if grpcAdapter, err := NewGRPCCapabilityAdapter(config.CapabilityGRPCAddress, config.CapabilityGRPCTimeout); err == nil {
			server.capability = grpcAdapter
		} else {
			server.capability = NoopCapabilityAdapter{}
		}
	}

	if server.capability == nil {
		server.capability = NoopCapabilityAdapter{}
	}

	if certFile, keyFile := os.Getenv("EKB_GATEWAY_TLS_CERT_FILE"), os.Getenv("EKB_GATEWAY_TLS_KEY_FILE"); certFile != "" && keyFile != "" {
		_ = http.ListenAndServeTLS(":8090", certFile, keyFile, server.routes())
		return
	}
	_ = http.ListenAndServe(":8090", server.routes())
}

func (s GatewayServer) routes() http.Handler {
	mux := http.NewServeMux()
	metricsPath := s.config.MetricsPath
	if strings.TrimSpace(metricsPath) == "" {
		metricsPath = "/metrics/gateway"
	}
	baseMiddlewares := []func(http.HandlerFunc) http.HandlerFunc{
		s.withGlobalRateLimit(),
		s.withBackpressure(),
	}

	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, HealthResponse{Status: "ok", Name: s.name})
	})

	mux.HandleFunc(metricsPath, func(w http.ResponseWriter, r *http.Request) {
		canary := s.canaryHits.Load()
		primary := s.primaryHits.Load()
		total := canary + primary
		canaryRatio := 0.0
		if total > 0 {
			canaryRatio = float64(canary) / float64(total)
		}
		metrics := map[string]any{
			"gateway_canary_hits":              s.canaryHits.Load(),
			"gateway_primary_hits":             s.primaryHits.Load(),
			"gateway_canary_hit_ratio":         canaryRatio,
			"gateway_degrade_hits":             s.degradeHits.Load(),
			"gateway_authz_circuit_open_hits":  s.authzBreakerOpenHits.Load(),
			"gateway_route_circuit_open_hits":  s.routeBreakerOpenHits.Load(),
			"gateway_authz_circuit_state_code": s.authzBreaker.StateCode(),
			"gateway_route_circuit_state_code": s.routeBreaker.StateCode(),
			"gateway_canary_percent":           s.config.CanaryPercent,
			"gateway_capability_mode":          s.capabilityMode(),
		}
		writeJSON(w, http.StatusOK, metrics)
	})

	authzHandler := func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"error": "method not allowed"})
			return
		}
		if !s.authzLimiter.Allow(1) {
			writeJSON(w, http.StatusTooManyRequests, map[string]any{"error": "authz_rate_limited"})
			return
		}
		if !s.authzBreaker.Allow() {
			s.authzBreakerOpenHits.Add(1)
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{"error": "authz_circuit_open"})
			return
		}

		ctx := r.Context()
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			s.authzBreaker.Report(false)
			s.errorBudget.Report(false)
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid_json"})
			return
		}

		subject, _ := body["subject"].(string)
		cacheKey := "authz:" + subject
		if _, err := s.cache.GetMany(ctx, []string{cacheKey}); err != nil {
			s.authzBreaker.Report(false)
			s.errorBudget.Report(false)
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{"error": "cache_unavailable"})
			return
		}

		eventErr := executeWithRetry(ctx, s.config.RetryMaxAttempts, s.config.RetryBackoff, func() error {
			return s.events.PublishBatch(ctx, "persistent://group/audit/authz-check", []map[string]any{{
				"subject": subject,
				"allowed": true,
				"ts":      time.Now().UTC().Format(time.RFC3339Nano),
			}})
		})
		if eventErr != nil {
			s.authzBreaker.Report(false)
			s.errorBudget.Report(false)
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{"error": "event_publish_failed"})
			return
		}

		s.authzBreaker.Report(true)
		s.errorBudget.Report(true)
		writeJSON(w, http.StatusOK, map[string]any{
			"allowed": true,
			"engine":  "casbin-compatible",
			"subject": subject,
		})
	}

	routeHandler := func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"error": "method not allowed"})
			return
		}
		if !s.routeLimiter.Allow(1) {
			writeJSON(w, http.StatusTooManyRequests, map[string]any{"error": "route_rate_limited"})
			return
		}
		if !s.routeBreaker.Allow() {
			s.routeBreakerOpenHits.Add(1)
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{"error": "route_circuit_open"})
			return
		}

		if s.errorBudget.IsDegraded() {
			s.degradeHits.Add(1)
			writeJSON(w, http.StatusOK, map[string]any{
				"route":  s.config.PrimaryRoute,
				"mode":   "degraded",
				"reason": "error_budget_exceeded",
			})
			return
		}

		ctx := r.Context()
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			s.routeBreaker.Report(false)
			s.errorBudget.Report(false)
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid_json"})
			return
		}

		tenant, _ := body["tenant_id"].(string)
		region, _ := body["region_id"].(string)

		if s.capability != nil {
			allowed, policyErr := s.capability.EvaluatePolicy(ctx, tenant, region, "route")
			if policyErr != nil {
				s.routeBreaker.Report(false)
				s.errorBudget.Report(false)
				writeJSON(w, http.StatusServiceUnavailable, map[string]any{"error": "capability_policy_unavailable"})
				return
			}
			if !allowed {
				s.routeBreaker.Report(true)
				s.errorBudget.Report(true)
				writeJSON(w, http.StatusForbidden, map[string]any{"error": "policy_denied"})
				return
			}
			if err := s.capability.AggregateInsights(ctx, tenant, "route_dispatch"); err != nil {
				s.routeBreaker.Report(false)
				s.errorBudget.Report(false)
				writeJSON(w, http.StatusServiceUnavailable, map[string]any{"error": "capability_aggregate_unavailable"})
				return
			}
			if err := s.capability.GovernanceDecision(ctx, tenant, region, "route_dispatch"); err != nil {
				s.routeBreaker.Report(false)
				s.errorBudget.Report(false)
				writeJSON(w, http.StatusServiceUnavailable, map[string]any{"error": "capability_governance_unavailable"})
				return
			}
		}

		cacheKey := "route:" + tenant
		if _, err := s.cache.GetMany(ctx, []string{cacheKey}); err != nil {
			s.routeBreaker.Report(false)
			s.errorBudget.Report(false)
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{"error": "cache_unavailable"})
			return
		}

		graphErr := executeWithRetry(ctx, s.config.RetryMaxAttempts, s.config.RetryBackoff, func() error {
			return s.graph.BatchUpsertRelations(ctx, []GraphEdge{{Source: tenant, Target: s.config.PrimaryRoute, Type: "ROUTED_TO"}})
		})
		if graphErr != nil {
			s.routeBreaker.Report(false)
			s.errorBudget.Report(false)
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{"error": "graph_unavailable"})
			return
		}

		if _, err := s.vector.Search(ctx, "dialogue-route", []float32{0.1, 0.2, 0.3}, 3); err != nil {
			s.routeBreaker.Report(false)
			s.errorBudget.Report(false)
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{"error": "vector_unavailable"})
			return
		}

		route := s.pickRouteForTenant(tenant)
		if route == s.config.CanaryRoute {
			s.canaryHits.Add(1)
		} else {
			s.primaryHits.Add(1)
		}
		eventErr := executeWithRetry(ctx, s.config.RetryMaxAttempts, s.config.RetryBackoff, func() error {
			return s.events.PublishBatch(ctx, "persistent://group/audit/mcp-invoke", []map[string]any{{
				"tenant": tenant,
				"mode":   "low-latency",
				"route":  route,
				"ts":     time.Now().UTC().Format(time.RFC3339Nano),
			}})
		})
		if eventErr != nil {
			s.routeBreaker.Report(false)
			s.errorBudget.Report(false)
			writeJSON(w, http.StatusServiceUnavailable, map[string]any{"error": "event_publish_failed"})
			return
		}

		bodyBytes, marshalErr := json.Marshal(body)
		if marshalErr != nil {
			s.routeBreaker.Report(false)
			s.errorBudget.Report(false)
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid_payload"})
			return
		}
		r.Body = io.NopCloser(bytes.NewBuffer(bodyBytes))
		r.ContentLength = int64(len(bodyBytes))
		if proxied, success := s.tryProxyRoute(w, r, route, tenant); proxied {
			s.routeBreaker.Report(success)
			s.errorBudget.Report(success)
			return
		}

		s.routeBreaker.Report(true)
		s.errorBudget.Report(true)
		writeJSON(w, http.StatusOK, map[string]any{
			"route":       route,
			"mode":        "low-latency",
			"tenant":      tenant,
			"cache_hints": []string{"redis-batch-read", "redis-pipeline-write"},
			"ttl_ms":      strconv.Itoa(int(s.config.RouteTimeout.Milliseconds())),
		})
	}

	mux.HandleFunc("/v1/authz/check", chain(authzHandler, append(baseMiddlewares,
		s.withAuth(),
		s.withTimeout(s.config.AuthzTimeout),
		s.withTenantRouteLimit("/v1/authz/check", s.config.AuthzRateLimitPerMinute),
	)...))

	mux.HandleFunc("/v1/dialogue/route", chain(routeHandler, append(baseMiddlewares,
		s.withAuth(),
		s.withTimeout(s.config.RouteTimeout),
		s.withTenantRouteLimit("/v1/dialogue/route", s.config.RouteRateLimitPerMinute),
	)...))

	return mux
}

func (s GatewayServer) tryProxyRoute(w http.ResponseWriter, r *http.Request, route string, tenant string) (bool, bool) {
	rp, ok := s.routeProxies[route]
	if !ok {
		return false, false
	}
	requestClone := r.Clone(r.Context())
	requestClone.Header.Set("X-Resolved-Route", route)
	requestClone.Header.Set("X-Tenant-ID", tenant)
	requestClone.Header.Set("X-Gateway-Mode", "proxy")
	recorder := &statusRecorder{ResponseWriter: w}
	rp.proxy.ServeHTTP(recorder, requestClone)
	if recorder.statusCode == 0 {
		recorder.statusCode = http.StatusOK
	}
	return true, recorder.statusCode < 500
}

func buildRouteProxies(config GatewayRuntimeConfig) map[string]routeProxy {
	result := map[string]routeProxy{}
	for route, rawURL := range config.BackendRouteMap {
		backendURL := strings.TrimSpace(rawURL)
		if backendURL == "" {
			continue
		}
		targetURL, err := url.Parse(backendURL)
		if err != nil {
			continue
		}
		t := &http.Transport{
			Proxy:               http.ProxyFromEnvironment,
			MaxIdleConns:        config.ProxyMaxIdleConns,
			MaxIdleConnsPerHost: config.ProxyMaxIdleConnsPerHost,
			MaxConnsPerHost:     config.ProxyMaxConnsPerHost,
			IdleConnTimeout:     config.ProxyIdleConnTimeout,
		}
		proxy := httputil.NewSingleHostReverseProxy(targetURL)
		proxy.Transport = t
		basePath := strings.TrimSuffix(targetURL.Path, "/")
		proxy.Director = func(req *http.Request) {
			req.URL.Scheme = targetURL.Scheme
			req.URL.Host = targetURL.Host
			req.Host = targetURL.Host
			req.URL.Path = basePath + "/mcp/invoke"
		}
		result[route] = routeProxy{baseURL: backendURL, proxy: proxy}
	}
	return result
}

func parseBackendRouteMap(raw string) map[string]string {
	result := map[string]string{}
	if strings.TrimSpace(raw) == "" {
		return result
	}
	for _, pair := range strings.Split(raw, ",") {
		item := strings.TrimSpace(pair)
		if item == "" {
			continue
		}
		parts := strings.SplitN(item, "=", 2)
		if len(parts) != 2 {
			continue
		}
		key := strings.TrimSpace(parts[0])
		value := strings.TrimSpace(parts[1])
		if key != "" && value != "" {
			result[key] = value
		}
	}
	return result
}

func (s GatewayServer) pickRouteForTenant(tenant string) string {
	if s.config.CanaryPercent <= 0 || s.config.CanaryRoute == "" {
		return s.config.PrimaryRoute
	}
	h := fnv.New32a()
	_, _ = h.Write([]byte(tenant))
	bucket := int(h.Sum32() % 100)
	if bucket < s.config.CanaryPercent {
		return s.config.CanaryRoute
	}
	return s.config.PrimaryRoute
}

func (s GatewayServer) withAuth() func(http.HandlerFunc) http.HandlerFunc {
	return func(next http.HandlerFunc) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			if s.config.AuthToken == "" {
				next(w, r)
				return
			}
			auth := r.Header.Get("Authorization")
			if auth != "Bearer "+s.config.AuthToken {
				writeJSON(w, http.StatusUnauthorized, map[string]any{"error": "unauthorized"})
				return
			}
			next(w, r)
		}
	}
}

func (s GatewayServer) withGlobalRateLimit() func(http.HandlerFunc) http.HandlerFunc {
	return func(next http.HandlerFunc) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			if !s.globalLimiter.Allow(1) {
				writeJSON(w, http.StatusTooManyRequests, map[string]any{"error": "global_rate_limited"})
				return
			}
			next(w, r)
		}
	}
}

func (s GatewayServer) withBackpressure() func(http.HandlerFunc) http.HandlerFunc {
	return func(next http.HandlerFunc) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			select {
			case s.inflightSemaphore <- struct{}{}:
				defer func() { <-s.inflightSemaphore }()
				next(w, r)
			default:
				writeJSON(w, http.StatusServiceUnavailable, map[string]any{"error": "gateway_overloaded"})
			}
		}
	}
}

func (s GatewayServer) withTimeout(timeout time.Duration) func(http.HandlerFunc) http.HandlerFunc {
	return func(next http.HandlerFunc) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			ctx, cancel := context.WithTimeout(r.Context(), timeout)
			defer cancel()
			next(w, r.WithContext(ctx))
		}
	}
}

func (s GatewayServer) withTenantRouteLimit(route string, defaultRate int) func(http.HandlerFunc) http.HandlerFunc {
	return func(next http.HandlerFunc) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			tenant := r.Header.Get("X-Tenant-ID")
			if tenant == "" {
				tenant = "default"
			}
			rate := defaultRate
			if s.quotaProvider != nil {
				rate = s.quotaProvider.Get(tenant, route, defaultRate)
			}
			limiter := s.getTenantLimiter(tenant, route, rate)
			if !limiter.Allow(1) {
				writeJSON(w, http.StatusTooManyRequests, map[string]any{"error": "tenant_route_rate_limited"})
				return
			}
			next(w, r)
		}
	}
}

func (s GatewayServer) getTenantLimiter(tenant string, route string, rate int) *TokenBucketRateLimiter {
	if rate <= 0 {
		rate = 1
	}
	key := tenant + "|" + route
	s.tenantLimiterMu.Lock()
	defer s.tenantLimiterMu.Unlock()
	if s.tenantRouteLimiters == nil {
		s.tenantRouteLimiters = map[string]*TokenBucketRateLimiter{}
	}
	if limiter, ok := s.tenantRouteLimiters[key]; ok {
		return limiter
	}
	limiter := NewTokenBucketRateLimiter(rate)
	s.tenantRouteLimiters[key] = limiter
	return limiter
}

func (s GatewayServer) capabilityMode() string {
	if s.capability == nil {
		return "noop"
	}
	return s.capability.Mode()
}

func chain(handler http.HandlerFunc, middlewares ...func(http.HandlerFunc) http.HandlerFunc) http.HandlerFunc {
	wrapped := handler
	for i := len(middlewares) - 1; i >= 0; i-- {
		wrapped = middlewares[i](wrapped)
	}
	return wrapped
}

func executeWithRetry(ctx context.Context, attempts int, backoff time.Duration, fn func() error) error {
	if attempts <= 0 {
		attempts = 1
	}
	if backoff < 0 {
		backoff = 0
	}
	var lastErr error
	for attempt := 0; attempt < attempts; attempt++ {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		err := fn()
		if err == nil {
			return nil
		}
		lastErr = err
		if attempt == attempts-1 {
			break
		}
		timer := time.NewTimer(backoff)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ctx.Err()
		case <-timer.C:
		}
	}
	return lastErr
}

func loadGatewayRuntimeConfig() GatewayRuntimeConfig {
	globalRate := getEnvInt("EKB_GATEWAY_GLOBAL_RATE_LIMIT_PER_MINUTE", 12000)
	authzRate := getEnvInt("EKB_GATEWAY_AUTHZ_RATE_LIMIT_PER_MINUTE", 8000)
	routeRate := getEnvInt("EKB_GATEWAY_ROUTE_RATE_LIMIT_PER_MINUTE", getEnvInt("EKB_GATEWAY_RATE_LIMIT_PER_MINUTE", 6000))

	authzTimeoutMS := getEnvInt("EKB_GATEWAY_AUTHZ_TIMEOUT_MS", 120)
	routeTimeoutMS := getEnvInt("EKB_GATEWAY_ROUTE_TIMEOUT_MS", 180)

	retryAttempts := getEnvInt("EKB_GATEWAY_RETRY_MAX_ATTEMPTS", 2)
	retryBackoffMS := getEnvInt("EKB_GATEWAY_RETRY_BACKOFF_MS", 10)

	maxInflight := getEnvInt("EKB_GATEWAY_MAX_INFLIGHT", 2000)

	breakerFailures := getEnvInt("EKB_GATEWAY_CIRCUIT_BREAKER_FAILURE_THRESHOLD", 20)
	breakerOpenSeconds := getEnvInt("EKB_GATEWAY_CIRCUIT_BREAKER_OPEN_SECONDS", 15)
	breakerHalfOpenCalls := getEnvInt("EKB_GATEWAY_CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS", 10)

	canaryPercent := getEnvInt("EKB_GATEWAY_CANARY_PERCENT", 0)
	primaryRoute := getEnvString("EKB_GATEWAY_PRIMARY_ROUTE", "python-dialogue-service")
	canaryRoute := getEnvString("EKB_GATEWAY_CANARY_ROUTE", "python-dialogue-service-canary")

	quotaReloadSeconds := getEnvInt("EKB_GATEWAY_TENANT_ROUTE_LIMITS_RELOAD_SECONDS", 30)

	degradeErrorRate := getEnvFloat("EKB_GATEWAY_DEGRADE_ERROR_RATE_PERCENT", 5.0)
	degradeWindowSeconds := getEnvInt("EKB_GATEWAY_DEGRADE_WINDOW_SECONDS", 60)
	degradeDurationSeconds := getEnvInt("EKB_GATEWAY_DEGRADE_DURATION_SECONDS", 30)
	degradeMinSamples := getEnvInt("EKB_GATEWAY_DEGRADE_MIN_SAMPLES", 50)

	metricsPath := getEnvString("EKB_GATEWAY_METRICS_PATH", "/metrics/gateway")
	capabilityGRPCAddress := getEnvString("EKB_GATEWAY_CAPABILITY_GRPC_ADDRESS", "")
	capabilityGRPCTimeoutMS := getEnvInt("EKB_GATEWAY_CAPABILITY_GRPC_TIMEOUT_MS", 200)
	backendRouteMap := parseBackendRouteMap(getEnvString("EKB_GATEWAY_BACKEND_ROUTE_MAP", ""))
	proxyMaxIdleConns := getEnvInt("EKB_GATEWAY_PROXY_MAX_IDLE_CONNS", 4096)
	proxyMaxIdleConnsPerHost := getEnvInt("EKB_GATEWAY_PROXY_MAX_IDLE_CONNS_PER_HOST", 2048)
	proxyMaxConnsPerHost := getEnvInt("EKB_GATEWAY_PROXY_MAX_CONNS_PER_HOST", 0)
	proxyIdleConnTimeoutSec := getEnvInt("EKB_GATEWAY_PROXY_IDLE_CONN_TIMEOUT_SECONDS", 90)

	return GatewayRuntimeConfig{
		AuthToken:                    getEnvString("EKB_GATEWAY_AUTH_TOKEN", getEnvString("EKB_AUTH_TOKEN", "")),
		GlobalRateLimitPerMinute:     globalRate,
		AuthzRateLimitPerMinute:      authzRate,
		RouteRateLimitPerMinute:      routeRate,
		AuthzTimeout:                 time.Duration(authzTimeoutMS) * time.Millisecond,
		RouteTimeout:                 time.Duration(routeTimeoutMS) * time.Millisecond,
		RetryMaxAttempts:             retryAttempts,
		RetryBackoff:                 time.Duration(retryBackoffMS) * time.Millisecond,
		MaxInflight:                  maxInflight,
		BreakerFailureThreshold:      breakerFailures,
		BreakerOpenDuration:          time.Duration(breakerOpenSeconds) * time.Second,
		BreakerHalfOpenMaxCalls:      breakerHalfOpenCalls,
		CanaryPercent:                canaryPercent,
		PrimaryRoute:                 primaryRoute,
		CanaryRoute:                  canaryRoute,
		TenantRouteLimitsReloadEvery: time.Duration(quotaReloadSeconds) * time.Second,
		DegradeErrorRatePercent:      degradeErrorRate,
		DegradeWindow:                time.Duration(degradeWindowSeconds) * time.Second,
		DegradeDuration:              time.Duration(degradeDurationSeconds) * time.Second,
		DegradeMinSamples:            degradeMinSamples,
		MetricsPath:                  metricsPath,
		CapabilityGRPCAddress:        capabilityGRPCAddress,
		CapabilityGRPCTimeout:        time.Duration(capabilityGRPCTimeoutMS) * time.Millisecond,
		BackendRouteMap:              backendRouteMap,
		ProxyMaxIdleConns:            proxyMaxIdleConns,
		ProxyMaxIdleConnsPerHost:     proxyMaxIdleConnsPerHost,
		ProxyMaxConnsPerHost:         proxyMaxConnsPerHost,
		ProxyIdleConnTimeout:         time.Duration(proxyIdleConnTimeoutSec) * time.Second,
	}
}

func getEnvInt(name string, defaultValue int) int {
	raw := os.Getenv(name)
	if raw == "" {
		return defaultValue
	}
	parsed, err := strconv.Atoi(raw)
	if err != nil {
		return defaultValue
	}
	return parsed
}

func getEnvFloat(name string, defaultValue float64) float64 {
	raw := os.Getenv(name)
	if raw == "" {
		return defaultValue
	}
	parsed, err := strconv.ParseFloat(raw, 64)
	if err != nil {
		return defaultValue
	}
	return parsed
}

func getEnvString(name string, defaultValue string) string {
	raw := os.Getenv(name)
	if raw == "" {
		return defaultValue
	}
	return raw
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
