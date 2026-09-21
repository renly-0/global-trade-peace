"""
Global Trade & Peace Analysis System (실시간 통계 버전)
두 나라 이름만 입력하면 World Bank / WITS(UN Comtrade 기반)에서 최신 GDP·무역 통계를 자동으로 가져와
경제적 상호 의존도를 계산합니다.

실행:  pip install -r requirements.txt
       streamlit run app.py
"""
import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import core
import data_live as dl

st.set_page_config(page_title="Global Trade & Peace (실시간)", page_icon="🌐", layout="wide")

# ------------------------------------------------------------------
# 캐시된 조회 (6시간) — 같은 나라를 다시 입력해도 API를 반복 호출하지 않는다
# ------------------------------------------------------------------
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cached_wb_countries():
    return dl.wb_countries()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cached_country(iso):
    return dl.fetch_country(iso)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cached_pair(a, b):
    return dl.fetch_pair(a, b)


def resolve(text):
    """한국어/영어 이름, ISO 코드를 (ISO3, 표시 이름)으로. 내장 목록에 없으면 세계은행 국가 목록을 검색."""
    try:
        return dl.resolve_country(text)
    except dl.DataError:
        return dl.resolve_country(text, cached_wb_countries())


# ------------------------------------------------------------------
# 보고서에 이미 정리된 국가 쌍의 갈등 수준 (ISO 코드 쌍 -> (수준, 설명))
# ------------------------------------------------------------------
NAME_TO_ISO = {"대한민국": "KOR", "미국": "USA", "중국": "CHN", "독일": "DEU", "프랑스": "FRA", "일본": "JPN"}
KNOWN_CONFLICT = {}
for (n1, n2), p in core.PAIRS.items():
    KNOWN_CONFLICT[frozenset((NAME_TO_ISO[n1], NAME_TO_ISO[n2]))] = (p["conflict"], p["note"])
LEVELS = ["미분류", "낮음", "보통", "높음"]

ss = st.session_state
ss.setdefault("records", {})      # {frozenset(iso): 기록}
ss.setdefault("current", None)    # 현재 보고 있는 기록의 키
ss.setdefault("error", None)

# ------------------------------------------------------------------
# 사이드바
# ------------------------------------------------------------------
st.sidebar.title("🌐 Global Trade & Peace")
st.sidebar.caption("두 나라를 입력하면 최신 공개 통계를 자동으로 조회합니다.")

cy = dt.date.today().year
with st.sidebar.form("query"):
    a_txt = st.text_input("국가 A", value="대한민국", help="한국어·영어 이름 또는 ISO 3자리 코드 (예: 인도 / India / IND)")
    b_txt = st.text_input("국가 B", value="미국")
    submitted = st.form_submit_button("분석하기")

with st.sidebar.expander("⚙️ 고급 설정 (선택)"):
    year_choice = st.selectbox("기준 연도", ["자동(가장 최신)"] + [str(y) for y in range(cy - 1, cy - 9, -1)])
    w_trade = st.slider("총무역 대비 비중 가중치", 0.0, 1.0, core.W_TRADE, 0.05)
    w_gdp = round(1.0 - w_trade, 2)
    st.caption(f"GDP 대비 비중 가중치 = {w_gdp}")
    scale = st.number_input("스케일링 계수", min_value=1.0, value=float(core.SCALE), step=100.0)

st.sidebar.caption("예: 인도, India, IND, 베트남, 독일 …")


def run_query(a_text, b_text):
    ss.error = None
    try:
        iso_a, name_a = resolve(a_text)
        iso_b, name_b = resolve(b_text)
        if iso_a == iso_b:
            raise dl.DataError("서로 다른 두 나라를 입력해 주세요.")
        with st.spinner("최신 통계를 조회하는 중입니다… (처음 조회하는 나라는 몇 초 걸릴 수 있어요)"):
            ca, cb = cached_country(iso_a), cached_country(iso_b)
            pair = cached_pair(iso_a, iso_b)
            year = None if year_choice.startswith("자동") else int(year_choice)
            rec = dl.assemble(ca, cb, pair, year)
        key = frozenset((iso_a, iso_b))
        old = ss.records.get(key, {})
        known = KNOWN_CONFLICT.get(key)
        rec.update({
            "iso_a": iso_a, "iso_b": iso_b, "name_a": name_a, "name_b": name_b,
            "conflict": old.get("conflict") or (known[0] if known else "미분류"),
            "note": old.get("note") or (known[1] if known else ""),
        })
        ss.records[key] = rec
        ss.current = key
    except dl.DataError as e:
        ss.error = str(e)
    except Exception as e:                                   # 예기치 못한 오류도 화면에 안내
        ss.error = f"조회 중 오류가 발생했습니다: {type(e).__name__}. 잠시 후 다시 시도해 주세요."


