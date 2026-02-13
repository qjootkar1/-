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
    if not api_key:
        return {"status": "error", "message": "API 키 설정 필요"}

    search_url = "https://google.serper.dev/search"
    headers = {'X-API-KEY': api_key, 'Content-Type': 'application/json'}
    
    # 쿼리 강화: 커뮤니티 타겟팅
    payload = {
        "q": f"{q} (단점 OR 장점 OR 특징 OR 비추) (site:gall.dcinside.com OR site:ppomppu.co.kr OR site:fmkorea.com)",
        "gl": "ko", "hl": "ko", "num": 15, "tbs": "qdr:y" 
    }
    
    try:
        response = requests.post(search_url, json=payload, headers=headers)
        data = response.json()
        items = data.get('organic', [])
        
        raw_reviews = []
        pros, cons = [], []
        score_sum = 70  # 기본 점수 시작
        
        # 키워드 기반 분석 로직
        pro_words = ['좋음', '가성비', '만족', '추천', '깔끔', '빠름']
        con_words = ['느림', '별로', '쓰레기', '비쌈', '베젤', '무거움', '발열', '단점']

        for item in items:
            txt = item.get('snippet', '')
            if q.lower() in txt.lower() or any(w in txt for w in ['폰', '제품', '기기']):
                raw_reviews.append(txt)
                
                # 점수 및 장단점 분류 (간단한 형태)
                for p in pro_words:
                    if p in txt:
                        pros.append(txt[:50] + "...")
                        score_sum += 2
                        break
                for c in con_words:
                    if c in txt:
                        cons.append(txt[:50] + "...")
                        score_sum -= 3
                        break

        # 최종 점수 제한 (0~100점)
        final_score = max(min(score_sum, 100), 10)

        return {
            "status": "success",
            "product": q,
            "score": final_score,
            "summary": {
                "pros": list(set(pros))[:3], # 중복 제거 후 3개
                "cons": list(set(cons))[:3],
                "features": ["실시간 커뮤니티 반응 분석", "최근 1년 데이터 기반"]
            },
            "reviews": raw_reviews[:5]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
