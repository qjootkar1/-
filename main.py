import os
import re
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import google.generativeai as genai

# 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
template_path = os.path.join(current_dir, "templates")
templates = Jinja2Templates(directory=template_path)

app = FastAPI()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

# --- [수정] 404 에러 해결을 위한 모델 초기화 로직 ---
model = None
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        
        # [핵심] models/ 접두사 없이 모델명만 시도하거나, 
        # API가 현재 세션에서 허용하는 정확한 이름을 리스트에서 직접 뽑아옵니다.
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        print(f"DEBUG: Available models -> {available_models}") # Render 로그에서 확인 가능
        
        # 1. 'gemini-1.5-flash' (접두사 없음) 
        # 2. 'models/gemini-1.5-flash' (표준)
        # 3. 리스트에 있는 첫 번째 1.5-flash 모델
        if "gemini-1.5-flash" in available_models:
            target = "gemini-1.5-flash"
        elif "models/gemini-1.5-flash" in available_models:
            target = "models/gemini-1.5-flash"
        else:
            target = next((n for n in available_models if "1.5-flash" in n), "models/gemini-1.5-flash")
            
        model = genai.GenerativeModel(model_name=target)
    except Exception as e:
        print(f"Init Error: {e}")

# --- 1차: Python 필터링 (기존 로직 유지) ---
async def fetch_search_data(product_name: str):
    if not SERPER_API_KEY: return []
    url = "https://google.serper.dev/search"
    headers = {'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'}
    data = { "q": f"{product_name} 실제 사용기 장단점 품질 이슈", "gl": "kr", "hl": "ko" }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=data, timeout=10.0)
            response.raise_for_status() 
            return [item.get("snippet", "") for item in response.json().get("organic", [])]
        except Exception as e:
            print(f"Serper Fetch Error: {e}")
            return []

def filter_exact_match(raw_texts, product_name):
    filtered = []
    keywords = [k.lower() for k in product_name.split() if len(k) > 1]
    if not keywords: return raw_texts[:5]
    for text in raw_texts:
        match_count = sum(1 for kw in keywords if kw in text.lower())
        if match_count / len(keywords) >= 0.7:
            clean_text = re.sub(r'\s+', ' ', text).strip()
            filtered.append(clean_text)
    return list(dict.fromkeys(filtered))[:12]

# --- 2차: 제미나이 정밀 분석 (기존 로직 유지) ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/chat")
async def handle_analysis(user_input: str = Form(...)):
    if not model: 
        return JSONResponse(content={"error": "모델 설정 확인 필요"}, status_code=500)
    
    try:
        raw_data = await fetch_search_data(user_input)
        refined_data = filter_exact_match(raw_data, user_input)
        
        if not refined_data:
            return {"answer": f"'{user_input}'와 일치하는 데이터를 찾지 못했습니다.", "data_info": "검증 실패"}

        context = "\n".join([f"데이터[{i}]: {t}" for i, t in enumerate(refined_data)])

        prompt = f"""
        당신은 초정밀 제품 분석가입니다. 
        요청 제품: [{user_input}]
        
        [데이터]
        {context}

        ---
        [지시]
        1. 데이터 중 [{user_input}]과 무관한 내용은 철저히 제외하세요. (제미나이 자체 필터링)
        2. 아래 양식에 맞춰 아주 상세하게 리포트를 작성하세요.

        ■ 1. 핵심 특징 및 품질 상세 분석
        ■ 2. 주요 장점 (Pros)
        ■ 3. 주요 단점 및 고질적 이슈 (Cons)
        ■ 4. 항목별 평가 점수 (10점 만점)
        ■ 5. 타겟 맞춤형 추천 가이드
        ■ 6. 전문가 최종 결론
        """
        
        response = model.generate_content(prompt)
        return {"answer": response.text, "data_info": f"이중 검증 완료 ({len(refined_data)}건 분석)"}

    except Exception as e:
        # 에러 메시지에 모델 정보 포함하여 디버깅 용이하게 변경
        return JSONResponse(content={"error": f"모델({model.model_name}) 분석 오류: {str(e)}"}, status_code=500)
