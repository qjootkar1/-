import os
import requests
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

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
    
    # 1. 멀티 쿼리로 원천 데이터 대량 확보
    queries = [f"{q} 단점 결함", f"{q} 실사용 후기 불만", f"{q} 고질병 이슈"]
    all_snippets = []
    
    for query in queries:
        payload = {"q": query, "gl": "ko", "hl": "ko", "num": 20}
        try:
            res = requests.post(search_url, json=payload, headers=headers)
            all_snippets.extend([item.get('snippet', '') for item in res.json().get('organic', [])])
        except: continue

    # 2. 분석 사전 (더 세밀하게 확장)
    keyword_map = {
        "디스플레이": ["액정", "화면", "밝기", "주사율", "번인", "베젤"],
        "퍼포먼스": ["속도", "버벅", "렉", "게임", "최적화", "발열", "뜨거움"],
        "배터리/충전": ["조기방전", "광탈", "충전기", "무선충전", "오래"],
        "음질/사운드": ["노캔", "화이트노이즈", "끊김", "싱크", "저음", "고음"],
        "디자인/외형": ["무게", "그립감", "색상", "재질", "스크래치", "마감"],
        "가격/가치": ["가성비", "비쌈", "저렴", "할인", "돈값"]
    }

    found_features = []
    pros_list = []
    cons_list = []
    score = 75.0

    # 3. 데이터 정밀 스캐닝
    for txt in all_snippets:
        if any(ad in txt for ad in ["소정의", "지원받아", "협찬"]): continue
        
        # 특징 및 키워드 동적 추출
        for category, keywords in keyword_map.items():
            for k in keywords:
                if k in txt:
                    found_features.append(category if category != "가격/가치" else k)
                    # 문맥에 따른 가점/감점 (더 정밀하게)
                    if any(bad in txt for bad in ["불편", "별로", "최악", "이슈", "문제"]):
                        score -= 2.5
                        cons_list.append(txt[:80] + "...")
                    if any(good in txt for good in ["좋음", "추천", "만족", "훌륭"]):
                        score += 0.8
                        pros_list.append(txt[:80] + "...")
                    break

    # 중복 제거 및 상위 키워드 추출
    final_features = sorted(set(found_features), key=lambda x: found_features.count(x), reverse=True)

    return {
        "product": q,
        "score": max(min(round(score), 100), 5),
        "summary": {
            "features": final_features[:6],
            "pros": list(set(pros_list))[:3],
            "cons": list(set(cons_list))[:5]
        },
        "reviews": list(set(all_snippets))[:15]
    }
