import os
import requests
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()
# Jinja2 문법과 Vue 문법이 충돌하지 않도록 설정을 변경합니다.
templates = Jinja2Templates(directory="templates")
templates.env.variable_start_string = '[[' 
templates.env.variable_end_string = ']]'

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/analyze")
async def analyze(q: str = Query(...)):
    api_key = os.environ.get('SERPER_API_KEY')
    search_url = "https://google.serper.dev/search"
    headers = {'X-API-KEY': api_key, 'Content-Type': 'application/json'}
    
    # 데이터 수집 (최대한 많이)
    queries = [f"{q} 단점 이슈", f"{q} 사용기 장단점", f"{q} 솔직 후기"]
    all_snippets = []
    
    for query in queries:
        payload = {"q": query, "gl": "ko", "hl": "ko", "num": 15}
        try:
            res = requests.post(search_url, json=payload, headers=headers)
            all_snippets.extend([item.get('snippet', '') for item in res.json().get('organic', [])])
        except: continue

    # 키워드 분석 로직
    keyword_map = {
        "디스플레이": ["화면", "액정", "밝기", "주사율"],
        "퍼포먼스": ["속도", "버벅", "렉", "발열"],
        "배터리": ["광탈", "충전", "방전"],
        "사운드": ["음질", "노캔", "끊김"],
        "디자인": ["무게", "그립감", "재질"]
    }

    found_tags = []
    cons = []
    score = 80.0

    for txt in all_snippets:
        if any(ad in txt for ad in ["소정의", "지원받아", "협찬"]): continue
        for cat, keywords in keyword_map.items():
            for k in keywords:
                if k in txt:
                    found_tags.append(cat)
                    if any(b in txt for b in ["불편", "문제", "단점", "최악"]):
                        score -= 4.0
                        cons.append(txt[:80] + "...")
                    break

    return {
        "score": max(min(round(score), 100), 10),
        "summary": {
            "tags": list(set(found_tags))[:5],
            "cons": list(set(cons))[:5]
        },
        "reviews": list(set(all_snippets))[:10]
    }
