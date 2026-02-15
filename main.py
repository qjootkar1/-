import os
import re
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import google.generativeai as genai

# 경로 보정
current_dir = os.path.dirname(os.path.abspath(__file__))
template_path = os.path.join(current_dir, "templates")
templates = Jinja2Templates(directory=template_path)

app = FastAPI()

# 환경 변수
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
# 모델 선언부 수정 (model_name 명시 및 최신 규격 적용)
model = genai.GenerativeModel(model_name="gemini-1.5-flash")

async def fetch_search_data(product_name: str):
    url = "https://google.serper.dev/search"
    headers = {'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'}
    data = { "q": f"{product_name} 실제 사용 리뷰 장단점 특징", "gl": "kr", "hl": "ko" }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=data, timeout=10.0)
            res_json = response.json()
            return [item.get("snippet", "") for item in res_json.get("organic", [])]
        except: return []

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
        return JSONResponse(content={"error": "API 키 설정 누락"}, status_code=500)
    try:
        raw_data = await fetch_search_data(user_input)
        refined_data = filter_relevant_data(raw_data, user_input)
        
        if not refined_data:
            return {"answer": f"'{user_input}'에 대한 데이터를 찾지 못했습니다.", "data_info": "검증 데이터 없음"}

        context = "\n".join(refined_data)

        # AI 프롬프트 (요청하신 항목들 모두 포함)
        prompt = f"""
        사용자 요청 제품: [{user_input}]
        아래 실시간 리뷰 데이터를 기반으로 정밀 보고서를 작성하세요.

        ---
        [수집된 데이터]
        {context}
        ---

        [보고서 양식]
        ■ 1. 핵심 특징 및 품질
        (제품의 주요 강점과 마감 수준 설명)

        ■ 2. 주요 장점 (Pros)
        (불렛포인트로 정리)

        ■ 3. 주요 단점 (Cons)
        (실제 사용 시 불편함과 품질 이슈 정리)

        ■ 4. 항목별 평가 점수 (10점 만점)
        - 성능: [점수] / 디자인: [점수] / 가성비: [점수] / 품질: [점수]
        - **종합 점수: [평균 점수]**

        ■ 5. 맞춤 추천 가이드
        - ✅ 추천: (누구에게 좋은가?)
        - ❌ 비추천: (누구에게 별로인가?)

        ■ 6. 최종 결론
        (한 줄 평)
        """
        
        response = model.generate_content(prompt)
        return {"answer": response.text, "data_info": f"{len(refined_data)}건 분석 완료"}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
