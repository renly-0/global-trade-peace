"""
실시간 통계 조회 모듈 (인터넷 연결 필요, API 키 불필요)

- GDP            : World Bank Open Data API  (지표 NY.GDP.MKTP.CD, 현재 달러)
- 총무역액       : World Bank WITS API       (상품 수출 XPRT-TRD-VL + 수입 MPRT-TRD-VL, UN Comtrade 기반)
                   WITS에 없으면 World Bank 지표 TX.VAL.MRCH.CD.WT / TM.VAL.MRCH.CD.WT 사용
- 양국 교역액    : World Bank WITS API       (A가 보고한 A→B 수출 + B→A 수입, 없으면 B의 보고값으로 대체)

공식 통계는 발표까지 보통 1~2년 걸리므로, '실시간'은 '조회 시점에 공개된 가장 최신 연도'를 뜻합니다.
모든 금액은 십억 달러(B$) 단위로 반환합니다.
"""
import re
import time
import datetime as dt
import xml.etree.ElementTree as ET

import requests

WITS_BASE = "https://wits.worldbank.org/API/V1/SDMX/V21/rest/data/df_wits_tradestats_trade"
WB_BASE = "https://api.worldbank.org/v2"
EXPORT, IMPORT = "XPRT-TRD-VL", "MPRT-TRD-VL"      # 단위: 천 달러
TIMEOUT = 30


class DataError(Exception):
    """사용자에게 그대로 보여줄 수 있는 조회 오류."""


# ------------------------------------------------------------------
# 국가 이름 -> ISO3 코드
# ------------------------------------------------------------------
KOREAN = {
    "KOR": ["대한민국", "한국", "남한", "korea", "southkorea", "republicofkorea"],
    "USA": ["미국", "미합중국", "usa", "us", "unitedstates", "america"],
    "CHN": ["중국", "china"], "JPN": ["일본", "japan"], "DEU": ["독일", "germany"],
    "FRA": ["프랑스", "france"], "GBR": ["영국", "uk", "unitedkingdom", "britain"],
    "ITA": ["이탈리아"], "ESP": ["스페인"], "CAN": ["캐나다"], "MEX": ["멕시코"],
    "BRA": ["브라질"], "ARG": ["아르헨티나"], "CHL": ["칠레"], "PER": ["페루"], "COL": ["콜롬비아"],
    "RUS": ["러시아"], "IND": ["인도"], "IDN": ["인도네시아"], "VNM": ["베트남"], "THA": ["태국"],
    "MYS": ["말레이시아"], "SGP": ["싱가포르"], "PHL": ["필리핀"], "HKG": ["홍콩"],
    "AUS": ["호주", "오스트레일리아"], "NZL": ["뉴질랜드"], "TUR": ["튀르키예", "터키"],
    "SAU": ["사우디아라비아", "사우디"], "ARE": ["아랍에미리트", "uae"], "IRN": ["이란"],
    "ISR": ["이스라엘"], "EGY": ["이집트"], "ZAF": ["남아프리카공화국", "남아공"], "NGA": ["나이지리아"],
    "KEN": ["케냐"], "NLD": ["네덜란드"], "BEL": ["벨기에"], "CHE": ["스위스"], "SWE": ["스웨덴"],
    "NOR": ["노르웨이"], "DNK": ["덴마크"], "FIN": ["핀란드"], "POL": ["폴란드"], "CZE": ["체코"],
    "HUN": ["헝가리"], "AUT": ["오스트리아"], "GRC": ["그리스"], "PRT": ["포르투갈"], "IRL": ["아일랜드"],
    "UKR": ["우크라이나"], "KAZ": ["카자흐스탄"], "PAK": ["파키스탄"], "BGD": ["방글라데시"],
    "MNG": ["몽골"], "UZB": ["우즈베키스탄"], "QAT": ["카타르"], "KWT": ["쿠웨이트"], "IRQ": ["이라크"],
    "DZA": ["알제리"], "MAR": ["모로코"], "ETH": ["에티오피아"], "GHA": ["가나"], "LKA": ["스리랑카"],
    "MMR": ["미얀마"], "KHM": ["캄보디아"], "LAO": ["라오스"], "NPL": ["네팔"], "ROU": ["루마니아"],
    "BGR": ["불가리아"], "SRB": ["세르비아"], "HRV": ["크로아티아"], "SVK": ["슬로바키아"],
    "SVN": ["슬로베니아"], "LTU": ["리투아니아"], "LVA": ["라트비아"], "EST": ["에스토니아"],
    "ISL": ["아이슬란드"], "LUX": ["룩셈부르크"], "VEN": ["베네수엘라"], "ECU": ["에콰도르"],
    "URY": ["우루과이"], "PAN": ["파나마"], "DOM": ["도미니카공화국"], "GEO": ["조지아"],
    "AZE": ["아제르바이잔"], "ARM": ["아르메니아"], "BLR": ["벨라루스"],
}
_ALIAS = {}
for _iso, _names in KOREAN.items():
    for _n in _names:
        _ALIAS[re.sub(r"[\s\.\-]", "", _n).lower()] = _iso


