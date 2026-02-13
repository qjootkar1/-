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
    
    # 데이터 확보를 위한 다중 쿼리
    queries = [f"{q} 단점 이슈", f"{q} 내돈내산 불만", f"{q} 사용기 장단점"]
    all_snippets = []
    
    for query in queries:
        payload = {"q": query, "gl": "ko", "hl": "ko", "num": 15}
        try:
            res = requests.post(search_url, json=payload, headers=headers)
            all_snippets.extend([item.get('snippet', '') for item in res.json().get('organic', [])])
        except: continue

    # 키워드 맵 (더 풍부한 분석을 위해)
    keyword_map = {
        "디스플레이": ["화면", "액정", "주사율", "밝기", "번인"],
        "성능/발열": ["속도", "버벅", "렉", "뜨거움", "발열", "최적화"],
        "배터리": ["광탈", "충전", "오래", "방전"],
        "사운드": ["음질", "노캔", "소음", "싱크", "화이트노이즈"],
        "편의성": ["무게", "그립감", "연동", "불편", "편함"],
        "가성비": ["비쌈", "혜자", "돈값", "저렴", "할인"]
    }

    found_tags = []
    pros = []
    cons = []
    score = 75.0

    for txt in all_snippets:
        if any(ad in txt for ad in ["소정의", "지원받아", "협찬"]): continue
        
        # 카테고리 매칭 및 점수 계산
        for cat, keywords in keyword_map.items():
            for k in keywords:
                if k in txt:
                    found_tags.append(cat)
                    if any(b in txt for b in ["불편", "문제", "단점", "최악", "별로"]):
                        score -= 3.5
                        cons.append(txt[:85] + "...")
                    if any(g in txt for g in ["좋음", "만족", "추천", "최고"]):
                        score += 1.0
                        pros.append(txt[:85] + "...")
                    break

    return {
        "score": max(min(round(score), 100), 5),
        "summary": {
            "tags": list(set(found_tags))[:6],
            "pros": list(set(pros))[:3],
            "cons": list(set(cons))[:5]
        },
        "reviews": list(set(all_snippets))[:12]
    }
