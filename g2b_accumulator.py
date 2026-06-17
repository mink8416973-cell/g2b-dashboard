"""
조달 종합쇼핑몰 납품요구상세 누적 수집기  (getDlvrReqDtlInfoList)
- 1일 단위 API 제한을 '날짜 루프'로 우회 (백필 + 증분)
- 마스터 CSV에 누적, (납품요구번호 + 변경차수 + 물품순번) 기준 중복제거
- 중단 후 재실행 시 마지막 수집일 다음날부터 이어서 수집
- API는 D-1(어제)까지만 제공 → 루프 종료일은 '어제'

[사용 전]
  SERVICE_KEY 에 본인 디코딩 인증키 입력 후 실행:  python g2b_accumulator.py
"""

import os
import csv
import sys
import time
import datetime as dt
import requests

# ─────────────────────────────── 설정 ───────────────────────────────
SERVICE_KEY = os.environ.get("G2B_KEY") or "여기에_본인_디코딩_인증키_입력"  # GitHub Actions에선 Secret(G2B_KEY) 사용

ENDPOINT = "https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService/getDlvrReqDtlInfoList"

MASTER_CSV = "master_납품요구.csv"     # 누적 마스터 (이어받기 기준)
START_DATE = dt.date(2025, 1, 1)      # 백필 시작일
NUM_OF_ROWS = 100                     # 페이지당 행 수
SLEEP_SEC = 0.2                       # 호출 간 대기
MAX_RETRY = 3

# (선택) 조회 단계에서 미리 좁히고 싶으면 채움. 비우면 그 날 전체를 받아 로컬 필터.
FILTER_DTIL_PRDCT_NM = "보안소프트웨어"     # 세부품명 (dtilPrdctClsfcNoNm) — 이 분류만 수집

# 중복제거 키
KEY_FIELDS = ("dlvrReqNo", "dlvrReqChgOrd", "prdctSno")

# 저장 컬럼 = 실제 응답 필드명
COLUMNS = [
    "dlvrReqNo", "dlvrReqChgOrd", "prdctSno", "dlvrReqRcptDate",
    "dminsttCd", "dminsttNm", "dmndInsttDivNm", "dminsttRgnNm",
    "dlvrReqNm", "corpNm", "cntrctCorpBizno", "corpEntrprsDivNmNm",
    "prdctClsfcNo", "prdctClsfcNoNm", "dtilPrdctClsfcNo", "dtilPrdctClsfcNoNm",
    "prdctIdntNo", "prdctIdntNoNm", "prdctUnit", "dlvrTmlmtDate",
    "cntrctNo", "cntrctChgOrd", "cntrctCnclsStleNm",
    "prdctUprc", "prdctQty", "prdctAmt", "incdecQty", "incdecAmt",
    "dlvrReqQty", "dlvrReqAmt",
    "masYn", "exclcProdctYn", "cnstwkMtrlDrctPurchsObjYn",
    "smetprCmptProdctYn", "fnlDlvrReqYn", "brnofceNm", "IntlCntrctDlvrReqDate",
]

# 컬럼 → 한글 헤더 (대시보드 원천 시트와 동일 명칭)
KOR_HEADER = {
    "dlvrReqNo": "납품요구번호", "dlvrReqChgOrd": "납품요구변경차수",
    "prdctSno": "납품요구물품순번", "dlvrReqRcptDate": "납품요구접수일자",
    "dminsttCd": "수요기관코드", "dminsttNm": "수요기관명",
    "dmndInsttDivNm": "소관구분", "dminsttRgnNm": "수요기관지역명",
    "dlvrReqNm": "요청명", "corpNm": "업체명", "cntrctCorpBizno": "업체사업자등록번호",
    "corpEntrprsDivNmNm": "기업형태구분", "prdctClsfcNo": "물품분류번호",
    "prdctClsfcNoNm": "물품분류명", "dtilPrdctClsfcNo": "세부품명번호",
    "dtilPrdctClsfcNoNm": "세부품명", "prdctIdntNo": "물품식별번호",
    "prdctIdntNoNm": "물품식별명", "prdctUnit": "납품단위", "dlvrTmlmtDate": "납품기한일자",
    "cntrctNo": "계약번호", "cntrctChgOrd": "계약변경차수", "cntrctCnclsStleNm": "계약유형",
    "prdctUprc": "단가", "prdctQty": "수량", "prdctAmt": "금액",
    "incdecQty": "증감수량", "incdecAmt": "증감금액",
    "dlvrReqQty": "납품요구수량", "dlvrReqAmt": "납품요구금액",
    "masYn": "MAS여부", "exclcProdctYn": "우수제품여부",
    "cnstwkMtrlDrctPurchsObjYn": "직접구매대상여부",
    "smetprCmptProdctYn": "중소기업경쟁제품여부", "fnlDlvrReqYn": "최종납품요구여부",
    "brnofceNm": "지청", "IntlCntrctDlvrReqDate": "국제계약납품요구일자",
}
# ─────────────────────────────────────────────────────────────────────


