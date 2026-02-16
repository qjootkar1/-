import os
import re
from datetime import datetime, timedelta
from typing import Optional, List
import httpx
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from functools import lru_cache
import google.generativeai as genai

# ============ 설정 및 초기화 ============

# 경로 설정 (Render 환경 최적화)
current_dir = os.path.dirname(os.path.abspath(__file__))
template_path = os.path.join(current_dir, "templates")
templates = Jinja2Templates(directory=template_path)

app = FastAPI(
    title="AI 제품 분석기",
    description="실사용 리뷰 기반 제품 분석 서비스",
    version="2.0"
)

# CORS 설정 (보안)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션에서는 특정 도메인만 허용
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# 환경 변수
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")

# API 키 검증
if GEMINI_API_KEY:
    print(f"✅ GEMINI_API_KEY 확인됨: {GEMINI_API_KEY[:10]}...")
else:
    print("❌ GEMINI_API_KEY 환경 변수가 설정되지 않았습니다!")

if SERPER_API_KEY:
    print(f"✅ SERPER_API_KEY 확인됨: {SERPER_API_KEY[:10]}...")
else:
    print("⚠️ SERPER_API_KEY 환경 변수가 없습니다 (검색 기능 비활성화)")

# ============ Gemini 모델 초기화 (최적화 + Fallback) ============

model = None
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        
        # 여러 모델명 시도 (404 에러 방지)
        model_candidates = [
            "gemini-2.0-flash-exp",           # 최신 실험 버전
            "gemini-1.5-flash-002",           # 안정 버전 (숫자 버전)
            "gemini-1.5-flash-latest",        # Latest 태그
            "gemini-1.5-pro-latest",          # Pro 버전
            "models/gemini-1.5-flash",        # models/ 프리픽스
            "models/gemini-2.0-flash-exp",    # models/ 프리픽스 실험
            "gemini-pro",                     # 레거시 이름
        ]
        
        model_initialized = False
        for model_name in model_candidates:
            try:
                print(f"🔄 모델 시도 중: {model_name}")
                test_model = genai.GenerativeModel(model_name)
                # 간단한 테스트로 모델 작동 확인
                test_model.count_tokens("test")
                model = test_model
                print(f"✅ Gemini 모델 초기화 성공: {model_name}")
                model_initialized = True
                break
            except Exception as e:
                print(f"⚠️ {model_name} 실패: {str(e)[:80]}")
                continue
        
        if not model_initialized:
            # 마지막 시도: 사용 가능한 모델 자동 탐지
            print("🔍 사용 가능한 모델 자동 탐지 중...")
            try:
                available_models = []
                for m in genai.list_models():
                    if 'generateContent' in m.supported_generation_methods:
                        available_models.append(m.name)
                
                if available_models:
                    # Flash 모델 우선, 없으면 첫 번째 모델 사용
                    selected = next((m for m in available_models if 'flash' in m.lower()), available_models[0])
                    model = genai.GenerativeModel(selected)
                    print(f"✅ Gemini 모델 자동 선택 성공: {selected}")
                    print(f"   (사용 가능 모델: {', '.join(available_models[:3])}...)")
                else:
                    print("❌ 사용 가능한 모델이 없습니다")
                    model = None
            except Exception as list_error:
                print(f"❌ 모델 탐지 실패: {list_error}")
                model = None
                
    except Exception as e:
        print(f"❌ Gemini 초기화 최종 실패: {e}")
        model = None

# ============ 보안 및 검증 함수 ============

def validate_input(text: str) -> bool:
    """입력 검증 - XSS, SQL Injection 방지"""
    if not text or len(text.strip()) == 0:
        return False
    if len(text) > 100:  # 제품명은 100자 이하
        return False
    # 위험한 문자 패턴 체크
    dangerous_patterns = ['<script', 'javascript:', 'onerror=', 'onclick=', '--', ';', 'DROP', 'DELETE']
    text_lower = text.lower()
    return not any(pattern in text_lower for pattern in dangerous_patterns)

def sanitize_input(text: str) -> str:
    """입력 정제 - 특수문자 제거"""
    # 기본 문자, 숫자, 공백, 하이픈만 허용
    return re.sub(r'[^a-zA-Z0-9가-힣\s\-]', '', text).strip()

# ============ 캐싱 (성능 최적화) ============

# 간단한 메모리 캐시 (최근 10개 결과 저장)
_cache = {}
_cache_timestamps = {}
CACHE_DURATION = timedelta(hours=1)  # 1시간 캐시

def get_from_cache(key: str) -> Optional[dict]:
    """캐시에서 결과 가져오기"""
    if key in _cache:
        timestamp = _cache_timestamps.get(key)
        if timestamp and datetime.now() - timestamp < CACHE_DURATION:
            print(f"💾 캐시 히트: {key}")
            return _cache[key]
        else:
            # 만료된 캐시 제거
            del _cache[key]
            del _cache_timestamps[key]
    return None

