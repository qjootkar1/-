import os
import requests
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# HTML 파일이 들어있는 폴더 설정
templates = Jinja2Templates(directory="templates")

# 1. 메인 페이지 (브라우저 접속 시)
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# 2. 실시간 분석 API
@app.get("/analyze")
async def analyze(q: str = Query(...)):
    # 환경변수에서 API 키 로드 (보안)
    api_key = os.environ.get('SERPER_API_KEY')
    
    if not api_key:
        return {"error": "API 키가 설정되지 않았습니다."}

    search_url = "https://google.serper.dev/search"
    headers = {
        'X-API-KEY': api_key,
        'Content-Type': 'application/json'
    }
    
    # 실시간 검색 쿼리 설정 (단점 위주 수집)
    payload = {
        "q": f"{q} 실사용 단점 결함 후기 -광고 -협찬",
        "gl": "ko",
        "hl": "ko",
        "num": 20
    }
    
    try:
        response = requests.post(search_url, json=payload, headers=headers)
        data = response.json()
        
        # 검색 결과 파싱
        items = data.get('organic', [])
        snippets = [item.get('snippet', '') for item in items]
        
        # 광고성 키워드 필터링 로직
        ad_keywords = ['소정의', '원고료', '지원받아', '체험단', '무상제공']
        ad_detected = [s for s in snippets if any(k in s for k in ad_keywords)]
        
        return {
            "status": "success",
            "product": q,
            "total_count": len(snippets),
            "ad_ratio": round((len(ad_detected) / len(snippets)) * 100) if snippets else 0,
            "reviews": snippets,
            "ad_snippets": ad_detected
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    # Render 배포를 위한 포트 설정
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
