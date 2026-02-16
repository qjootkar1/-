import os
import re
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import google.generativeai as genai

# 경로 인식 오류 방지
current_dir = os.path.dirname(os.path.abspath(__file__))
template_path = os.path.join(current_dir, "templates")
templates = Jinja2Templates(directory=template_path)

app = FastAPI()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

# --- [에러 해결 핵심] Gemini 모델 설정 ---
model = None
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        
        # 404 에러를 방지하기 위해 가용한 모델 리스트를 탐색하여 
        # API가 현재 허용하는 정확한 모델명을 할당합니다.
        model_list = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # 최신 API(v1beta) 환경에서는 'models/gemini-1.5-flash-8b'나 'models/gemini-1.5-flash' 중 
        # 존재하는 것을 우선적으로 선택합니다.
        if "models/gemini-1.5-flash" in model_list:
            target = "models/gemini-1.5-flash"
        elif "models/gemini-1.5-flash-latest" in model_list:
            target = "models/gemini-1.5-flash-latest"
        else:
            # 리스트에 있는 이름 중 적절한 1.5-flash 모델을 선택
            target = next((n for n in model_list if "1.5-flash" in n), "gemini-1.5-flash")
            
        model = genai.GenerativeModel(model_name=target)
        print(f"DEBUG: Model successfully bound to -> {target}")
        
    except Exception as e:
        print(f"Init Error: {e}")

# --- 1차: Python 로직 필터링 ---
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
        # 핵심 키워드 매칭률 70% 이상만 통가
        if match_count / len(keywords) >= 0.7:
            clean_text = re.sub(r'\s+', ' ', text).strip()
            filtered.append(clean_text)
    return list(dict.fromkeys(filtered))[:12]

# --- 2차: 제미나이 정밀 분석 및 이중 필터링 ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/chat")
async def handle_analysis(user_input: str = Form(...)):
    if not model: 
        return JSONResponse(content={"error": "모델 설정 확인이 필요합니다."}, status_code=500)
    
    try:
        raw_data = await fetch_search_data(user_input)
        refined_data = filter_exact_match(raw_data, user_input)
        
        if not refined_data:
            return {"answer": f"'{user_input}'와 일치하는 데이터를 찾지 못했습니다.", "data_info": "검증 실패"}

        context = "\n".join([f"데이터[{i}]: {t}" for i, t in enumerate(refined_data)])

        prompt = f"""
        당신은 초정밀 제품 분석가입니다. 
        사용자의 요청 제품: [{user_input}]

        [수집된 데이터 리스트]
        {context}

        ---
        [필터링 지시 사항 - 매우 중요]
        1. 위 데이터 중 [{user_input}]과 관련이 없거나, 다른 모델의 정보가 섞여 있다면 절대 분석에 포함하지 마세요. (제미나이가 직접 맥락을 판단하여 제외할 것)
        2. 만약 모든 데이터가 불일치한다면 "일치하는 정보가 없습니다"라고만 답하세요.
        3. 광고성 멘트는 무시하고 오직 실사용자의 '품질'과 '경험'에 집중하세요.

        [보고서 작성 양식 - 매우 자세하게]
        ■ 1. 핵심 특징 및 품질 상세 분석
        - 제품의 빌드 퀄리티, 마감 수준, 적용된 기술의 실효성을 상세히 서술하세요.

        ■ 2. 주요 장점 (Pros)
        - 실사용자들이 공통적으로 꼽는 핵심 만족 포인트를 3가지 이상 상세히 기술하세요.

        ■ 3. 주요 단점 및 고질적 이슈 (Cons)
        - 실제 고질병, 결함, 가성비 불만 등을 냉정하게 비판하세요.

        ■ 4. 항목별 평가 점수 (10점 만점)
        - 성능: [ /10] | 디자인: [ /10] | 가성비: [ /10] | 품질: [ /10]
        - **종합 점수: [평균] / 10**

        ■ 5. 타겟 맞춤형 추천 가이드
        - ✅ 추천: 어떤 환경의 사용자에게 최고의 가치를 주는가?
        - ❌ 비추천: 어떤 성향의 사용자가 구매하면 후회하는가?

        ■ 6. 전문가 최종 결론
        - 이 제품의 구매 가치를 최종 요약하세요.
        """
        
        response = model.generate_content(prompt)
        return {"answer": response.text, "data_info": f"이중 검증 완료 (데이터 {len(refined_data)}건 분석)"}

    except Exception as e:
        return JSONResponse(content={"error": f"분석 중 오류 발생: {str(e)}"}, status_code=500)
