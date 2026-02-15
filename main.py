import os
import requests
import re
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from collections import Counter

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
    
    # 1. 검색어 강제 고정 (따옴표 활용 및 불필요 모델 제외)
    search_queries = [
        f'"{q}" 실제 사용기 단점 아쉬운점', 
        f'"{q}" 솔직 후기 장단점 특징',
        f'"{q}" 구매 전 필수 확인 이슈'
    ]
    
    all_snippets = []
    for query in search_queries:
        payload = {"q": query, "gl": "ko", "hl": "ko", "num": 40}
        try:
            res = requests.post(search_url, json=payload, headers=headers)
            all_snippets.extend([item.get('snippet', '') for item in res.json().get('organic', [])])
        except: continue

    # 2. 감성 사전 및 문맥 사전 (부정적 뉘앙스 우선 순위)
    neg_indicators = ["아쉽", "불편", "문제", "별로", "비추", "끊겨", "아파", "이슈", "실망", "부족", "글쎄", "글쎄요", "하지만", "다만"]
    pos_indicators = ["좋음", "만족", "추천", "최고", "깔끔", "편해", "빠름", "강추", "완벽", "개선"]

    pros_details, cons_details, features = [], [], []
    detected_tags = []
    
    # 모델명에서 숫자와 영문 추출 (정확한 매칭용)
    q_clean = q.lower().replace(" ", "")

    for txt in list(set(all_snippets)):
        # [검증 1] 광고/협찬 글 차단
        if any(ad in txt for ad in ["소정의", "지원받아", "협찬", "TOP", "원고료"]): continue
        
        # [검증 2] 모델명 철저 검증 (T18 검색 시 T13이 나오면 탈락)
        txt_lower = txt.lower().replace(" ", "")
        if q_clean not in txt_lower: continue
        
        # 다른 모델명(숫자가 다른 경우)이 주연인지 확인 (예: T18 검색 중 T13 언급)
        numbers_in_txt = re.findall(r'\d+', txt_lower)
        numbers_in_q = re.findall(r'\d+', q_clean)
        if numbers_in_q and any(num for num in numbers_in_txt if num not in numbers_in_q):
            # 검색어에 없는 숫자가 모델명처럼 쓰였다면 타 모델 비교글일 확률 높음 -> 제외하거나 매우 조심히 다룸
            continue

        # [검증 3] 문장 정제 (말줄임표 제거 및 핵심 추출)
        clean_txt = re.sub(r'\.{2,}', '. ', txt).strip()
        if len(clean_txt) < 15: continue

        # [검증 4] 오분류 방지 로직 (장점 같은데 단점인 경우)
        # "좋긴 한데 ~가 아쉽다"는 단점으로 분류해야 함
        is_neg = any(n in clean_txt for n in neg_indicators)
        is_pos = any(p in clean_txt for p in pos_indicators)

        if is_neg: # 부정 키워드가 하나라도 있으면 '단점' 혹은 '주의사항'으로 우선 분류
            cons_details.append(clean_txt)
        elif is_pos:
            pros_details.append(clean_txt)
        else:
            features.append(clean_txt)

        # 태그 추출 (음질, 배터리 등)
        for cat, words in {"음질": ["음질", "소리", "베이스"], "착용감": ["착용", "귀", "무게"], "연결": ["블루투스", "끊김"], "배터리": ["배터리", "충전"]}.items():
            if any(w in clean_txt for w in words):
                detected_tags.append(cat)

    # 중복 제거 및 최종 선별 (내용이 겹치지 않게)
    def finalize_list(lst, limit=4):
        seen = set()
        final = []
        for item in lst:
            short = item[:20] # 앞부분이 비슷하면 중복으로 간주
            if short not in seen:
                final.append(item[:120]) # 최대 120자 제한 (잘리지 않게)
                seen.add(short)
        return final[:limit]

    return {
        "score": 70 + (len(pros_details) * 2) - (len(cons_details) * 3),
        "tags": [k for k, v in Counter(detected_tags).most_common(5)],
        "pros_list": finalize_list(pros_details),
        "cons_list": finalize_list(cons_details),
        "features": finalize_list(features, limit=2)
    }
