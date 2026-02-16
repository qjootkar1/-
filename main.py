import os
import re
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import google.generativeai as genai

# 경로 설정 (Render 환경 최적화)
current_dir = os.path.dirname(os.path.abspath(__file__))
template_path = os.path.join(current_dir, "templates")
templates = Jinja2Templates(directory=template_path)

app = FastAPI()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

# --- [에러 해결] Gemini 모델 동적 설정 ---
model = None
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # 404 에러 방지: 현재 사용 가능한 모델명을 실시간으로 조회하여 할당
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        target = next((n for n in available_models if "1.5-flash" in n), "models/gemini-1.5-flash")
        model = genai.GenerativeModel(model_name=target)
        print(f"DEBUG: Active Model -> {target}")
    except Exception as e:
        print(f"Init Error: {e}")

# --- 1차: Python 필터링 (검색어 일치율 70% 이상 검수) ---
async def fetch_search_data(product_name: str):
    if not SERPER_API_KEY: return []
    url = "https://google.serper.dev/search"
    headers = {'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'}
    # 검색 쿼리 고도화 (단점 및 고질병 유도)
    data = { "q": f"{product_name} 실제 사용기 장단점 품질 이슈 고질병", "gl": "kr", "hl": "ko" }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=data, timeout=12.0)
            return [item.get("snippet", "") for item in response.json().get("organic", [])]
        except: return []

def filter_exact_match(raw_texts, product_name):
    filtered = []
    keywords = [k.lower() for k in product_name.split() if len(k) > 1]
    if not keywords: return raw_texts[:5]

    for text in raw_texts:
        match_count = sum(1 for kw in keywords if kw in text.lower())
        # 제품 핵심 키워드 매칭률 70% 이상만 통과
        if match_count / len(keywords) >= 0.7:
            # 스팸성 텍스트 필터링
            if any(junk in text for junk in ["로그인", "장바구니", "쿠키"]): continue
            clean_text = re.sub(r'\s+', ' ', text).strip()
            filtered.append(clean_text)
    return list(dict.fromkeys(filtered))[:12]

# --- 2차: 제미나이 정밀 분석 및 이중 검증 ---
@app.post("/chat")
async def handle_analysis(user_input: str = Form(...)):
    if not model: return JSONResponse(content={"error": "AI 모델 설정 실패"}, status_code=500)
    
    try:
        raw_data = await fetch_search_data(user_input)
        refined_data = filter_exact_match(raw_data, user_input)
        
        if not refined_data:
            return {"answer": f"'{user_input}'와 일치하는 신뢰할 수 있는 리뷰 데이터를 찾지 못했습니다.", "data_info": "검증 실패"}

        context = "\n".join([f"데이터[{i}]: {t}" for i, t in enumerate(refined_data)])

        # 다시 복구된 초정밀 전문가 프롬프트
        prompt = f"""
        당신은 초정밀 제품 분석가이자 소비자 권익 보호 전문가입니다.
        사용자의 요청 제품: [{user_input}]

        [수집된 데이터 리스트]
        {context}

        ---
        [필터링 및 분석 지시사항]
        1. 제공된 데이터 중 [{user_input}]과 관련이 없거나 다른 모델의 정보라면 절대 분석에 포함하지 마세요. (제미나이 자체 2차 검수)
        2. 광고성 찬사보다는 실제 사용자의 '불편함'과 '품질 결함'을 찾아내는 데 집중하세요.
        3. 아래의 양식을 엄격히 준수하여 전문적인 리포트를 작성하세요.

        ■ 1. 핵심 특징 및 품질 상세 분석
        - 제품의 빌드 퀄리티, 마감 수준, 실제 적용된 기술의 완성도를 전문가 시선에서 상세히 분석하세요.

        ■ 2. 주요 장점 (Pros)
        - 실사용자들이 공통적으로 만족하는 포인트 3가지 이상을 구체적인 근거와 함께 서술하세요.

        ■ 3. 주요 단점 및 고질적 이슈 (Cons)
        - 실제 사용자들이 겪는 하드웨어/소프트웨어적 결함, 고질적인 불편함, 가격 대비 아쉬운 점을 냉정하게 비판하세요.

        ■ 4. 항목별 평가 점수 (10점 만점)
        - 성능: [ /10] | 디자인/마감: [ /10] | 가성비: [ /10] | 품질 안정성: [ /10]
        - **종합 점수: [평균] / 10**

        ■ 5. 타겟 맞춤형 추천 가이드
        - ✅ 추천: 어떤 환경이나 목적을 가진 사용자에게 최고의 가치를 주는가?
        - ❌ 비추천: 어떤 단점을 참지 못하는 사용자가 구매를 피해야 하는가?

        ■ 6. 전문가 최종 결론
        - 수집된 모든 근거를 바탕으로 이 제품의 구매 가치에 대한 최종 판단을 요약하세요.
        """
        
        response = model.generate_content(prompt)
        return {"answer": response.text, "data_info": f"이중 검증 완료 (고순도 데이터 {len(refined_data)}건 분석)"}

    except Exception as e:
        return JSONResponse(content={"error": f"분석 중 오류 발생: {str(e)}"}, status_code=500)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