def save_to_cache(key: str, value: dict):
    """결과를 캐시에 저장 (최대 10개)"""
    if len(_cache) >= 10:
        # 가장 오래된 항목 제거 (LRU)
        oldest_key = min(_cache_timestamps, key=_cache_timestamps.get)
        del _cache[oldest_key]
        del _cache_timestamps[oldest_key]
    
    _cache[key] = value
    _cache_timestamps[key] = datetime.now()
    print(f"💾 캐시 저장: {key}")

# ============ 검색 및 필터링 (최적화) ============

# httpx 클라이언트 재사용 (연결 풀링)
http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(12.0),
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
)

async def fetch_search_data(product_name: str) -> List[str]:
    """검색 데이터 수집 (최적화)"""
    if not SERPER_API_KEY:
        return []
    
    url = "https://google.serper.dev/search"
    headers = {'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'}
    data = {
        "q": f'"{product_name}" 실사용 후기 리뷰 장단점 2024 2025 2026',
        "gl": "kr",
        "hl": "ko",
        "num": 15
    }
    
    try:
        response = await http_client.post(url, headers=headers, json=data)
        response.raise_for_status()
        results = response.json().get("organic", [])
        return [item.get("snippet", "") for item in results if item.get("snippet")]
    except Exception as e:
        print(f"⚠️ 검색 오류: {e}")
        return []

# 정규식 컴파일 (재사용을 위해 전역으로)
WHITESPACE_PATTERN = re.compile(r'\s+')
NUMBER_PATTERN = re.compile(r'\d+')

def filter_exact_match(raw_texts: List[str], product_name: str) -> List[str]:
    """정확한 제품명 필터링 (최적화)"""
    if not raw_texts or not product_name:
        return []
    
    filtered = []
    product_lower = product_name.lower().strip()
    keywords = [k.lower() for k in product_name.split() if len(k) > 1]
    
    if not keywords:
        return raw_texts[:5]
    
    # 제품명에 숫자가 있는지 미리 확인
    has_digits = any(char.isdigit() for char in product_name)
    product_numbers = set(NUMBER_PATTERN.findall(product_name)) if has_digits else set()
    
    # 스팸 키워드 (소문자로 미리 변환)
    spam_keywords = {"로그인", "장바구니", "쿠키", "404", "error", "페이지를 찾을 수 없습니다"}
    
    for text in raw_texts:
        text_lower = text.lower()
        
        # 스팸 체크 (먼저 수행 - 빠른 제외)
        if any(spam in text_lower for spam in spam_keywords):
            continue
        
        # 정확한 제품명 매칭
        has_exact_product = product_lower in text_lower
        
        # 키워드 매칭률
        match_count = sum(1 for kw in keywords if kw in text_lower)
        match_ratio = match_count / len(keywords)
        
        # 숫자 매칭 (필요한 경우에만)
        exclude = False
        if has_digits and product_numbers:
            text_numbers = set(NUMBER_PATTERN.findall(text))
            if not product_numbers.issubset(text_numbers):
                exclude = True
        
        # 필터링 조건
        if not exclude and (has_exact_product or match_ratio >= 0.7):
            clean_text = WHITESPACE_PATTERN.sub(' ', text).strip()
            if clean_text and len(clean_text) > 20:  # 너무 짧은 텍스트 제외
                filtered.append(clean_text)
    
    # 중복 제거 (순서 유지)
    seen = set()
    unique_filtered = []
    for item in filtered:
        if item not in seen:
            seen.add(item)
            unique_filtered.append(item)
    
    result = unique_filtered[:15]
    print(f"필터링 결과: {len(raw_texts)}개 → {len(result)}개")
    return result

# ============ 프롬프트 템플릿 (재사용) ============

ANALYSIS_PROMPT_TEMPLATE = """당신은 제품 분석 전문가입니다.
제품: [{product_name}]

수집된 실사용 리뷰 데이터:
{context}

---
**분석 지침:**
1. 위 데이터에서 [{product_name}]과 정확히 일치하는 정보만 사용하세요
2. 다른 모델의 정보는 절대 포함하지 마세요
3. 각 섹션을 구체적이고 상세하게 작성하되, 구조를 유지하세요

---
**아래 형식으로 상세한 분석 리포트를 작성하세요:**

## 📊 1. 데이터 수집 상태
[2-3문장으로 수집된 리뷰의 양과 신뢰도 평가]

## 🔍 2. 제품 핵심 특징
[5-6문장으로 주요 스펙, 기술, 디자인 특징, 타겟층을 상세히 설명]

## ✅ 3. 주요 장점
**장점 1: [제목]**
[3-4문장으로 실사용자들의 구체적인 만족 사례와 이유 설명]

**장점 2: [제목]**
[3-4문장으로 실사용자들의 구체적인 만족 사례와 이유 설명]

**장점 3: [제목]**
[3-4문장으로 실사용자들의 구체적인 만족 사례와 이유 설명]

## ⚠️ 4. 주요 단점
**단점 1: [제목]**
[3-4문장으로 실사용자들이 겪은 구체적인 불편함과 문제점 설명]

**단점 2: [제목]**
[3-4문장으로 실사용자들이 겪은 구체적인 불편함과 문제점 설명]

**단점 3: [제목]**
[3-4문장으로 실사용자들이 겪은 구체적인 불편함과 문제점 설명]

## 📈 5. 항목별 평가
- **성능**: X/10 - [1-2문장 근거]
- **디자인/마감**: X/10 - [1-2문장 근거]
- **가성비**: X/10 - [1-2문장 근거]
- **품질 안정성**: X/10 - [1-2문장 근거]
- **사용자 만족도**: X/10 - [1-2문장 근거]

### 종합 점수: X.X/10

## 🎯 6. 구매 추천 가이드
### ✅ 강력 추천
[3-4가지 구체적인 추천 대상과 이유를 각 2-3문장으로 설명]

### ❌ 비추천
[3-4가지 구체적인 비추천 대상과 이유를 각 2-3문장으로 설명]

## 💭 7. 전문가 최종 결론
[5-6문장으로 종합 평가, 가격 대비 가치, 구매 추천도를 상세히 설명]

---
**중요:** 모든 섹션을 완전히 작성하세요."""

