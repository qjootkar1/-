import os
import re
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import google.generativeai as genai

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# 환경 변수 설정 (Render 환경변수 탭에 두 개 다 넣으셔야 합니다)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# 1. Serper API를 이용한 실제 데이터 수집 (크롤링 대체)
async def fetch_search_data(product_name: str):
    url = "https://google.serper.dev/search"
    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json'
    }
    # 검색 정확도를 위해 "리뷰 장단점 특징" 키워드 조합
    data = { "q": f"{product_name} 실제 사용 리뷰 장단점 특징", "gl": "kr", "hl": "ko" }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=data, timeout=10.0)
            res_json = response.json()
            
            # 검색 결과의 snippet(요약문)들을 수집
            results = []
            if "organic" in res_json:
                for item in res_json["organic"]:
                    results.append(item.get("snippet", ""))
            return results
        except Exception as e:
            print(f"Serper API Error: {e}")
            return []

# 2. 제품 일치 여부 및 노이즈 필터링
def filter_relevant_data(raw_texts, product_name):
    filtered = []
    keywords = [k for k in product_name.lower().split() if len(k) > 0]
    
    for text in raw_texts:
        # 입력한 제품명 키워드가 포함되어 있는지 확인 (엉뚱한 제품 방지)
        if any(kw in text.lower() for kw in keywords):
            clean_text = re.sub(r'\s+', ' ', text).strip()
            if len(clean_text) > 20:
                filtered.append(clean_text)
    return list(set(filtered))[:15]

@app.post("/chat")
async def handle_analysis(user_input: str = Form(...)):
    if not GEMINI_API_KEY or not SERPER_API_KEY:
        return JSONResponse(content={"error": "API 키 설정이 누락되었습니다."}, status_code=500)

    try:
        # Step 1: Serper API로 검색 데이터 가져오기
        raw_data = await fetch_search_data(user_input)

        # Step 2: 제품 일치 검수
        refined_data = filter_relevant_data(raw_data, user_input)
        
        if not refined_data:
            return {"answer": f"'{user_input}'에 대한 정확한 리뷰 데이터를 찾지 못했습니다. 제품명을 상세히 입력해 주세요.", "data_info": "검증 데이터 없음"}

        context = "\n".join(refined_data)

        # Step 3: Gemini 분석
        prompt = f"""
        사용자 요청 제품: [{user_input}]
        아래 검색된 실시간 리뷰 데이터를 기반으로 분석하세요:
        ---
        {context}
        ---
        1. 핵심 특징 및 품질
        2. 장단점 (불렛포인트)
        3. 항목별 점수 (10점 만점: 성능, 디자인, 가성비, 품질) 및 총점
        4. 추천/비추천 대상 (구체적으로)
        5. 최종 구매 가치
        
        주의: 데이터와 관련 없는 제품 정보는 무시하고 객관적으로 작성하세요.
        """
        response = model.generate_content(prompt)
        
        return {
            "answer": response.text,
            "data_info": f"실시간 검색 데이터 {len(refined_data)}건 분석 완료"
        }
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
