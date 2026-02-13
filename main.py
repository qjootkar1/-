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
    
    # 데이터 양을 늘리기 위해 검색 결과 수를 40개로 대폭 상향
    payload = {
        "q": f"{q} (단점 OR 장점 OR 실사용 OR 후기 OR 고민) (site:gall.dcinside.com OR site:ppomppu.co.kr OR site:fmkorea.com OR site:ruliweb.com OR site:naver.com)",
        "gl": "ko", "hl": "ko", "num": 40, "tbs": "qdr:y" 
    }
    
    try:
        response = requests.post(search_url, json=payload, headers=headers)
        data = response.json()
        items = data.get('organic', [])
        
        analysis = {"pros": [], "cons": [], "features": []}
        score = 75  # 기본 베이스 점수

        # [초거대 범용 키워드 사전]
        dict_map = {
            # 이어폰, 가전, 의류, 캠핑 등 통합 긍정 키워드
            "pros": [
                "가성비", "음질 좋", "노캔 대박", "착용감 편", "연결 빠름", "디자인 예쁨", 
                "튼튼", "배송 빠름", "마감 훌륭", "조용함", "강력 추천", "오래감", "가벼움", 
                "색상 잘", "삶의 질", "만족도 높", "편리함", "수납 넉넉"
            ],
            # 이어폰 끊김, 발열, 소음, 비싼 가격 등 통합 부정 키워드
            "cons": [
                "비쌈", "끊김", "싱크 안맞", "무거움", "발열", "소음", "조잡", "배터리 광탈", 
                "불량", "아쉬움", "별로", "비추", "느림", "베젤 두껍", "먼지 잘", "냄새 남", 
                "귀 아픔", "압박", "작음", "내구성 약함", "조작 불편", "비효율"
            ],
            # 제품의 특성을 나타내는 기술적 키워드
            "features": [
                "음질", "통화품질", "노이즈캔슬링", "무선충전", "방수", "무게", "사이즈", 
                "가격", "디스플레이", "카메라", "착용감", "내구성", "재질", "색상"
            ]
        }

        valid_reviews = []
        for item in items:
            txt = item.get('snippet', '')
            
            # 검색어가 포함된 유효한 데이터만 선별
            if q.lower() not in txt.lower(): continue
            valid_reviews.append(txt)

            # 긍정 분석 & 점수 가점
            for word in dict_map["pros"]:
                if word in txt:
                    analysis["pros"].append(txt[:70] + "...")
                    score += 1.8
            # 부정 분석 & 점수 감점 (쇼핑 방지기이므로 감점 폭이 큽니다)
            for word in dict_map["cons"]:
                if word in txt:
                    analysis["cons"].append(txt[:70] + "...")
                    score -= 3.5
            # 특징 추출
            for word in dict_map["features"]:
                if word in txt:
                    analysis["features"].append(word)

        # 최종 점수 산출 (보정치 적용)
        final_score = max(min(round(score), 100), 5)
        
        return {
            "status": "success",
            "product": q,
            "score": final_score,
            "summary": {
                "pros": list(set(analysis["pros"]))[:4],
                "cons": list(set(analysis["cons"]))[:4],
                "features": list(set(analysis["features"]))[:6]
            },
            "reviews": valid_reviews[:10] # 원본 리뷰도 더 많이 보여줌
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
