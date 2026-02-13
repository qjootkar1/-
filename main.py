import os
import requests
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from collections import Counter

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Jinja2와 Vue 문법 충돌 방지
templates.env.variable_start_string = "[["
templates.env.variable_end_string = "]]"

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/analyze")
async def analyze(q: str = Query(...)):
    api_key = os.environ.get('SERPER_API_KEY')
    search_url = "https://google.serper.dev/search"
    headers = {'X-API-KEY': api_key, 'Content-Type': 'application/json'}
    
    # 검색 쿼리 최적화
    search_queries = [f"{q} 사용기 장단점", f"{q} 음질 착용감 후기", f"{q} 실사용 만족도 이슈"]
    all_snippets = []
    
    for query in search_queries:
        payload = {"q": query, "gl": "ko", "hl": "ko", "num": 25}
        try:
            res = requests.post(search_url, json=payload, headers=headers)
            all_snippets.extend([item.get('snippet', '') for item in res.json().get('organic', [])])
        except: continue

    # [수백가지 대응] 범용 및 오디오/가전 특화 키워드 사전
    analysis_dict = {
        "음질/사운드": ["음질", "저음", "고음", "베이스", "해상도", "음향", "타격감", "화이트노이즈", "음색", "보컬", "악기분리"],
        "착용감/디자인": ["착용감", "이어팁", "귀아픔", "무게", "그립감", "재질", "마감", "디자인", "색상", "두께", "핏"],
        "연결/지연": ["블루투스", "끊김", "페어링", "레이턴시", "싱크", "지연", "연결성", "멀티포인트", "코덱"],
        "기능/노캔": ["노캔", "노이즈캔슬링", "주변소리", "통화품질", "앱지원", "방수", "터치조작", "공간음향"],
        "성능/작동": ["속도", "렉", "버벅", "최적화", "흡입력", "화력", "풍량", "반응속도", "부팅", "성능"],
        "배터리/전력": ["배터리", "충전", "광탈", "방전", "지속시간", "C타입", "무선충전", "전력효율"],
        "소음/발열": ["소음", "팬소음", "진동", "웅웅", "정숙", "발열", "뜨거움", "냉각", "온도"],
        "가격/가심비": ["가성비", "비쌈", "저렴", "돈값", "할인", "혜자", "창렬", "유지비", "프리미엄"]
    }

    pros_count = 0
    cons_count = 0
    detected_tags = []
    cons_details = []
    
    unique_snippets = list(set(all_snippets))
    for txt in unique_snippets:
        if any(ad in txt for ad in ["소정의", "지원받아", "협찬", "광고"]): continue
        
        # 감성 분석 시그널
        bad_signals = ["불편", "문제", "단점", "아쉽", "별로", "비추", "끊겨", "아파", "비싸", "이슈", "실망"]
        good_signals = ["좋음", "만족", "추천", "최고", "깔끔", "풍부", "편해", "가벼워", "빠름", "강추", "완벽"]
        
        has_bad = any(b in txt for b in bad_signals)
        has_good = any(g in txt for g in good_signals)
        
        if has_bad: 
            cons_count += 1
            cons_details.append(txt[:100].replace('\n', ' ') + "...")
        if has_good: 
            pros_count += 1

        for cat, words in analysis_dict.items():
            if any(w in txt for w in words):
                detected_tags.append(cat)

    # [현실적 점수 반영] 
    # 기본 점수를 80점으로 높이고, 긍정 점수 가중치를 상향, 부정 점수 감점을 완화했습니다.
    final_score = 80 + (pros_count * 1.5) - (cons_count * 2.5)
    final_score = max(min(round(final_score), 100), 10)

    # 점수 근거
    reason_summary = []
    if final_score >= 85:
        reason_summary.append("전반적으로 실사용자들의 만족도가 매우 높고 추천할만한 제품입니다.")
    elif final_score >= 70:
        reason_summary.append("대체로 만족스러우나 일부 사용 환경에서 아쉬운 점이 포착됩니다.")
    else:
        reason_summary.append("성능이나 편의성 면에서 사용자들이 공통적으로 지적하는 이슈가 있습니다.")

    reason_summary.append(f"총 {len(unique_snippets)}건의 데이터 중 긍정 신호 {pros_count}개, 주의 신호 {cons_count}개가 분석되었습니다.")

    return {
        "score": final_score,
        "pros_n": pros_count,
        "cons_n": cons_count,
        "reason": reason_summary,
        "tags": [k for k, v in Counter(detected_tags).most_common(8)],
        "cons_list": list(set(cons_details))[:6],
        "reviews": unique_snippets[:12]
    }
