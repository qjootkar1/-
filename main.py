import os
import requests
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()

# Jinja2와 Vue의 기호 충돌을 막기 위해 서버용 기호를 [[ ]] 로 변경합니다.
templates = Jinja2Templates(directory="templates")
templates.env.variable_start_string = "[["
templates.env.variable_end_string = "]]"

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # 이제 서버는 HTML 내부의 {{ }} 를 봐도 무시하고 에러를 내지 않습니다.
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/analyze")
async def analyze(q: str = Query(...)):
    api_key = os.environ.get('SERPER_API_KEY')
    if not api_key:
        return {"status": "error", "message": "API 키 누락"}

    search_url = "https://google.serper.dev/search"
    headers = {'X-API-KEY': api_key, 'Content-Type': 'application/json'}
    
    # 더 넓은 범위의 키워드 수집
    queries = [f"{q} 단점 이슈", f"{q} 장점 특징", f"{q} 솔직 후기"]
    all_snippets = []
    
    for query in queries:
        payload = {"q": query, "gl": "ko", "hl": "ko", "num": 15}
        try:
            res = requests.post(search_url, json=payload, headers=headers)
            all_snippets.extend([item.get('snippet', '') for item in res.json().get('organic', [])])
        except: continue

    # 동적 키워드 및 점수 분석
    score = 75.0
    tags = []
    cons = []
    
    analysis_map = {
        "디스플레이": ["화면", "액정", "주사율", "밝기"],
        "퍼포먼스": ["속도", "버벅", "렉", "발열", "성능"],
        "배터리": ["광탈", "충전", "방전", "용량"],
        "디자인": ["무게", "그립감", "색상", "마감"]
    }

    for txt in all_snippets:
        if any(ad in txt for ad in ["소정의", "지원받아", "협찬"]): continue
        
        for category, keywords in analysis_map.items():
            if any(k in txt for k in keywords):
                tags.append(category)
                if any(b in txt for b in ["불편", "문제", "단점", "최악", "이슈"]):
                    score -= 3.5
                    cons.append(txt[:80] + "...")
                break

    return {
        "score": max(min(round(score), 100), 5),
        "tags": list(set(tags))[:5],
        "cons": list(set(cons))[:5],
        "reviews": list(set(all_snippets))[:10]
    }
