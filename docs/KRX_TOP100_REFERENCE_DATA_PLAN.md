# KRX 거래대금 상위 100개 종목 적재 계획

> **목적**: KRX의 최근 확정 거래일 데이터를 기준으로 KOSPI·KOSDAQ 전체에서 거래대금 상위 100개 종목을 선별해 로컬 DB에 적재한다.
>
> 이 데이터는 시뮬레이터의 종목 풀·기준가·차트·전략 입력에만 사용한다. 외부 가격은 내부 order book의 체결가를 대체하지 않는다.

**선행 조건**: KRX Open API 인증키 발급 완료

**관련 문서**: [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) · [backend README](../backend/README.md)

---

## 1. 범위

### 포함

- KRX Open API의 유가증권·코스닥 일별매매정보 조회
- 최근 **확정 거래일**의 데이터를 KOSPI·KOSDAQ에서 각각 수집
- 두 시장 데이터를 합쳐 거래대금 내림차순 정렬 후 상위 100개 선별
- 종목 기본정보 조회 및 DB upsert
- 수집 당시의 KRX 원본 응답(JSON) 보관
- Django 관리 명령을 통한 수동 실행과 테스트

### 제외

- 실시간 시세·호가·체결 WebSocket 수집
- 외부 데이터 기반 주문 체결 또는 자동 주문
- 전체 종목의 장기 OHLCV backfill
- PostgreSQL 전환, CronJob, Kubernetes 배포

초기 구현은 Django 기본 SQLite를 사용한다.

---

## 2. 데이터 소스

| 용도 | KRX API | 사용 방법 |
|---|---|---|
| KOSPI 거래 순위 | 유가증권 일별매매정보 | 해당 거래일 전 종목 조회 |
| KOSDAQ 거래 순위 | 코스닥 일별매매정보 | 해당 거래일 전 종목 조회 |
| 종목명·시장 확인 | 유가증권/코스닥 종목기본정보 | 상위 100개 종목에 대해 조회·보강 |

인증키는 요청 헤더 `AUTH_KEY`로 전달한다. 애플리케이션은 `KRX_AUTH_KEY` 환경 변수에서만 읽고, 저장소·로그·응답에 노출하지 않는다.

---

## 3. 선별 규칙

1. 기준일은 API 데이터가 존재하는 가장 최근 거래일이다.
2. 장중 또는 장 마감 전 실행 시에는 당일이 아닌 직전 확정 거래일을 사용한다.
3. KOSPI·KOSDAQ 일별매매정보를 모두 가져와 하나의 목록으로 합친다.
4. 거래대금(`trading_value`)을 숫자로 변환해 내림차순 정렬한다.
5. 동률이면 거래량 내림차순, 종목코드 오름차순으로 결정성을 보장한다.
6. 상위 100개만 `market_daily`에 적재한다.
7. API 응답이 비어 있거나 한 시장 조회가 실패하면 부분 결과를 정상 데이터로 저장하지 않고 실행을 실패 처리한다.

`latest`는 시스템 날짜가 아니라 **KRX 응답이 존재하는 가장 최신 거래일**을 의미한다.

---

## 4. DB 모델 초안

```text
Symbol
  ticker             string, primary key       # KRX 6자리 코드
  name               string
  market             KOSPI | KOSDAQ
  updated_at         datetime

MarketDaily
  ticker             foreign key Symbol
  trade_date         date
  close_price        integer                   # KRW
  volume             integer
  trading_value      integer                   # KRW
  trading_value_rank integer                   # 1..100
  source             "krx_open_api"
  source_payload     JSON                      # 원본 레코드 보관
  imported_at        datetime
  unique             (ticker, trade_date)

ReferenceImportRun
  id                 UUID
  trade_date         date
  status             running | success | failed
  selected_count     integer
  source             "krx_open_api"
  error_message      text, nullable
  started_at         datetime
  finished_at        datetime, nullable
```

가격·거래량·거래대금은 모두 `int`로 보관한다. 금액에 `float`를 사용하지 않는다.

---

## 5. 구현 단위

### R1 — 설정과 KRX 클라이언트

- `KRX_AUTH_KEY` 설정 검증
- HTTP client timeout, 재시도, 오류 메시지 정규화
- KOSPI/KOSDAQ 일별매매정보 응답을 내부 레코드로 변환
- 외부 HTTP 호출은 mock으로 테스트

**완료 기준**: 인증키가 없으면 명확하게 실패하고, fixture 응답을 파싱할 수 있다.

### R2 — DB 모델과 적재 서비스

- `Symbol`, `MarketDaily`, `ReferenceImportRun` 모델·migration
- KOSPI/KOSDAQ 병합, 거래대금 상위 100개 선별
- 종목·일별 데이터 upsert와 원본 JSON 저장
- 동일 날짜 재실행 시 중복 행 없이 갱신

**완료 기준**: fixture 기준 정확히 100개가 순위와 함께 저장되고, 두 번째 실행도 idempotent하다.

### R3 — 관리 명령과 운영 피드백

```bash
make import-krx-top100
make import-krx-top100 TRADE_DATE=20260724
```

- `python manage.py import_krx_top100 [--trade-date YYYYMMDD]`
- 실행 결과: 기준일, 선택 수, 상위 10개, 실패 사유 출력
- 성공·실패 이력을 `ReferenceImportRun`에 기록

**완료 기준**: 수동 실행 한 번으로 최근 확정 거래일의 100개가 DB에 적재된다.

---

## 6. 서비스 API 활용 범위

참조 데이터를 읽는 API는 적재가 안정된 뒤에만 추가한다.

| API | 용도 |
|---|---|
| `GET /api/v1/reference/top100/` | 가장 최근 적재일의 상위 100개 목록 |
| `GET /api/v1/reference/top100/{ticker}/` | 종목의 최근 저장 일별 데이터 |

주문 API는 이 데이터를 조회하지 않는다. 기준가를 order book 초기화에 연결할 필요가 생길 때 별도 작업으로 설계한다.

---

## 7. 검증 시나리오

1. KOSPI·KOSDAQ fixture를 병합했을 때 거래대금 상위 100개가 정확히 선택된다.
2. 같은 거래대금은 거래량, 종목코드 순으로 안정적으로 정렬된다.
3. 거래대금이 빈 값·문자열·0인 응답의 처리 기준을 테스트로 고정한다.
4. 동일 거래일을 재수집해도 `MarketDaily` 중복이 생기지 않는다.
5. 한 시장 API가 실패하면 `ReferenceImportRun.status=failed`로 기록되고 상위 100개 데이터는 갱신되지 않는다.
6. 인증키와 원본 응답에 포함될 수 있는 민감 헤더가 로그에 출력되지 않는다.

---

## 8. 완료 후 다음 판단

이 작업이 끝난 뒤에도 외부 수집을 주문 처리 경로에 연결하지 않는다. 먼저 다음을 확인한다.

- 상위 100개 종목 풀만으로 부하 테스트 시나리오가 충분한가?
- 기준가·종목명·거래대금이 실제로 API 또는 프론트엔드에 필요한가?
- 수집 주기를 수동 실행에서 일 1회로 바꿀 근거가 있는가?

일 1회 자동 수집, PostgreSQL, KRX CronJob은 위 질문에 대한 필요가 확인될 때 별도 작업으로 추가한다.

---

*Last updated: 2026-07-25*
