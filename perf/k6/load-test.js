import http from 'k6/http'
import { check, sleep } from 'k6'
import { Trend } from 'k6/metrics'

const baseUrl = __ENV.BASE_URL || 'http://localhost:8090'
const controlBaseUrl = __ENV.CONTROL_BASE_URL || 'http://localhost:8080'

const gatewayLatency = new Trend('gateway_latency')
const controlLatency = new Trend('ai_control_latency')
const gatewayRouteLatency = new Trend('gateway_route_latency')

export const options = {
  scenarios: {
    ramp_up: {
      executor: 'ramping-vus',
      exec: 'runScenario',
      startVUs: 0,
      stages: [
        { duration: '2m', target: 40 },
        { duration: '4m', target: 120 },
        { duration: '2m', target: 120 },
      ],
    },
    spike: {
      executor: 'ramping-vus',
      exec: 'runScenario',
      startVUs: 0,
      stages: [
        { duration: '45s', target: 220 },
        { duration: '2m', target: 220 },
        { duration: '45s', target: 0 },
      ],
      startTime: '8m',
    },
    soak: {
      executor: 'ramping-vus',
      exec: 'runScenario',
      startVUs: 50,
      stages: [
        { duration: '30m', target: 90 },
      ],
      startTime: '12m',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.002'],
    gateway_latency: ['p(90)<150', 'p(95)<200', 'p(99)<400'],
    gateway_route_latency: ['p(90)<130', 'p(95)<180', 'p(99)<350'],
    ai_control_latency: ['p(90)<380', 'p(95)<500', 'p(99)<1200'],
  },
}

function registerAndPromoteSkill() {
  const registerPayload = JSON.stringify({
    skill_name: 'k6-qa-agent',
    version: '1.0.0',
    owner: 'perf-team',
    risk_level: 'low',
    allowed_tools: ['qa.query'],
    allowed_domains: ['quality'],
    residency_scope: ['cn-north-1'],
    input_schema: { type: 'object' },
    output_schema: { type: 'object' },
    changelog: 'k6 bootstrapped',
  })
  const registerResp = http.post(`${controlBaseUrl}/skills/register`, registerPayload, {
    headers: { 'Content-Type': 'application/json' },
  })
  check(registerResp, {
    'register status 200 or 409': (r) => r.status === 200 || r.status === 409,
  })

  const stages = ['review', 'staging', 'production']
  for (const stage of stages) {
    const promoteResp = http.post(
      `${controlBaseUrl}/skills/promote`,
      JSON.stringify({ skill_name: 'k6-qa-agent', version: '1.0.0', target_stage: stage }),
      { headers: { 'Content-Type': 'application/json' } }
    )
    check(promoteResp, {
      'promote status 200': (r) => r.status === 200,
    })
  }
}

export function setup() {
  registerAndPromoteSkill()
}

export function runScenario() {
  const t0 = Date.now()
  const health = http.get(`${baseUrl}/healthz`)
  gatewayLatency.add(Date.now() - t0)

  const routePayload = JSON.stringify({
    tenant_id: 'group',
    region_id: 'cn-north-1',
    plant_id: 'plant-bj',
  })
  const routeStart = Date.now()
  const routeResp = http.post(`${baseUrl}/v1/dialogue/route`, routePayload, {
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${__ENV.GATEWAY_TOKEN || ''}` },
  })
  gatewayRouteLatency.add(Date.now() - routeStart)

  const invokePayload = JSON.stringify({
    tenant_id: 'group',
    region_id: 'cn-north-1',
    plant_id: 'plant-bj',
    domain: 'quality',
    user_or_agent_id: 'perf-user',
    skill_name: 'k6-qa-agent',
    skill_version: '1.0.0',
    tool_name: 'qa.query',
    payload: { q: 'status' },
  })

  const t1 = Date.now()
  const invoke = http.post(`${controlBaseUrl}/mcp/invoke`, invokePayload, {
    headers: { 'Content-Type': 'application/json' },
  })
  controlLatency.add(Date.now() - t1)

  const relay = http.post(
    `${controlBaseUrl}/events/relay`,
    JSON.stringify({ batch_size: 10 }),
    { headers: { 'Content-Type': 'application/json' } }
  )

  check(health, {
    'health status 200': (r) => r.status === 200,
  })
  check(routeResp, {
    'route status 200': (r) => r.status === 200,
  })
  check(invoke, {
    'invoke status 200': (r) => r.status === 200,
  })
  check(relay, {
    'relay status 200': (r) => r.status === 200,
  })

  sleep(0.2)
}
