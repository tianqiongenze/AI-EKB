import http from 'k6/http'
import { check, sleep } from 'k6'

const baseUrl = __ENV.BASE_URL || 'http://localhost:8090'
const route = __ENV.ROUTE_PATH || '/healthz'

export const options = {
  vus: Number(__ENV.VUS || 50),
  duration: __ENV.DURATION || '2m',
  thresholds: {
    http_req_failed: ['rate<0.02'],
    http_req_duration: ['p(90)<1200', 'p(95)<1500', 'p(99)<3000'],
  },
}

export default function () {
  const res = http.get(`${baseUrl}${route}`)
  check(res, {
    'status is 200': (r) => r.status === 200,
  })
  sleep(0.1)
}