if submitted:
    run_query(a_txt, b_txt)
elif ss.current is None and ss.error is None:
    run_query(a_txt, b_txt)          # 첫 화면: 기본 예시(대한민국–미국) 자동 조회


def analyze(rec):
    countries = {rec["name_a"]: {"gdp": rec["gdp_a"], "total_trade": rec["tot_a"]},
                 rec["name_b"]: {"gdp": rec["gdp_b"], "total_trade": rec["tot_b"]}}
    return core.analyze_pair(rec["name_a"], rec["name_b"], rec["trade"], countries, scale, w_trade, w_gdp)


# ------------------------------------------------------------------
# 본문
# ------------------------------------------------------------------
st.title("세계화는 국가 간 평화에 어떤 영향을 미칠까?")
st.caption("Global Trade & Peace Analysis System · 데이터: World Bank Open Data(GDP), WITS/UN Comtrade(상품 무역)")

if ss.error:
    st.error(ss.error)

tab1, tab2, tab3, tab4 = st.tabs(["🔍 두 국가 분석", "📊 조회한 국가 쌍 비교", "✅ 보고서 값 검증", "📘 자료·공식·한계"])

# ---------------------------- TAB 1 ----------------------------
with tab1:
    rec = ss.records.get(ss.current) if ss.current else None
    if rec is None:
        st.info("왼쪽에서 두 나라를 입력하고 ‘분석하기’를 눌러 주세요.")
    else:
        r = analyze(rec)
        na, nb = rec["name_a"], rec["name_b"]

        left, right = st.columns(2)
        with left:
            fig = go.Figure(go.Indicator(
                mode="gauge+number", value=r.score,
                title={"text": f"{na} – {nb} 상호 의존도 ({rec['year']}년)"},
                number={"suffix": "점", "valueformat": ".1f"},
                gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#2b6cb0"},
                       "steps": [{"range": [0, 40], "color": "#e6f0fa"}, {"range": [40, 60], "color": "#cfe2f5"},
                                 {"range": [60, 80], "color": "#a9cbec"}, {"range": [80, 100], "color": "#7fb0e0"}]}))
            fig.update_layout(height=320, margin=dict(t=60, b=10, l=30, r=30))
            st.plotly_chart(fig)
            if r.capped:
                st.info(f"계산 원점수는 {r.raw_score:.1f}점이지만 최대 100점 상한이 적용되었습니다.")
        with right:
            c1, c2 = st.columns(2)
            c1.metric("양국 교역액", f"${rec['trade']:,.1f}B")
            c2.metric("기준 연도", f"{rec['year']}년")
            c3, c4 = st.columns(2)
            c3.metric(f"{na} 의존 비중 (Dep)", f"{r.dep_a:.4f}")
            c4.metric(f"{nb} 의존 비중 (Dep)", f"{r.dep_b:.4f}")
            st.metric("의존의 비대칭성", f"{r.asymmetry * 100:.0f}%",
                      help="두 나라의 Dep 차이를 합으로 나눈 값. 클수록 한쪽이 더 크게 의존(취약)합니다.")

            # 갈등 수준은 통계로 자동 산출할 수 없으므로 선택 항목 (보고서의 5개 쌍은 기본 입력됨)
            idx = LEVELS.index(rec["conflict"]) if rec["conflict"] in LEVELS else 0
            sel = st.selectbox("이 국가 쌍의 갈등 수준 (선택 사항)", LEVELS, index=idx,
                               key="conf_" + "_".join(sorted(ss.current)),
                               help="공개 통계로 자동 산출되지 않는 질적 평가입니다. 선택하면 ‘비교’ 탭의 산점도에 반영됩니다.")
            if sel != rec["conflict"]:
                rec["conflict"] = sel
                st.rerun()
            conflict = rec["conflict"] if rec["conflict"] in core.CONFLICT_LEVELS else None
            more = na if r.dep_a > r.dep_b else nb
            st.write(f"**해석:** {core.interpret(r.score, conflict)} 의존 비중은 **{more}** 쪽이 더 큽니다.")
            if rec["note"]:
                st.write(f"**갈등 현황(보고서):** {rec['note']}")

        st.subheader("의존도 구성 요소 비교")
        comp = pd.DataFrame({"지표": ["총무역 대비 교역 비중", "GDP 대비 교역 비중"],
                             na: [r.share_a * 100, r.gdp_ratio_a * 100],
                             nb: [r.share_b * 100, r.gdp_ratio_b * 100]})
        bar = go.Figure()
        for c in (na, nb):
            bar.add_bar(name=c, x=comp["지표"], y=comp[c], text=[f"{v:.1f}%" for v in comp[c]], textposition="outside")
        bar.update_layout(barmode="group", yaxis_title="%", height=360, margin=dict(t=20))
        st.plotly_chart(bar)

        st.subheader("사용된 실제 자료")
        used = pd.DataFrame([
            {"구분": na, "GDP($B)": round(rec["gdp_a"], 1), "총무역액($B)": round(rec["tot_a"], 1), "무역 출처": rec["trade_source_a"]},
            {"구분": nb, "GDP($B)": round(rec["gdp_b"], 1), "총무역액($B)": round(rec["tot_b"], 1), "무역 출처": rec["trade_source_b"]},
        ])
        st.dataframe(used, hide_index=True)
        mirror = " (상대국이 보고한 값으로 대체됨)" if rec["mirrored"] else ""
        st.caption(f"양국 교역액 ${rec['trade']:,.1f}B{mirror} · 기준 연도 {rec['year']}년 · 조회 시각 {rec['fetched_at']} · "
                   "GDP는 명목(현재 달러), 무역액은 상품(재화) 수출입 합계입니다.")

