import os
import requests
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from collections import Counter

app = FastAPI()
# 기본 설정을 사용하여 충돌을 방지합니다.
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/analyze")
async def analyze(q: str = Query(...)):
    api_key = os.environ.get('SERPER_API_KEY')
    search_url = "https://google.serper.dev/search"
    headers = {'X-API-KEY': api_key, 'Content-Type': 'application/json'}
    
    # [수백가지 키워드 데이터 유지]
    search_queries = [f"{q} 사용기 장단점", f"{q} 음질 착용감 후기", f"{q} 실사용 만족도 이슈"]
    all_snippets = []
    
    for query in search_queries:
        payload = {"q": query, "gl": "ko", "hl": "ko", "num": 25}
        try:
            res = requests.post(search_url, json=payload, headers=headers)
            all_snippets.extend([item.get('snippet', '') for item in res.json().get('organic', [])])
        except: continue

    analysis_dict = {
        "음질/사운드": ["음질", "저음", "고음", "베이스", "해상도", "음향", "타격감", "화이트노이즈", "음색", "보컬", "악기분리", "공간감", "치찰음"],
        "착용감/디자인": ["착용감", "이어팁", "귀아픔", "무게", "그립감", "재질", "마감", "디자인", "색상", "두께", "핏", "이압"],
        "연결/지연": ["블루투스", "끊김", "페어링", "레이턴시", "싱크", "지연", "연결성", "멀티포인트", "코덱"],
        "기능/노캔": ["노캔", "노이즈캔슬링", "주변소리", "통화품질", "앱지원", "방수", "터치조작", "공간음향"],
        "성능/작동": ["속도", "렉", "버벅", "최적화", "흡입력", "화력", "풍량", "반응속도", "부팅", "성능"],
        "배터리/전력": ["배터리", "충전", "광탈", "방전", "지속시간", "C타입", "무선충전", "전력효율"],
        "소음/발열": ["소음", "팬소음", "진동", "웅웅", "정숙", "발열", "뜨거움", "냉각", "온도"],
        "가격/가심비": ["가성비", "비쌈", "저렴", "돈값", "할인", "혜자", "창렬", "유지비", "프리미엄"]
    }

    pros_count, cons_count = 0, 0
    detected_tags, cons_details = [], []
    
    unique_snippets = list(set(all_snippets))
    for txt in unique_snippets:
        if any(ad in txt for ad in ["소정의", "지원받아", "협찬", "광고"]): continue
        bad_signals = ["불편", "문제", "단점", "아쉽", "별로", "비추", "끊겨", "아파", "비싸", "이슈", "실망"]
        good_signals = ["좋음", "만족", "추천", "최고", "깔끔", "풍부", "편해", "가벼워", "빠름", "강추", "완벽"]
        if any(b in txt for b in bad_signals): 
            cons_count += 1
            cons_details.append(txt[:100].replace('\n', ' ') + "...")
        if any(g in txt for g in good_signals): 
            pros_count += 1
        for cat, words in analysis_dict.items():
            if any(w in txt for w in words):
                detected_tags.append(cat)

    final_score = 80 + (pros_count * 1.5) - (cons_count * 2.5)
    final_score = max(min(round(final_score), 100), 10)

    reason_summary = []
    if final_score >= 85: reason_summary.append("전반적인 실사용 만족도가 매우 높습니다.")
    elif final_score >= 70: reason_summary.append("대체로 무난하지만 일부 아쉬운 점이 포착됩니다.")
    else: reason_summary.append("사용자들이 공통적으로 지적하는 특정 이슈가 확인됩니다.")

    return {
        "score": final_score, "pros_n": pros_count, "cons_n": cons_count,
        "reason": reason_summary, "tags": [k for k, v in Counter(detected_tags).most_common(8)],
        "cons_list": list(set(cons_details))[:6], "reviews": unique_snippets[:12]
    }
