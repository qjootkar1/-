import os
import re
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import google.generativeai as genai

# 경로 절대화 (하얀 화면 방지)
current_dir = os.path.dirname(os.path.abspath(__file__))
template_path = os.path.join(current_dir, "templates")
templates = Jinja2Templates(directory=template_path)

app = FastAPI()

# 환경 변수 가져오기
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

# [핵심 수정] Gemini 모델 설정
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # 가장 안정적인 최신 별칭을 사용합니다.
        model = genai.GenerativeModel(model_name="gemini-1.5-flash-latest")
    except Exception as e:
        print(f"Model Init Error: {e}")

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
        return JSONResponse(content={"error": "API 키가 설정되지 않았습니다."}, status_code=500)
    
    try:
        raw_data = await fetch_search_data(user_input)
        refined_data = filter_relevant_data(raw_data, user_input)
        context = "\n".join(refined_data) if refined_data else "정보 부족. 일반 지식으로 분석."

        # 살려낸 정밀 프롬프트
        prompt = f"""
        제품명: [{user_input}]
        데이터: {context}
        ---
        위 데이터를 기반으로 아래 양식에 맞춰 리포트를 작성하세요.
        1. 핵심 특징
        2. 주요 장단점 (불렛포인트)
        3. 항목별 점수 (성능, 디자인, 가성비, 품질)
        4. 추천/비추천 대상
        5. 최종 결론
        """
        
        # 답변 생성 시도
        response = model.generate_content(prompt)
        return {"answer": response.text, "data_info": f"{len(refined_data)}건 분석 완료"}

    except Exception as e:
        # 에러 발생 시 모델명을 다르게 하여 한 번 더 시도 (보험)
        try:
            alt_model = genai.GenerativeModel(model_name="gemini-1.5-flash")
            response = alt_model.generate_content(prompt)
            return {"answer": response.text, "data_info": "보조 모델로 분석 완료"}
        except:
            return JSONResponse(content={"error": f"최종 에러: {str(e)}"}, status_code=500)