# ---------------------------- TAB 2 ----------------------------
with tab2:
    rows = []
    for key, rec in ss.records.items():
        r = analyze(rec)
        rows.append({"국가 관계": f"{rec['name_a']} – {rec['name_b']}", "기준 연도": rec["year"],
                     "양국 교역액($B)": round(rec["trade"], 1), "상호 의존도 점수": round(r.score, 1),
                     "원점수(상한 전)": round(r.raw_score, 1), "비대칭성(%)": round(r.asymmetry * 100),
                     "갈등 수준": rec["conflict"], "조회 시각": rec["fetched_at"]})
    if not rows:
        st.info("아직 조회한 국가 쌍이 없습니다. 왼쪽에서 나라를 입력하면 여기에 계속 쌓입니다.")
    else:
        df = pd.DataFrame(rows)
        st.subheader("이번 세션에서 조회한 국가 쌍")
        st.dataframe(df, hide_index=True)
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("상호 의존도 순위")
            srt = df.sort_values("상호 의존도 점수")
            cmap = {"낮음": "#4c9f70", "보통": "#e0a030", "높음": "#d64545", "미분류": "#7a8794"}
            fig = go.Figure(go.Bar(x=srt["상호 의존도 점수"], y=srt["국가 관계"], orientation="h",
                                   marker_color=[cmap[c] for c in srt["갈등 수준"]],
                                   text=srt["갈등 수준"], textposition="inside"))
            fig.update_layout(xaxis=dict(range=[0, 100]), height=380, margin=dict(t=10))
            st.plotly_chart(fig)
        with col2:
            st.subheader("의존도 vs 갈등 수준")
            lv = df[df["갈등 수준"].isin(core.CONFLICT_LEVELS)].copy()
            if len(lv) == 0:
                st.caption("갈등 수준을 선택한 국가 쌍이 없습니다.")
            else:
                lv["y"] = lv["갈등 수준"].map(core.CONFLICT_LEVELS)
                sc = go.Figure(go.Scatter(x=lv["상호 의존도 점수"], y=lv["y"], mode="markers+text", text=lv["국가 관계"],
                                          textposition="top center",
                                          marker=dict(size=14, color=lv["y"], colorscale="RdYlGn_r")))
                sc.update_layout(xaxis_title="상호 의존도 점수",
                                 yaxis=dict(tickvals=[1, 2, 3], ticktext=["낮음", "보통", "높음"], range=[0.5, 3.5]),
                                 height=380, margin=dict(t=10))
                st.plotly_chart(sc)
                if len(lv) >= 3:
                    rho = core.correlation(lv["상호 의존도 점수"].tolist(), lv["y"].tolist())
                    st.write(f"**상관계수:** {rho:.2f} (표본 {len(lv)}쌍)")
                    st.caption("표본이 적어 통계적 결론을 내리기는 어렵습니다.")

