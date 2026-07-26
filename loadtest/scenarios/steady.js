import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

const baseUrl = __ENV.BACKEND_BASE_URL || 'http://backend:8000';
const orderRate = Number(__ENV.ORDER_RATE || '10');
const testDuration = __ENV.TEST_DURATION || '30s';

if (!Number.isInteger(orderRate) || orderRate < 1) {
  throw new Error('ORDER_RATE must be a positive integer');
}

export const options = {
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  scenarios: {
    steady_orders: {
      executor: 'constant-arrival-rate',
      rate: orderRate,
      timeUnit: '1s',
      duration: testDuration,
      gracefulStop: '0s',
      preAllocatedVUs: Math.max(10, Math.ceil(orderRate / 10)),
      maxVUs: Math.max(50, Math.ceil(orderRate / 2)),
    },
  },
  thresholds: {
    checks: ['rate==1'],
    http_req_failed: ['rate<0.01'],
    dropped_iterations: ['count==0'],
  },
};

const submittedOrders = new Counter('orders_submitted');

export default function () {
  const side = (__VU + __ITER) % 2 === 0 ? 'BUY' : 'SELL';
  const response = http.post(
    `${baseUrl}/api/v1/orders/`,
    JSON.stringify({
      user_id: `k6-vu-${__VU}-iteration-${__ITER}`,
      symbol: '005930',
      side,
      price: 70_000,
      qty: 1,
    }),
    {
      headers: { 'Content-Type': 'application/json' },
      tags: { endpoint: 'orders' },
    },
  );

  submittedOrders.add(1);
  check(response, {
    'order accepted': (result) => result.status === 201,
  });
}