def display_name(iso, english=None):
    """ISO3 코드의 표시 이름 (한국어 우선)."""
    if iso in KOREAN:
        return KOREAN[iso][0]
    return english or iso


def resolve_country(text, wb_countries=None):
    """입력 문자열 -> (ISO3, 표시 이름). 찾지 못하면 DataError.

    wb_countries: World Bank 국가 목록 [{'id': 'KOR', 'name': 'Korea, Rep.'}, ...] (영문 이름 검색용, 선택)
    """
    t = (text or "").strip()
    if not t:
        raise DataError("국가 이름을 입력해 주세요.")
    key = re.sub(r"[\s\.\-]", "", t).lower()
    if key in _ALIAS:
        iso = _ALIAS[key]
        return iso, display_name(iso)
    if re.fullmatch(r"[A-Za-z]{3}", t):
        iso = t.upper()
        if wb_countries:
            for c in wb_countries:
                if c["id"] == iso:
                    return iso, display_name(iso, c["name"])
        elif iso in KOREAN:
            return iso, display_name(iso)
    if wb_countries:
        low = t.lower()
        exact = [c for c in wb_countries if c["name"].lower() == low]
        part = [c for c in wb_countries if low in c["name"].lower()]
        hit = exact or (part if len(part) == 1 else [])
        if hit:
            return hit[0]["id"], display_name(hit[0]["id"], hit[0]["name"])
        if len(part) > 1:
            names = ", ".join(c["name"] for c in part[:5])
            raise DataError(f"‘{t}’와 비슷한 나라가 여러 개입니다: {names} … 더 정확히 입력해 주세요.")
    raise DataError(f"‘{t}’을(를) 국가로 인식하지 못했습니다. 한국어 국가명, 영어 국가명 또는 ISO 3자리 코드(예: IND)로 입력해 주세요.")


# ------------------------------------------------------------------
# HTTP
# ------------------------------------------------------------------
def _get(url, params=None, retries=2):
    last = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT,
                             headers={"User-Agent": "global-trade-peace/1.0"})
            if r.status_code in (429, 500, 502, 503, 504) and i < retries:
                time.sleep(1.5 * (i + 1))
                continue
            return r
        except requests.RequestException as e:      # 네트워크 오류
            last = e
            if i < retries:
                time.sleep(1.5 * (i + 1))
    raise DataError(f"인터넷 연결 또는 서버 오류로 자료를 가져오지 못했습니다. ({type(last).__name__})")


