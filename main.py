import os
import requests
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from collections import Counter

app = FastAPI()
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/analyze")
async def analyze(q: str = Query(...)):
    api_key = os.environ.get('SERPER_API_KEY')
    search_url = "https://google.serper.dev/search"
    headers = {'X-API-KEY': api_key, 'Content-Type': 'application/json'}
    
    # 쿼리 정밀화: 비교글보다는 해당 기기 자체의 "진짜 후기"를 찾도록 변경
    search_queries = [
        f"{q} 실사용 후기 내돈내산", 
        f"{q} 음질 착용감 솔직후기", 
        f"{q} 일주일 사용 장단점",
        f"{q} 카페 커뮤니티 후기"
    ]
    all_snippets = []
    
    for query in search_queries:
        payload = {"q": query, "gl": "ko", "hl": "ko", "num": 40} # 더 넓은 샘플 확보
        try:
            res = requests.post(search_url, json=payload, headers=headers)
            all_snippets.extend([item.get('snippet', '') for item in res.json().get('organic', [])])
        except: continue

    # 키워드 사전 (기존 유지하되 분석 강도 조절)
    analysis_dict = {
        "음질/사운드": ["음질", "저음", "고음", "베이스", "해상도", "음향", "타격감", "음색", "보컬", "치찰음"],
        "착용감/디자인": ["착용감", "이어팁", "귀아픔", "무게", "디자인", "색상", "두께", "핏", "이압"],
        "연결/지연": ["블루투스", "끊김", "페어링", "레이턴시", "싱크", "지연", "멀티포인트"],
        "기능/노캔": ["노캔", "노이즈캔슬링", "주변소리", "통화품질", "방수", "터치조작"],
        "성능/작동": ["속도", "렉", "버벅", "최적화", "성능", "반응속도"],
        "배터리/전력": ["배터리", "충전", "광탈", "지속시간", "C타입", "무선충전"],
        "소음/발열": ["소음", "팬소음", "진동", "발열", "온도"],
        "가격/가심비": ["가성비", "비쌈", "저렴", "돈값", "할인", "혜자"]
    }

    pros_count, cons_count = 0, 0
    detected_tags = []
    pros_details, cons_details = [], []
    
    unique_snippets = list(set(all_snippets))
    for txt in unique_snippets:
        # 1. 스팸 및 단순 가이드글 필터링 강화
        if any(ad in txt for ad in ["소정의", "지원받아", "협찬", "TOP5", "비교추천"]): continue
        
        # 2. 감성 사전 정밀화
        bad_signals = ["불편", "문제", "단점", "아쉽", "별로", "비추", "끊겨", "아파", "비싸", "이슈", "실망", "부족"]
        good_signals = ["좋음", "만족", "추천", "최고", "깔끔", "풍부", "편해", "가벼워", "빠름", "강추", "완벽", "개선"]
        
        # 3. 긍정/부정 내용이 문장에 포함되었는지 체크
        is_bad = any(b in txt for b in bad_signals)
        is_good = any(g in txt for g in good_signals)
        
        # 4. 단순 나열이 아닌 '내용'이 있는 것만 수집
        if is_bad and len(txt) > 20: 
            cons_count += 1
            cons_details.append(txt.strip())
        if is_good and len(txt) > 20: 
            pros_count += 1
            pros_details.append(txt.strip())

        for cat, words in analysis_dict.items():
            if any(w in txt for w in words):
                detected_tags.append(cat)

    # 현실적 점수 반영 (긍정 가중치를 소폭 높임)
    final_score = 75 + (pros_count * 1.5) - (cons_count * 2.0)
    final_score = max(min(round(final_score), 100), 10)

    # 분석 요약 메시지
    reason_summary = []
    if final_score >= 85: reason_summary.append("사용자들의 극찬이 많습니다. 믿고 구매하셔도 좋을 것 같네요.")
    elif final_score >= 70: reason_summary.append("대체로 좋다는 평이 많지만, 몇몇 아쉬운 점은 체크해보세요.")
    else: reason_summary.append("호불호가 갈리거나 특정 기능에 대한 불만이 확인됩니다.")

    return {
        "score": final_score, 
        "pros_n": pros_count, 
        "cons_n": cons_count,
        "reason": reason_summary, 
        "tags": [k for k, v in Counter(detected_tags).most_common(8)],
        "pros_list": list(set(pros_details))[:5], 
        "cons_list": list(set(cons_details))[:5],
        "reviews": unique_snippets[:10]
    }
