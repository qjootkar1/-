import os
import re
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import google.generativeai as genai

# [경로 보정] templates 폴더를 절대 경로로 지정하여 하얀 화면 방지
current_dir = os.path.dirname(os.path.abspath(__file__))
template_path = os.path.join(current_dir, "templates")
templates = Jinja2Templates(directory=template_path)

app = FastAPI()

# Render 환경 변수 로드
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

# Gemini 설정 (가장 안정적인 최신 모델명 지정)
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    # [수정 포인트] 모델명 앞에 models/를 빼거나 -latest를 붙여 404 에러를 방지합니다.
    model = genai.GenerativeModel(model_name="gemini-1.5-flash")

# Serper API 실시간 검색 함수
async def fetch_search_data(product_name: str):
    if not SERPER_API_KEY:
        return []
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

# 제품 일치 검증 필터
def filter_relevant_data(raw_texts, product_name):
    filtered = []
    keywords = [k for k in product_name.lower().split() if len(k) > 0]
    for text in raw_texts:
        if any(kw in text.lower() for kw in keywords):
            clean_text = re.sub(r'\s+', ' ', text).strip()
            if len(clean_text) > 20:
                filtered.append(clean_text)
    return list(set(filtered))[:15]

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/chat")
async def handle_analysis(user_input: str = Form(...)):
    if not GEMINI_API_KEY or not SERPER_API_KEY:
        return JSONResponse(content={"error": "서버에 API 키 설정이 되어있지 않습니다."}, status_code=500)
    
    try:
        # 1. Serper 데이터 수집
        raw_data = await fetch_search_data(user_input)
        refined_data = filter_relevant_data(raw_data, user_input)
        
        # 데이터가 없을 경우를 대비한 기본 컨텍스트
        context = "\n".join(refined_data) if refined_data else "실시간 리뷰를 찾지 못했습니다. 일반적인 제품 지식을 바탕으로 분석하세요."

        # 2. 복구된 정밀 분석 프롬프트
        prompt = f"""
        당신은 제품 전문 리뷰 분석가입니다. 아래 데이터를 기반으로 '{user_input}'의 상세 리포트를 작성하세요.
        ---
        [수집된 데이터]
        {context}
        ---
        [보고서 양식]
        ■ 1. 핵심 특징 및 품질
        (제품의 기술적 강점과 소재, 마감 수준 설명)

        ■ 2. 주요 장점 (Pros)
        (사용자들이 높게 평가하는 부분을 불렛포인트로 정리)

        ■ 3. 주요 단점 (Cons)
        (실제 사용 시 불편함이나 품질 이슈를 비판적으로 정리)

        ■ 4. 항목별 평가 점수 (10점 만점)
        - 성능: [점수] / 디자인: [점수] / 가성비: [점수] / 품질: [점수]
        - **종합 점수: [평균 점수]**

        ■ 5. 맞춤 추천 가이드
        - ✅ 이런 분께 추천: (용도, 취향 등)
        - ❌ 이런 분께 비추천: (기대치, 특정 환경 등)

        ■ 6. 최종 결론
        (현재 구매 가치가 있는지 한 줄 평)
        """
        
        # 3. 답변 생성
        response = model.generate_content(prompt)
        return {"answer": response.text, "data_info": f"검증 데이터 {len(refined_data)}건 기반 분석 완료"}

    except Exception as e:
        # 에러 발생 시 상세 메시지 반환
        return JSONResponse(content={"error": f"분석 중 오류 발생: {str(e)}"}, status_code=500)
