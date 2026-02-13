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
        return {"status": "error", "message": "API 키를 설정해주세요."}

    search_url = "https://google.serper.dev/search"
    headers = {'X-API-KEY': api_key, 'Content-Type': 'application/json'}
    
    # 데이터 확보를 위한 다각도 검색 쿼리
    target_queries = [
        f"{q} 실제 사용 단점 결함",
        f"{q} 내돈내산 솔직 불만",
        f"{q} 커뮤니티 고질병",
        f"{q} 장점 특징 요약"
    ]
    
    all_raw_items = []
    for t_query in target_queries:
        payload = {"q": t_query, "gl": "ko", "hl": "ko", "num": 20, "tbs": "qdr:y"}
        try:
            res = requests.post(search_url, json=payload, headers=headers)
            all_raw_items.extend(res.json().get('organic', []))
        except: continue

    unique_items = {item.get('link'): item for item in all_raw_items}.values()
    
    analysis = {"pros": [], "cons": [], "features": []}
    score = 72.0 
    ad_count = 0
    ad_keywords = ['소정의', '원고료', '협찬', '지원받아', '체험단', '무상제공']

    valid_reviews = []
    for item in unique_items:
        txt = item.get('snippet', '')
        if any(k in txt for k in ad_keywords):
            ad_count += 1
            continue
            
        if q.lower() in txt.lower() or any(w in txt for w in ['제품', '사용', '구매', '리뷰']):
            valid_reviews.append(txt)
            
            # 장단점 분석 키워드 (범용)
            pro_map = ["가성비", "음질", "만족", "추천", "빠름", "편함", "혁신", "견고", "깔끔", "정확", "튼튼"]
            con_map = ["비쌈", "느림", "무겁", "발열", "소음", "불량", "끊김", "싱크", "단점", "최악", "고장", "베젤", "진동", "이슈"]
            feat_map = ["배터리", "디스플레이", "카메라", "성능", "무게", "사이즈", "노캔", "연동성", "충전", "방수", "디자인"]

            for w in pro_map:
                if w in txt:
                    analysis["pros"].append(txt[:75] + "...")
                    score += 1.5
                    break
            for w in con_map:
                if w in txt:
                    analysis["cons"].append(txt[:75] + "...")
                    score -= 4.5 # 쇼핑 방지기이므로 감점 가중치 강화
                    break
            for w in feat_map:
                if w in txt: analysis["features"].append(w)

    return {
        "status": "success",
        "product": q,
        "score": max(min(round(score), 100), 5),
        "ad_ratio": round((ad_count / len(unique_items) * 100)) if unique_items else 0,
        "summary": {
            "pros": list(set(analysis["pros"]))[:5],
            "cons": list(set(analysis["cons"]))[:5],
            "features": list(set(analysis["features"]))[:8]
        },
        "reviews": valid_reviews[:15]
    }