def build_params(day_str, page_no):
    p = {
        "serviceKey": SERVICE_KEY,
        "type": "json",
        "numOfRows": NUM_OF_ROWS,
        "pageNo": page_no,
        "inqryDiv": "1",
        "inqryBgnDate": day_str,
        "inqryEndDate": day_str,
    }
    if FILTER_DTIL_PRDCT_NM:
        p["dtilPrdctClsfcNoNm"] = FILTER_DTIL_PRDCT_NM
    return p


def fetch_day(day):
    """하루치 전 페이지를 받아 레코드 리스트로 반환."""
    day_str = day.strftime("%Y%m%d")
    rows, page_no = [], 1
    while True:
        data = None
        for attempt in range(1, MAX_RETRY + 1):
            try:
                r = requests.get(ENDPOINT, params=build_params(day_str, page_no), timeout=30)
                r.raise_for_status()
                data = r.json()
                break
            except Exception as e:
                if attempt == MAX_RETRY:
                    print(f"  ! {day_str} p{page_no} 실패: {e}", file=sys.stderr)
                    return rows
                time.sleep(1.5 * attempt)

        body = (data or {}).get("response", {}).get("body", {})
        total = int(body.get("totalCount", 0) or 0)
        if total == 0:
            break

        items = body.get("items") or {}
        item = items.get("item") if isinstance(items, dict) else items
        if item is None:
            break
        if isinstance(item, dict):
            item = [item]
        rows.extend(item)

        if page_no * NUM_OF_ROWS >= total:
            break
        page_no += 1
        time.sleep(SLEEP_SEC)
    return rows


def row_key(rec):
    return tuple(str(rec.get(f, "")) for f in KEY_FIELDS)


def load_master():
    existing, last_date = {}, None
    if os.path.exists(MASTER_CSV):
        with open(MASTER_CSV, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            inv = {v: k for k, v in KOR_HEADER.items()}  # 한글헤더 → 영문키
            for kor_row in reader:
                rec = {inv.get(k, k): v for k, v in kor_row.items()}
                existing[row_key(rec)] = rec
                d = rec.get("dlvrReqRcptDate", "")
                if d and (last_date is None or d > last_date):
                    last_date = d
    return existing, last_date


def save_master(records):
    with open(MASTER_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([KOR_HEADER[c] for c in COLUMNS])
        for rec in records.values():
            w.writerow([rec.get(c, "") for c in COLUMNS])


def main():
    existing, last_date = load_master()
    start = START_DATE
    if last_date:
        start = dt.datetime.strptime(last_date, "%Y%m%d").date() + dt.timedelta(days=1)

    end = dt.date.today() - dt.timedelta(days=1)   # API는 D-1까지만 제공
    if start > end:
        print(f"이미 최신({last_date})입니다. 수집할 신규일 없음.")
        return

    print(f"수집 기간: {start} ~ {end}  (기존 {len(existing)}건 위에 추가)")
    new_cnt, day = 0, start
    while day <= end:
        recs = fetch_day(day)
        for rec in recs:
            existing[row_key(rec)] = rec
        if recs:
            new_cnt += len(recs)
            print(f"  {day} : {len(recs):>4}건")
        if day.day == 1:
            save_master(existing)
        day += dt.timedelta(days=1)
        time.sleep(SLEEP_SEC)

    save_master(existing)
    print(f"완료. 신규/갱신 {new_cnt}건 반영 → 총 {len(existing)}건 → {MASTER_CSV}")


if __name__ == "__main__":
    main()
