"""
Global Trade & Peace Analysis System - 핵심 계산 모듈 (외부 라이브러리 없음)

보고서 Ⅵ장의 알고리즘을 그대로 구현한다.
  Trade_AB = Export_A→B + Import_A→B
  Dep_X    = (Trade_AB / TotalTrade_X) * 0.5 + (Trade_AB / GDP_X) * 0.5
  Score    = min(100, (Dep_A + Dep_B) / 2 * 1000)
"""
from dataclasses import dataclass

# ------------------------------------------------------------------
# 1. 데이터 (보고서 Ⅴ장, Ⅶ장 기준 / 단위: 십억 달러)
# ------------------------------------------------------------------
COUNTRIES = {
    "대한민국": {"gdp": 1712.8,  "total_trade": 1275.0, "feature": "무역 의존도가 높으며 제조업/반도체 중심 공급망 형성"},
    "미국":     {"gdp": 25462.7, "total_trade": 5310.0, "feature": "세계 최대 경제 대국, 글로벌 금융 및 소비 시장의 중심"},
    "중국":     {"gdp": 17963.2, "total_trade": 6310.0, "feature": "세계의 공장, 글로벌 공급망의 핵심 축"},
    "독일":     {"gdp": 4072.2,  "total_trade": 3120.0, "feature": "EU 최대 경제국, 정밀 제조업 중심"},
    "프랑스":   {"gdp": 2782.9,  "total_trade": 1410.0, "feature": "EU 핵심 회원국, 서비스업 및 항공/원자력 산업"},
    "일본":     {"gdp": 4231.1,  "total_trade": 1540.0, "feature": "첨단 소재 및 부품 산업 강국"},
}

# 갈등 수준: 낮음=1, 보통=2, 높음=3 (질적 평가를 순서형 값으로 변환)
CONFLICT_LEVELS = {"낮음": 1, "보통": 2, "높음": 3}

# 국가 쌍 데이터: (A, B) -> 양국 교역액, 갈등 수준, 설명, 보고서 기재 점수
PAIRS = {
    ("대한민국", "미국"): {"trade": 187.0, "conflict": "낮음",
        "note": "안보 동맹 기반, 핵심 첨단 기술 및 경제 협력 견고", "reported": 72},
    ("대한민국", "중국"): {"trade": 310.0, "conflict": "보통",
        "note": "무역 비중 매우 높으나 THAAD 마찰, 요소수 등 공급망 갈등 존재", "reported": 81},
    ("미국", "중국"):     {"trade": 690.0, "conflict": "높음",
        "note": "높은 상호 의존도에도 관세 전쟁 및 첨단 기술 패권 갈등 심화", "reported": 85},
    ("프랑스", "독일"):   {"trade": 170.0, "conflict": "낮음",
        "note": "EU 체제 하에 강력한 경제 통합 및 제도적 평화 유지", "reported": 78},
    ("일본", "미국"):     {"trade": 220.0, "conflict": "낮음",
        "note": "미일 안보 조약 및 공급망 협의체를 통한 안정적 협력", "reported": 70},
}

# ------------------------------------------------------------------
# 2. 계산 함수
# ------------------------------------------------------------------
W_TRADE = 0.5   # 총무역 대비 비중 가중치
W_GDP = 0.5     # GDP 대비 비중 가중치
SCALE = 1000    # 0~100 스케일링 계수 (보고서 기준)


def dependence(trade_ab: float, total_trade: float, gdp: float,
               w_trade: float = W_TRADE, w_gdp: float = W_GDP) -> float:
    """한 국가의 상대 의존 비중 Dep."""
    if total_trade <= 0 or gdp <= 0:
        raise ValueError("총무역액과 GDP는 0보다 커야 합니다.")
    return (trade_ab / total_trade) * w_trade + (trade_ab / gdp) * w_gdp


@dataclass
class PairResult:
    country_a: str
    country_b: str
    trade_ab: float
    share_a: float      # A의 총무역 중 B와의 교역 비중
    share_b: float
    gdp_ratio_a: float  # A의 GDP 대비 양국 교역액
    gdp_ratio_b: float
    dep_a: float
    dep_b: float
    raw_score: float    # 상한(100) 적용 전 점수
    score: float        # 최종 점수 (0~100)
    capped: bool        # 상한에 걸렸는지
    asymmetry: float    # 비대칭성 |Dep_A - Dep_B| / (Dep_A + Dep_B), 0~1


def analyze_pair(a: str, b: str, trade_ab: float, countries: dict = None,
                 scale: float = SCALE, w_trade: float = W_TRADE,
                 w_gdp: float = W_GDP) -> PairResult:
    countries = countries or COUNTRIES
    ca, cb = countries[a], countries[b]
    dep_a = dependence(trade_ab, ca["total_trade"], ca["gdp"], w_trade, w_gdp)
    dep_b = dependence(trade_ab, cb["total_trade"], cb["gdp"], w_trade, w_gdp)
    raw = (dep_a + dep_b) / 2 * scale
    total = dep_a + dep_b
    return PairResult(
        country_a=a, country_b=b, trade_ab=trade_ab,
        share_a=trade_ab / ca["total_trade"], share_b=trade_ab / cb["total_trade"],
        gdp_ratio_a=trade_ab / ca["gdp"], gdp_ratio_b=trade_ab / cb["gdp"],
        dep_a=dep_a, dep_b=dep_b,
        raw_score=raw, score=min(100.0, raw), capped=raw > 100,
        asymmetry=abs(dep_a - dep_b) / total if total else 0.0,
    )


def interpret(score: float, conflict: str = None) -> str:
    """점수와 (선택) 갈등 수준을 바탕으로 한 해석 문장."""
    if score >= 80:
        level = "매우 높은 상호 의존"
    elif score >= 60:
        level = "높은 상호 의존"
    elif score >= 40:
        level = "중간 수준의 상호 의존"
    else:
        level = "낮은 상호 의존"
    text = f"{level} 관계입니다."
    if conflict == "높음" and score >= 60:
        text += " 그럼에도 갈등이 높다면, 경제적 결합이 평화를 자동으로 보장하지 않는다는 사례(비선형성)로 볼 수 있습니다."
    elif conflict == "낮음" and score >= 60:
        text += " 제도적 협력(동맹·경제통합체 등)이 함께 작동해 갈등이 낮게 유지되는 사례로 볼 수 있습니다."
    elif conflict == "보통" and score >= 60:
        text += " 의존도가 높은 만큼 공급망을 둘러싼 취약성(Vulnerability)이 갈등 요인이 될 수 있습니다."
    return text


def correlation(xs, ys) -> float:
    """피어슨 상관계수 (외부 라이브러리 없이 계산)."""
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sxx * syy) ** 0.5


if __name__ == "__main__":
    print(f"{'국가 쌍':<14}{'교역액':>8}{'Dep_A':>9}{'Dep_B':>9}{'계산점수':>10}{'보고서':>8}")
    for (a, b), p in PAIRS.items():
        r = analyze_pair(a, b, p["trade"])
        print(f"{a}-{b:<8}{p['trade']:>8.1f}{r.dep_a:>9.4f}{r.dep_b:>9.4f}"
              f"{r.score:>10.1f}{p['reported']:>8}{'  (상한 적용)' if r.capped else ''}")