# ============ 메인 분석 엔드포인트 ============

@app.post("/chat")
async def handle_analysis(user_input: str = Form(...)):
    """제품 분석 메인 엔드포인트 (최적화)"""
    
    # 1. 입력 검증
    if not validate_input(user_input):
        raise HTTPException(status_code=400, detail="유효하지 않은 입력입니다.")
    
    # 2. 입력 정제
    clean_input = sanitize_input(user_input)
    if not clean_input:
        raise HTTPException(status_code=400, detail="제품명을 입력해주세요.")
    
    # 3. API 키 확인
    if not GEMINI_API_KEY or not model:
        return JSONResponse(
            content={"error": "AI 모델을 사용할 수 없습니다. 관리자에게 문의하세요."},
            status_code=503
        )
    
    # 4. 캐시 확인
    cache_key = clean_input.lower()
    cached_result = get_from_cache(cache_key)
    if cached_result:
        return cached_result
    
    try:
        # 5. 데이터 수집
        raw_data = await fetch_search_data(clean_input)
        refined_data = filter_exact_match(raw_data, clean_input)
        
        # 6. 데이터 부족 처리
        if not refined_data:
            result = {
                "answer": f"""## ⚠️ 데이터 수집 실패

**'{clean_input}'에 대한 신뢰할 수 있는 실사용 리뷰를 찾지 못했습니다.**

가능한 원인:
- 📅 최근 출시된 제품으로 아직 리뷰가 충분하지 않음
- 🔍 제품명이 정확하지 않거나 오타가 있을 수 있음
- 🌐 해당 제품의 온라인 리뷰가 부족함

**추천 조치:**
1. 제품의 정확한 모델명을 다시 확인해주세요
2. 브랜드명과 함께 검색해보세요 (예: "삼성 갤럭시 A56")
3. 출시된 지 얼마 안 된 제품이라면 시간이 지난 후 다시 시도해주세요
""",
                "data_info": "검증된 데이터 없음"
            }
            save_to_cache(cache_key, result)
            return result
        
        # 7. Context 최적화 (너무 길면 잘라내기)
        context = "\n".join([f"[{i+1}] {t[:500]}" for i, t in enumerate(refined_data)])
        if len(context) > 8000:  # 약 2000 토큰
            context = context[:8000] + "\n...(이하 생략)"
        
        # 8. 프롬프트 생성
        prompt = ANALYSIS_PROMPT_TEMPLATE.format(
            product_name=clean_input,
            context=context
        )
        
        # 9. Gemini API 호출 (최적화된 설정)
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                max_output_tokens=8192,
                top_p=0.95,
                top_k=40,
            ),
            safety_settings=[
                {"category": cat, "threshold": "BLOCK_NONE"}
                for cat in [
                    "HARM_CATEGORY_HARASSMENT",
                    "HARM_CATEGORY_HATE_SPEECH",
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "HARM_CATEGORY_DANGEROUS_CONTENT"
                ]
            ]
        )
        
        # 10. 응답 추출
        result_text = response.text if hasattr(response, 'text') else str(response)
        
        # 11. 결과 패키징
        result = {
            "answer": result_text,
            "data_info": f"✅ 분석 완료 (신뢰도 높은 데이터 {len(refined_data)}건 기반)"
        }
        
        # 12. 캐시 저장
        save_to_cache(cache_key, result)
        
        return result
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"❌ 분석 오류:\n{error_detail}")
        
        return JSONResponse(
            content={
                "error": "분석 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
                "error_type": type(e).__name__
            },
            status_code=500
        )

# ============ 웹 인터페이스 ============

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """메인 페이지"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {
        "status": "healthy",
        "gemini": "available" if model else "unavailable",
        "serper": "available" if SERPER_API_KEY else "unavailable",
        "cache_size": len(_cache)
    }

# ============ 종료 시 정리 ============

@app.on_event("shutdown")
async def shutdown_event():
    """서버 종료 시 리소스 정리"""
    await http_client.aclose()
    print("✅ HTTP 클라이언트 종료")
