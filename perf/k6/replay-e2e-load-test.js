import http from 'k6/http'
import { check, sleep } from 'k6'
import { Trend } from 'k6/metrics'

const baseUrl = __ENV.BASE_URL || 'http://localhost:8080'
const authToken = __ENV.AUTH_TOKEN || ''

const relayLatency = new Trend('relay_latency')
const a2aPublishLatency = new Trend('a2a_publish_latency')
const subAgentLatency = new Trend('subagent_delegate_latency')

export const options = {
  scenarios: {
    warmup: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 30 },
        { duration: '1m', target: 60 },
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: '10s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.005'],
    relay_latency: ['p(90)<260', 'p(95)<350', 'p(99)<700'],
    a2a_publish_latency: ['p(90)<130', 'p(95)<180', 'p(99)<350'],
    subagent_delegate_latency: ['p(90)<180', 'p(95)<250', 'p(99)<500'],
  },
}

function headers() {
  return authToken
    ? { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` }
    : { 'Content-Type': 'application/json' }
}

export default function () {
  const msgId = `msg-${__VU}-${__ITER}-${Date.now()}`

  const pubStart = Date.now()
  const publishResp = http.post(
    `${baseUrl}/a2a/publish`,
    JSON.stringify({
      message_id: msgId,
      correlation_id: msgId,
      tenant_id: 'group',
      region_id: 'cn-north-1',
      agent_id: 'planner',
      target_agent: 'executor',
      intent: 'yield_optimization',
      priority: 'high',
      idempotency_key: msgId,
      created_at: new Date().toISOString(),
      ttl_seconds: 300,
      payload: { order_no: `SO-${__VU}-${__ITER}` },
      metadata: { source: 'k6-replay-e2e' },
    }),
    { headers: headers() },
  )
  a2aPublishLatency.add(Date.now() - pubStart)

  const subStart = Date.now()
  const subResp = http.post(
    `${baseUrl}/a2a/sub-agent/delegate`,
    JSON.stringify({
      tenant_id: 'group',
      region_id: 'cn-north-1',
      supervisor_id: 'planner',
      sub_agent_type: 'executor',
      task_objective: 'execute quality triage',
      idempotency_key: `sub-${msgId}`,
      context_payload: { trace: msgId },
    }),
    { headers: headers() },
  )
  subAgentLatency.add(Date.now() - subStart)

  const relayStart = Date.now()
  const relayResp = http.post(
    `${baseUrl}/events/relay`,
    JSON.stringify({ batch_size: 200 }),
    { headers: headers() },
  )
  relayLatency.add(Date.now() - relayStart)

  check(publishResp, { 'a2a publish 200': (r) => r.status === 200 })
  check(subResp, { 'subagent delegate 200': (r) => r.status === 200 })
  check(relayResp, { 'relay 200': (r) => r.status === 200 })

  sleep(0.2)
}
