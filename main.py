import os
import re
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import google.generativeai as genai

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# 1. Gemini API 설정
API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# 2. 강력한 데이터 필터링 (제품명 일치 여부 및 노이즈 제거)
def strict_filter_data(raw_texts, product_name):
    filtered = []
    # 검색어에서 핵심 키워드 추출 (예: "아이폰 15 프로" -> ["아이폰", "15", "프로"])
    search_keywords = [k for k in product_name.lower().split() if len(k) > 0]
    
    noise_keywords = ["광고", "협찬", "이벤트", "판매", "공구", "무료배송"]
    
    for text in raw_texts:
        lower_text = text.lower()
        
        # [검증 1] 핵심 키워드가 최소 1개 이상 포함되어 있는지 확인 (제품 일치 확인)
        # 만약 제품명이 "아이폰"인데 "갤럭시" 리뷰가 긁혔다면 여기서 걸러짐
        if not any(keyword in lower_text for keyword in search_keywords):
            continue
            
        # [검증 2] 광고성 키워드 제거
        if any(noise in lower_text for noise in noise_keywords):
            continue
            
        # 정제 및 저장
        clean_text = re.sub(r'\s+', ' ', text).strip()
        if len(clean_text) > 30:
            filtered.append(clean_text)
            
    return list(set(filtered))[:15] # 중복 제거 후 최적의 15개 선정

# 3. 실시간 크롤링 함수
async def crawl_product_info(product_name: str):
    # 검색 정확도를 높이기 위해 검색어 조합 최적화
    search_query = f"{product_name} 실제 사용 리뷰 단점 장점"
    url = f"https://www.google.com/search?q={search_query}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=10.0)
            soup = BeautifulSoup(response.text, "html.parser")
            # 검색 결과에서 유의미한 텍스트 블록 수집
            snippets = [tag.get_text() for tag in soup.find_all(['span', 'div']) if len(tag.get_text()) > 35]
            return snippets
        except:
            return []

# 4. 분석 엔드포인트
@app.post("/chat")
async def handle_analysis(user_input: str = Form(...)):
    if not API_KEY:
        return JSONResponse(content={"error": "API 키가 설정되지 않았습니다."}, status_code=500)

    try:
        # Step 1: 크롤링
        raw_data = await crawl_product_info(user_input)

        # Step 2: 파이썬에서 1차 검수 (제품 불일치 데이터 제거)
        refined_data = strict_filter_data(raw_data, user_input)
        
        # Step 3: Gemini에게 전달할 데이터가 아예 없는 경우 처리
        if not refined_data:
            return {"answer": "죄송합니다. 입력하신 제품과 정확히 일치하는 신뢰할 수 있는 리뷰 데이터를 찾지 못했습니다. 제품명을 더 정확하게 입력해 주세요.", "data_info": "검증된 데이터 없음"}

        context = "\n".join(refined_data)

        # Step 4: Gemini에게 '데이터 검증 후 분석' 명령
        prompt = f"""
        사용자가 분석을 요청한 제품명: [{user_input}]
        
        아래는 웹에서 수집된 로우 데이터입니다:
        ---
        {context}
        ---

        [지시사항]
        1. 위 데이터 중 [{user_input}]와 관련 없는 제품의 정보가 있다면 무시하세요.
        2. 오직 [{user_input}]에 대한 정보만 추출하여 다음 양식으로 분석하세요:
           - ■ 제품 특징 및 품질: 마감, 소재, 핵심 기술
           - ■ 주요 장점: 사용자들이 공통적으로 칭찬하는 점
           - ■ 주요 단점: 실제 결함, 불편한 점, 비판적인 의견
           - ■ 항목별 점수(10점 만점): 성능, 디자인, 가성비, 품질
           - ■ 타겟 가이드: ✅추천(어떤 사람?), ❌비추천(어떤 사람?)
        3. 만약 데이터가 충분치 않다면 지어내지 말고 아는 범위 내에서만 작성하세요.
        """

        response = model.generate_content(prompt)
        
        return {
            "answer": response.text,
            "data_info": f"검증된 {len(refined_data)}개의 리뷰를 기반으로 분석함"
        }
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
