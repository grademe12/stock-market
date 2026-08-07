# KRX KOSPI 거래대금 상위 100개 적재

> **목적**: KRX의 가장 최근 확정 거래일을 기준으로 KOSPI 거래대금 상위 100개 종목과 종가를 PostgreSQL에 적재한다.
>
> 이 데이터는 시뮬레이터의 종목 풀과 기준가를 위한 참조 데이터다. 외부 가격은 내부 order book의 체결가를 대체하지 않는다.

**관련 문서**: [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) · [database 설정](../db/README.md)

## 범위

### 포함

- KRX Open API `유가증권 일별매매정보` 조회
- 직전 날짜부터 역순으로 가장 최근 데이터가 존재하는 거래일 탐색
- 거래대금 내림차순 KOSPI 상위 100개 선별
- 종목, 종가, 거래량, 거래대금, 순위와 원본 레코드 upsert
- 수집 실행의 성공·실패 이력 기록
- Django management command를 통한 수동 실행

### 제외

- KOSDAQ, 실시간 시세·호가·체결 수집
- 외부 데이터 기반 자동 주문 또는 실제 증권사 거래
- 장기 OHLCV backfill과 일 1회 scheduler
- 수집 데이터를 현재 단일 종목 matcher에 즉시 연결

## 설정과 보안

실제 값은 Git과 Docker build context에서 제외된 두 파일에 나눠 둔다.

```env
# db/.env
KRX_API_KEY=...

# db/postgres.env
POSTGRES_DB=stock_market
POSTGRES_USER=stock_market
POSTGRES_PASSWORD=...
```

애플리케이션 환경변수 이름은 `KRX_API_KEY`다. 실제 KRX 요청에는 공식 규격에 따라 `AUTH_KEY` 헤더로 전달하며 키·인증 헤더를 로그, 예외 메시지, API 응답에 포함하지 않는다.

## 선별 규칙

1. `--trade-date`가 없으면 KST 오늘의 직전 날짜부터 최대 10일을 역순 조회한다.
2. 데이터가 처음 존재하는 날짜를 최근 확정 거래일로 선택한다.
3. 거래대금이 0보다 큰 종목만 후보로 사용한다.
4. 거래대금 내림차순, 거래량 내림차순, 종목코드 오름차순으로 정렬한다.
5. 정확히 상위 100개를 선택한다. 후보가 100개 미만이면 실패한다.
6. 동일 거래일 재실행은 중복 없이 갱신하고 이전 상위 100개에서 빠진 일별 행을 제거한다.
7. 적재 전체를 하나의 transaction으로 처리해 부분 성공을 남기지 않는다.

## 데이터 모델

```text
Symbol
  ticker             string, primary key
  name               string
  market             KOSPI
  updated_at         datetime

MarketDaily
  symbol             foreign key Symbol
  trade_date         date
  close_price        integer
  volume             integer
  trading_value      integer
  trading_value_rank integer
  source             krx_open_api
  source_payload     JSON
  imported_at        datetime
  unique             (symbol, trade_date)

ReferenceImportRun
  id                 UUID
  trade_date         date, nullable
  status             running | success | failed
  selected_count     integer
  error_message      text
  started_at         datetime
  finished_at        datetime
```

가격·수량·거래대금은 모두 정수로 저장하며 `float`를 사용하지 않는다. Django model migration은 `backend/exchange/migrations/`에서만 관리한다.

## 실행

```bash
make db-up
make db-migrate
make import-krx-top100
make import-krx-top100 TRADE_DATE=20260727
```

성공 시 기준 거래일, 선택 수, 실행 ID와 상위 10개를 출력한다. 인증키가 없거나 API 권한이 없으면 키를 노출하지 않고 실패한다.

## 완료 기준

- fixture 기반 client parsing, 순위 결정, 100개 선택 테스트 통과
- 동일 날짜 재실행의 idempotency와 이전 순위 데이터 정리 확인
- 100개 미만 응답에서 `ReferenceImportRun.status=failed`이며 일별 데이터가 저장되지 않음
- PostgreSQL container에서 Django migration과 전체 backend 테스트 통과
- 실제 KRX API에서 최근 확정 거래일 100개 적재 및 DB 재시작 후 보존 확인

실제 적재가 안정된 뒤에만 조회 API와 matcher 종목 확장을 별도 작업으로 설계한다.

---

*Last updated: 2026-07-28*