# ---------------------------- TAB 3 ----------------------------
with tab3:
    st.subheader("보고서 표의 점수와 공식 계산값 비교")
    st.write("보고서 Ⅴ·Ⅶ장에 수록된 자료(고정값)에 Ⅵ장 공식을 그대로 적용한 결과입니다. 실시간 조회값과는 무관합니다.")
    vr = []
    for (a, b), p in core.PAIRS.items():
        res = core.analyze_pair(a, b, p["trade"])
        vr.append({"국가 관계": f"{a} – {b}", "보고서 기재 점수": p["reported"], "계산 원점수": round(res.raw_score, 1),
                   "계산 최종 점수": round(res.score, 1), "차이(계산−보고서)": round(res.score - p["reported"], 1)})
    vdf = pd.DataFrame(vr)
    st.dataframe(vdf, hide_index=True)
    fig = go.Figure()
    fig.add_bar(name="보고서 기재 점수", x=vdf["국가 관계"], y=vdf["보고서 기재 점수"])
    fig.add_bar(name="계산 최종 점수", x=vdf["국가 관계"], y=vdf["계산 최종 점수"])
    fig.update_layout(barmode="group", yaxis=dict(range=[0, 105]), height=360, margin=dict(t=10))
    st.plotly_chart(fig)
    st.warning("공식을 그대로 계산하면 보고서 Ⅶ장 표의 점수와 일치하지 않습니다. 특히 한국–중국이 가장 높고(상한 100점) "
               "미국–중국은 그보다 낮게 나옵니다. 제출 전에 표의 점수 또는 Ⅷ장 해석을 함께 수정하세요.")

# ---------------------------- TAB 4 ----------------------------
with tab4:
    st.subheader("자료 출처")
    st.markdown("""
- **GDP**: World Bank Open Data API, 지표 `NY.GDP.MKTP.CD` (명목 GDP, 현재 달러)
- **총무역액·양국 교역액**: World Bank WITS API (UN Comtrade 기반 상품 무역, 수출+수입). WITS에 없으면 World Bank 지표 `TX.VAL.MRCH.CD.WT`, `TM.VAL.MRCH.CD.WT`로 대체
- **양국 교역액**: 국가 A가 보고한 값을 우선 사용하고, 없는 연도는 국가 B가 보고한 값으로 대체합니다(화면에 표시).
- **‘실시간’의 의미**: 조회하는 순간 API에서 가져오지만, 공식 통계는 발표까지 보통 1~2년 걸려 가장 최신 연도는 지난해·재작년입니다. 두 나라의 GDP·무역·교역 자료가 모두 있는 가장 최근 연도를 자동으로 씁니다.
- 같은 나라는 6시간 동안 캐시되어 다시 조회하지 않습니다.
""")
    st.subheader("계산 공식")
    st.latex(r"Trade_{AB} = Export_{A \rightarrow B} + Import_{A \rightarrow B}")
    st.latex(r"Dep_X = \frac{Trade_{AB}}{TotalTrade_X} \times 0.5 + \frac{Trade_{AB}}{GDP_X} \times 0.5")
    st.latex(r"Score = \min\left(100,\ \frac{Dep_A + Dep_B}{2} \times 1000\right)")
    st.subheader("한계")
    st.markdown("""
- 상품 무역만 사용합니다. 서비스 무역, 해외직접투자(FDI), 기술 교류는 반영하지 못합니다.
- 갈등 수준은 실시간 통계로 산출할 수 없는 **질적 평가**입니다. 보고서의 5개 국가 쌍은 기본값이 들어 있고, 나머지는 직접 선택해야 합니다.
- 대만 등 세계은행 GDP 통계가 없는 나라는 조회되지 않을 수 있습니다.
- 스케일링 계수 1000과 상한 100점은 직관적으로 정한 값이라, 상한에 걸리는 쌍은 서로 구분되지 않습니다.
""")
