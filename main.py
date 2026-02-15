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

# 2. 제미나이 모델 설정 (비판적 리뷰어 역할 부여)
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    system_instruction=(
        "당신은 실시간 수집된 데이터를 바탕으로 제품을 분석하는 10년 경력의 전문 리뷰어입니다. "
        "제공된 로우 데이터에서 광고와 노이즈를 걸러내고, 제품의 품질, 성능, 가성비를 분석하여 "
        "엄격하게 10점 만점의 점수를 매기고 추천/비추천 대상을 명확히 구분하세요."
    )
)

# 3. FastAPI 단계의 1차 필터링 함수 (노이즈 제거)
def filter_and_clean_data(raw_texts, product_name):
    filtered = []
    # 제거할 노이즈 키워드
    noise = ["광고", "협찬", "쿠팡", "제휴", "이벤트", "판매", "무료배송"]
    
    for text in raw_texts:
        # 제품명이 포함되어 있고 광고가 아닌 문장만 필터링
        if product_name.replace(" ", "") in text.replace(" ", ""):
            if not any(word in text for word in noise):
                # 특수문자 제거 및 줄바꿈 정리
                clean = re.sub(r'\s+', ' ', text).strip()
                if len(clean) > 30:  # 너무 짧은 문장은 정보 가치가 없어 제외
                    filtered.append(clean)
    
    # 중복 제거 후 최대 15~20개로 제한하여 제미나이의 부하를 줄임
    return list(set(filtered))[:20]

# 4. 실제 실시간 웹 크롤링 함수
async def crawl_product_info(product_name: str):
    # 구글 검색 결과에서 뉴스나 리뷰 요약문을 긁어옴
    url = f"https://www.google.com/search?q={product_name}+실제+리뷰+특징+단점"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=10.0)
            if response.status_code != 200:
                return []
            
            soup = BeautifulSoup(response.text, "html.parser")
            # 검색 결과의 스니펫(요약 문구)들을 모두 수집
            snippets = [tag.get_text() for tag in soup.find_all(['span', 'div']) if len(tag.get_text()) > 20]
            return snippets
        except Exception:
            return []

# 5. 메인 API 엔드포인트
@app.post("/chat")
async def analyze_product(user_input: str = Form(...)):
    if not API_KEY:
        return JSONResponse(content={"error": "GEMINI_API_KEY 설정이 필요합니다."}, status_code=500)

    try:
        # Step 1: 웹 크롤링 수행
        raw_data = await crawl_product_info(user_input)

        # Step 2: FastAPI 파이썬 로직으로 1차 필터링 및 검수
        refined_data = filter_and_clean_data(raw_data, user_input)
        context = "\n".join(refined_data) if refined_data else "실시간 정보를 찾지 못했습니다. 일반적인 제품 지식으로 답변하세요."

        # Step 3: 제미나이에게 최종 분석 요청 (사용자 의도 반영)
        prompt = f"""
        사용자 요청 제품: {user_input}
        
        [수집된 실시간 데이터]:
        {context}

        위 데이터를 바탕으로 다음 보고서를 작성하세요:
        1. 제품 품질 및 퀄리티 평가: 소재, 마감, 내구성에 대해 언급할 것.
        2. 10점 만점 점수표: (성능, 디자인, 가성비, 품질) 각 점수와 이유 기재.
        3. 종합 총점: (위 점수들을 종합한 평균 점수)
        4. 추천 대상: 이 제품을 사면 매우 만족할 사람들의 특징.
        5. 비추천 대상: 이 제품을 사면 반드시 후회할 사람들과 그 이유.
        6. 가성비 분석: 현재 시장 가격 대비 품질이 적절한가?

        모든 답변은 매우 객관적이고 비판적이어야 하며, 광고성 말투를 배제하세요.
        """

        response = model.generate_content(prompt)
        
        return {
            "answer": response.text,
            "data_info": f"수집된 데이터 {len(raw_data)}개 중 {len(refined_data)}개를 검수하여 분석함."
        }

    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