# ------------------------------------------------------------------
# 파서
# ------------------------------------------------------------------
def _local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_sdmx(xml_text):
    """WITS SDMX-ML(GenericData) -> [(시리즈키 dict, {연도: 값})]"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for series in root.iter():
        if _local(series.tag) != "Series":
            continue
        key, obs = {}, {}
        for child in series:
            name = _local(child.tag)
            if name == "SeriesKey":
                for v in child:
                    key[v.get("id")] = v.get("value")
            elif name == "Obs":
                year, val = None, None
                for o in child:
                    n = _local(o.tag)
                    if n == "ObsDimension":
                        year = o.get("value")
                    elif n == "ObsValue":
                        val = o.get("value")
                try:
                    obs[int(year)] = float(val)
                except (TypeError, ValueError):
                    pass
        out.append((key, obs))
    return out


def wits_series(reporter, partner, indicator, start, end):
    """WITS 총(Total) 상품 무역 시계열 {연도: 천 달러}. 데이터가 없으면 {}."""
    for product in ("Total", "all"):
        url = f"{WITS_BASE}/A.{reporter.lower()}.{partner.lower()}.{product}.{indicator}/"
        r = _get(url, params={"startPeriod": start, "endPeriod": end})
        if r.status_code != 200:
            continue
        for key, obs in parse_sdmx(r.text):
            if (key.get("PRODUCTCODE") or "").lower() == "total" and obs:
                return obs
    return {}


def wb_series(iso, indicator, start, end):
    """World Bank 지표 시계열 {연도: 값}. 데이터가 없으면 {}."""
    r = _get(f"{WB_BASE}/country/{iso}/indicator/{indicator}",
             params={"format": "json", "date": f"{start}:{end}", "per_page": 100})
    if r.status_code != 200:
        return {}
    try:
        data = r.json()
    except ValueError:
        return {}
    if not isinstance(data, list) or len(data) < 2 or not data[1]:
        return {}
    out = {}
    for row in data[1]:
        if row.get("value") is not None:
            try:
                out[int(row["date"])] = float(row["value"])
            except (TypeError, ValueError):
                pass
    return out


def wb_countries():
    """World Bank 국가 목록(집계 지역 제외). 영문 이름 검색용."""
    r = _get(f"{WB_BASE}/country", params={"format": "json", "per_page": 400})
    try:
        rows = r.json()[1]
    except (ValueError, IndexError, TypeError, KeyError):
        return []
    return [{"id": c["id"], "name": c["name"]} for c in rows
            if c.get("region", {}).get("value") != "Aggregates"]


# ------------------------------------------------------------------
# 조회 함수 (금액은 십억 달러 단위)
# ------------------------------------------------------------------
def _years():
    end = dt.date.today().year
    return end - 9, end


def _sum_series(a, b):
    """두 시계열에서 공통 연도만 합산."""
    return {y: a[y] + b[y] for y in a if y in b}


def fetch_country(iso):
    """한 국가의 GDP와 총 상품 무역액 시계열: {'gdp': {연도: B$}, 'trade': {연도: B$}, 'trade_source': str}"""
    start, end = _years()
    gdp = {y: v / 1e9 for y, v in wb_series(iso, "NY.GDP.MKTP.CD", start, end).items()}
    trade = _sum_series(wits_series(iso, "wld", EXPORT, start, end),
                        wits_series(iso, "wld", IMPORT, start, end))
    trade = {y: v / 1e6 for y, v in trade.items()}                 # 천 달러 -> 십억 달러
    source = "WITS (UN Comtrade 기반)"
    if not trade:
        trade = _sum_series(wb_series(iso, "TX.VAL.MRCH.CD.WT", start, end),
                            wb_series(iso, "TM.VAL.MRCH.CD.WT", start, end))
        trade = {y: v / 1e9 for y, v in trade.items()}
        source = "World Bank WDI (상품 수출입)"
    return {"gdp": gdp, "trade": trade, "trade_source": source}


def fetch_pair(a, b):
    """두 나라 사이의 상품 교역액 시계열: {'trade': {연도: B$}, 'mirrored': {연도: bool}}
    A가 보고한 값을 우선 쓰고, 없는 연도는 B가 보고한 값(미러 데이터)으로 채운다."""
    start, end = _years()
    a_rep = _sum_series(wits_series(a, b, EXPORT, start, end), wits_series(a, b, IMPORT, start, end))
    b_rep = _sum_series(wits_series(b, a, EXPORT, start, end), wits_series(b, a, IMPORT, start, end))
    trade, mirrored = {}, {}
    for y in sorted(set(a_rep) | set(b_rep)):
        if y in a_rep:
            trade[y], mirrored[y] = a_rep[y] / 1e6, False
        else:
            trade[y], mirrored[y] = b_rep[y] / 1e6, True
    return {"trade": trade, "mirrored": mirrored}


def assemble(ca, cb, pair, year=None):
    """국가 A·B와 양국 교역 시계열을 하나의 기준 연도로 합친다.

    year=None 이면 모든 값이 존재하는 가장 최근 연도를 자동 선택한다."""
    common = set(ca["gdp"]) & set(cb["gdp"]) & set(ca["trade"]) & set(cb["trade"]) & set(pair["trade"])
    if year is not None:
        if year not in common:
            raise DataError(f"{year}년 자료가 모두 존재하지 않습니다. 자동(최신)으로 조회해 보세요.")
    else:
        if not common:
            missing = []
            if not ca["gdp"] or not cb["gdp"]:
                missing.append("GDP")
            if not ca["trade"] or not cb["trade"]:
                missing.append("총무역액")
            if not pair["trade"]:
                missing.append("양국 교역액")
            what = "·".join(missing) if missing else "같은 연도의 자료"
            raise DataError(f"두 나라의 {what}을(를) 공개 통계에서 찾지 못했습니다. (WITS/세계은행에 자료가 없는 나라일 수 있습니다.)")
        year = max(common)
    return {
        "year": year,
        "gdp_a": ca["gdp"][year], "gdp_b": cb["gdp"][year],
        "tot_a": ca["trade"][year], "tot_b": cb["trade"][year],
        "trade": pair["trade"][year], "mirrored": pair["mirrored"][year],
        "trade_source_a": ca["trade_source"], "trade_source_b": cb["trade_source"],
        "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
