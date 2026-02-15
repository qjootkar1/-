import os
import re
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import google.generativeai as genai

# [경로 보정] templates 폴더를 절대 경로로 지정하여 '하얀 화면' 에러 방지
current_dir = os.path.dirname(os.path.abspath(__file__))
template_path = os.path.join(current_dir, "templates")
templates = Jinja2Templates(directory=template_path)

app = FastAPI()

# 환경 변수 설정 (Render에서 설정한 키값 로드)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(model_name="models/gemini-1.5-flash")

# 1. Serper API로 실시간 리뷰 수집
async def fetch_search_data(product_name: str):
    url = "https://google.serper.dev/search"
    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json'
    }
    data = { "q": f"{product_name} 실제 사용 리뷰 장단점 특징", "gl": "kr", "hl": "ko" }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=data, timeout=10.0)
            res_json = response.json()
            # 검색 결과의 snippet(요약문) 추출
            return [item.get("snippet", "") for item in res_json.get("organic", [])]
        except Exception as e:
            print(f"Search Error: {e}")
            return []

# 2. 제품 일치 검증 필터
def filter_relevant_data(raw_texts, product_name):
    filtered = []
    keywords = [k for k in product_name.lower().split() if len(k) > 0]
    for text in raw_texts:
        if any(kw in text.lower() for kw in keywords):
            clean_text = re.sub(r'\s+', ' ', text).strip()
            if len(clean_text) > 20:
                filtered.append(clean_text)
    return list(set(filtered))[:15]

# 3. 메인 페이지 전송
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# 4. 분석 요청 처리 (AI 프롬프트 복구)
@app.post("/chat")
async def handle_analysis(user_input: str = Form(...)):
    if not GEMINI_API_KEY or not SERPER_API_KEY:
        return JSONResponse(content={"error": "API 키 설정이 누락되었습니다."}, status_code=500)

    try:
        raw_data = await fetch_search_data(user_input)
        refined_data = filter_relevant_data(raw_data, user_input)
        
        if not refined_data:
            return {"answer": f"'{user_input}'에 대한 정확한 리뷰 데이터를 찾지 못했습니다.", "data_info": "검증 데이터 없음"}

        context = "\n".join(refined_data)

        # 사용자가 원했던 상세 분석 프롬프트
        prompt = f"""
        사용자 요청 제품: [{user_input}]
        아래 검색된 실시간 리뷰 데이터를 기반으로 정밀 보고서를 작성하세요. 
        관련 없는 제품 정보가 섞여 있다면 철저히 무시하고 오직 [{user_input}]에 대해서만 작성하세요.

        ---
        [수집된 데이터]
        {context}
        ---

        [보고서 양식]
        ■ 1. 핵심 특징 및 품질
        (제품의 주요 기술력과 소재, 마감 수준 설명)

        ■ 2. 주요 장점 (Pros)
        (실제 사용자들이 만족하는 포인트를 불렛포인트로 정리)

        ■ 3. 주요 단점 (Cons)
        (사용 시 겪는 불편함, 품질 불만, 아쉬운 점을 솔직하게 정리)

        ■ 4. 항목별 평가 점수 (10점 만점)
        - 성능: [점수] / 디자인: [점수] / 가성비: [점수] / 품질: [점수]
        - **종합 점수: [평균 점수]**

        ■ 5. 맞춤 추천 가이드
        - ✅ 이런 분께 추천: (용도, 취향, 환경 등)
        - ❌ 이런 분께 비추천: (특정 단점에 민감한 경우 등)

        ■ 6. 최종 결론
        (현재 이 제품을 구매할 가치가 있는지 한 줄 평)
        """

        response = model.generate_content(prompt)
        
        return {
            "answer": response.text,
            "data_info": f"실시간 데이터 {len(refined_data)}건 분석 완료"
        }
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
