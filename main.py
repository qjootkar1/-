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
        return {"status": "error", "message": "API 키가 설정되지 않았습니다."}

    search_url = "https://google.serper.dev/search"
    headers = {'X-API-KEY': api_key, 'Content-Type': 'application/json'}
    
    # [전략 1] 데이터 확보를 위한 멀티 타겟 쿼리 (검색량 4배 확장)
    target_queries = [
        f"{q} 실제 사용 단점 결함",
        f"{q} 내돈내산 솔직 불만 후기",
        f"{q} 커뮤니티 고질병 이슈",
        f"{q} 장점 특징 요약"
    ]
    
    all_raw_items = []
    for t_query in target_queries:
        payload = {
            "q": t_query,
            "gl": "ko", "hl": "ko", "num": 20, "tbs": "qdr:y" # 최근 1년 데이터
        }
        try:
            res = requests.post(search_url, json=payload, headers=headers)
            all_raw_items.extend(res.json().get('organic', []))
        except:
            continue

    # 중복 제거 (URL 기준)
    unique_items = {item.get('link'): item for item in all_raw_items}.values()
    
    # [전략 2] 방대한 범용 분석 사전
    dict_map = {
        "pros": [
            "가성비", "음질", "만족", "추천", "빠름", "편함", "혁신", "견고", "오래감", "예쁨", 
            "마감", "안정적", "가벼움", "조용", "최고", "깔끔", "정확", "튼튼", "수납", "품질"
        ],
        "cons": [
            "비쌈", "느림", "무거", "발열", "소음", "불량", "끊김", "싱크", "단점", "최악", 
            "버벅", "비효율", "부족", "불편", "고장", "베젤", "진동", "이슈", "아픔", "압박",
            "냄새", "먼지", "조잡", "광탈", "품절", "불친절", "어려움", "복잡", "허술"
        ],
        "features": [
            "배터리", "디스플레이", "카메라", "성능", "무게", "사이즈", "노캔", "연동성", 
            "그립감", "충전", "방수", "가격", "재질", "디자인", "색상", "음질", "착용감"
        ]
    }

    analysis = {"pros": [], "cons": [], "features": []}
    score = 72.0  # 기본 시작 점수
    ad_count = 0
    ad_keywords = ['소정의', '원고료', '협찬', '지원받아', '체험단', '무상제공']

    valid_reviews = []
    for item in unique_items:
        txt = item.get('snippet', '')
        
        # 1. 광고 필터링
        if any(k in txt for k in ad_keywords):
            ad_count += 1
            continue
            
        # 2. 관련성 체크 (제품명 검색어 포함 여부)
        if q.lower() in txt.lower() or any(w in txt for w in ['제품', '사용', '구매', '후기']):
            valid_reviews.append(txt)
            
            # 3. 가점 및 감점 로직 (점수 정밀화)
            found_pro = False
            for w in dict_map["pros"]:
                if w in txt:
                    analysis["pros"].append(txt[:75] + "...")
                    score += 1.2
                    found_pro = True
                    break
            
            # 단점은 더 민감하게 감점 (쇼핑 방지기 핵심)
            for w in dict_map["cons"]:
                if w in txt:
                    analysis["cons"].append(txt[:75] + "...")
                    score -= 4.0  # 감점 폭을 크게 설정
                    break
            
            # 특징 키워드 추출
            for w in dict_map["features"]:
                if w in txt:
                    analysis["features"].append(w)

    # [전략 3] 최종 결과 가공
    final_score = max(min(round(score), 100), 5)
    
    # 특징 태그 중복 제거 및 상위 추출
    final_features = list(set(analysis["features"]))[:8]
    
    return {
        "status": "success",
        "product": q,
        "score": final_score,
        "ad_ratio": round((ad_count / len(unique_items) * 100)) if unique_items else 0,
        "summary": {
            "pros": list(set(analysis["pros"]))[:5],
            "cons": list(set(analysis["cons"]))[:5],
            "features": final_features
        },
        "reviews": valid_reviews[:15] # 원본 소스 제공량 확대
    }
