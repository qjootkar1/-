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

# 환경 변수 로드
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

# Gemini 설정
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(model_name="gemini-1.5-flash")

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
        return JSONResponse(content={"error": "서버의 API 키 설정이 완료되지 않았습니다."}, status_code=500)
    
    try:
        # Serper API 데이터 수집
        raw_data = await fetch_search_data(user_input)
        refined_data = filter_relevant_data(raw_data, user_input)
        
        context = "\n".join(refined_data) if refined_data else "실시간 리뷰를 찾을 수 없습니다. 일반적인 정보를 바탕으로 작성하세요."

        # 요청하신 상세 분석 프롬프트
        prompt = f"""
        사용자 요청 제품: [{user_input}]
        아래 검색된 데이터를 기반으로 분석 보고서를 작성하세요:
        ---
        {context}
        ---
        ■ 1. 핵심 특징 및 품질
        (제품의 기술적 강점과 마감 수준 설명)

        ■ 2. 주요 장점 (Pros)
        (불렛포인트로 정리)

        ■ 3. 주요 단점 (Cons)
        (불편함이나 품질 이슈를 비판적으로 정리)

        ■ 4. 항목별 평가 점수 (10점 만점)
        - 성능: [점수] / 디자인: [점수] / 가성비: [점수] / 품질: [점수]
        - **종합 점수: [평균 점수]**

        ■ 5. 맞춤 추천 가이드
        - ✅ 이런 분께 추천: (용도, 성향 등)
        - ❌ 이런 분께 비추천: (기대치, 특정 환경 등)

        ■ 6. 최종 결론
        (현재 구매 가치가 있는지 한 줄 요약)
        """
        
        response = model.generate_content(prompt)
        return {"answer": response.text, "data_info": f"검증 데이터 {len(refined_data)}건 기반 분석"}
    except Exception as e:
        return JSONResponse(content={"error": f"분석 중 오류 발생: {str(e)}"}, status_code=500)
