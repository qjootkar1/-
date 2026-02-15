import os
import re
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import google.generativeai as genai

# 경로 보정: templates 폴더를 절대 경로로 찾아 '하얀 화면' 방지
current_dir = os.path.dirname(os.path.abspath(__file__))
template_path = os.path.join(current_dir, "templates")
templates = Jinja2Templates(directory=template_path)

app = FastAPI()

# 환경 변수 로드
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

# Gemini 설정 (가장 안정적인 최신 모델명 사용)
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    # [수정] 모델명을 'gemini-1.5-flash-latest'로 변경하여 404 에러 해결
    model = genai.GenerativeModel(model_name="gemini-1.5-flash-latest")

# Serper API 데이터 수집 함수
async def fetch_search_data(product_name: str):
    if not SERPER_API_KEY: return []
    url = "https://google.serper.dev/search"
    headers = {'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'}
    data = { "q": f"{product_name} 실제 사용 리뷰 장단점 특징", "gl": "kr", "hl": "ko" }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=data, timeout=10.0)
            res_json = response.json()
            return [item.get("snippet", "") for item in res_json.get("organic", [])]
        except Exception as e:
            print(f"Serper Error: {e}")
            return []

# 데이터 일치 검증 함수
def filter_relevant_data(raw_texts, product_name):
    filtered = []
    keywords = [k for k in product_name.lower().split() if len(k) > 0]
    for text in raw_texts:
        if any(kw in text.lower() for kw in keywords):
            clean_text = re.sub(r'\s+', ' ', text).strip()
            if len(clean_text) > 20: filtered.append(clean_text)
    return list(set(filtered))[:15]

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/chat")
async def handle_analysis(user_input: str = Form(...)):
    if not GEMINI_API_KEY or not SERPER_API_KEY:
        return JSONResponse(content={"error": "서버의 API 키 설정이 누락되었습니다."}, status_code=500)
    
    try:
        # 1. Serper 데이터 수집 및 필터링
        raw_data = await fetch_search_data(user_input)
        refined_data = filter_relevant_data(raw_data, user_input)
        
        context = "\n".join(refined_data) if refined_data else "실시간 리뷰를 찾지 못했습니다. 일반 지식으로 작성하세요."

        # 2. 사용자 요청 상세 프롬프트 (살려내기)
        prompt = f"""
        당신은 제품 전문 분석가입니다. 아래 데이터를 바탕으로 '{user_input}'의 리포트를 작성하세요.
        
        [수집된 정보]:
        {context}

        분석 양식:
        ■ 1. 핵심 특징 및 품질: 기술적 장점과 마감 수준 설명
        ■ 2. 주요 장점 (Pros): 사용자들이 칭찬하는 점 (불렛포인트)
        ■ 3. 주요 단점 (Cons): 실제 사용 시 불편함과 품질 이슈 (비판적 기술)
        ■ 4. 항목별 평가 점수 (10점 만점):
           - 성능, 디자인, 가성비, 품질 점수와 그 이유 기술
           - **종합 점수 기재**
        ■ 5. 맞춤 추천 가이드: 
           - ✅ 추천 대상: (누구에게 좋은가?)
           - ❌ 비추천 대상: (누구에게 나쁜가?)
        ■ 6. 최종 구매 가치 요약
        """
        
        # 3. 답변 생성
        response = model.generate_content(prompt)
        return {"answer": response.text, "data_info": f"검증 데이터 {len(refined_data)}건 분석 완료"}

    except Exception as e:
        return JSONResponse(content={"error": f"분석 중 오류 발생: {str(e)}"}, status_code=500)
