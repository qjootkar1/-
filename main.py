import os, re, asyncio, traceback, hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import httpx
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai

# --- [1. 설정 및 상수] ---
CACHE_SIZE   = 30
CACHE_TTL    = timedelta(hours=2)
PAGE_FETCH_N = 20
PAGE_CONCUR  = 10
PAGE_CHARS   = 5000
CTX_LIMIT    = 30000
MAX_FILTERED = 60
MIN_LEN      = 40

# [수정] _RE_HTML의 마지막 '|' 제거 (성능 저하 방지)
_RE_DANGER = re.compile(r'<script|javascript:|onerror=|onclick=|onload=|<iframe|DROP\s+TABLE', re.I)
_RE_CLEAN  = re.compile(r'[^a-zA-Z0-9가-힣\s\-\.]')
_RE_SPACE  = re.compile(r'\s+')
_RE_HTML   = re.compile(r'<script[^>]*>.*?</script>|<style[^>]*>.*?</style>', re.DOTALL | re.I)
_RE_TAG    = re.compile(r'<[^>]+>')
_RE_ENT    = re.compile(r'&(?:amp|lt|gt|quot|nbsp|apos);')
_RE_NUMS   = re.compile(r'\d+')

# --- [2. 앱 및 리소스 초기화] ---
app = FastAPI(title="AI 제품 분석기 V4.1", version="4.1")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates"))

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["GET", "POST"], allow_headers=["*"])

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
SERPER_KEY = os.environ.get("SERPER_API_KEY", "")

class GlobalState:
    model: Optional[genai.GenerativeModel] = None
    http: Optional[httpx.AsyncClient] = None
    sem: Optional[asyncio.Semaphore] = None
    cache: Dict = {}
    cache_ts: Dict = {}

state = GlobalState()

@app.on_event("startup")
async def startup():
    print(f"Starting UP: GEMINI {'OK' if GEMINI_KEY else 'NO'} | SERPER {'OK' if SERPER_KEY else 'NO'}")
    state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    state.sem = asyncio.Semaphore(PAGE_CONCUR)
    if GEMINI_KEY:
        genai.configure(api_key=GEMINI_KEY)
        for m_name in ["gemini-2.0-flash-exp", "gemini-1.5-flash"]:
            try:
                m = genai.GenerativeModel(m_name)
                m.count_tokens("ping")
                state.model = m
                print(f"Gemini Ready: {m_name}"); break
            except: continue

@app.on_event("shutdown")
async def shutdown():
    if state.http:
        await state.http.aclose()

# --- [3. 유틸리티 함수] ---
def validate_input(text: str) -> Optional[str]:
    if not text or len(text.strip()) < 2 or len(text) > 80: return None
    if _RE_DANGER.search(text): return None
    return _RE_SPACE.sub(' ', _RE_CLEAN.sub('', text)).strip()

def get_cache(k):
    h = hashlib.md5(k.lower().encode()).hexdigest()
    if h in state.cache and (datetime.now() - state.cache_ts[h] < CACHE_TTL):
        return state.cache[h]
    return None

def set_cache(k, v):
    h = hashlib.md5(k.lower().encode()).hexdigest()
    if len(state.cache) >= CACHE_SIZE:
        oldest = min(state.cache_ts, key=state.cache_ts.get)
        state.cache.pop(oldest); state.cache_ts.pop(oldest)
    state.cache[h] = v; state.cache_ts[h] = datetime.now()

def clean_html(raw: str) -> str:
    t = _RE_HTML.sub(' ', raw)
    t = _RE_TAG.sub(' ', t)
    t = _RE_ENT.sub(' ', t)
    return _RE_SPACE.sub(' ', t).strip()

# --- [4. 데이터 수집 로직] ---
async def fetch_search_data(product: str) -> List[str]:
    if not SERPER_KEY: return []
    queries = [
        f'"{product}" 실사용 후기 단점', f'"{product}" 리뷰 장단점',
        f'"{product}" site:clien.net OR site:ppomppu.co.kr',
        f'"{product}" review pros cons'
    ]
    
    async def search(q):
        try:
            r = await state.http.post("https://google.serper.dev/search", 
                json={"q": q, "gl": "kr", "hl": "ko", "num": 12}, 
                headers={'X-API-KEY': SERPER_KEY}, timeout=8.0)
            return r.json()
        except: return {}

    results = await asyncio.gather(*[search(q) for q in queries])
    unique_links = {}
    extra_texts = []
    
    for data in results:
        for item in data.get("organic", []):
            link = item.get("link")
            if link and link not in unique_links:
                unique_links[link] = item
        if "answerBox" in data: extra_texts.append(str(data["answerBox"]))

    async def fetch_body(item):
        url = item.get("link", "")
        if not url or any(x in url for x in ["youtube.com", "instagram.com", "facebook.com"]): return ""
        async with state.sem:
            try:
                r = await state.http.get(url, timeout=7.0)
                if r.status_code == 200:
                    cleaned = clean_html(r.text[:20000])
                    return cleaned[:PAGE_CHARS] if len(cleaned) > 150 else ""
            except: pass
        return ""

    snippets = [i["snippet"] for i in unique_links.values() if i.get("snippet")]
    bodies = await asyncio.gather(*[fetch_body(i) for i in list(unique_links.values())[:PAGE_FETCH_N]])
    return snippets + [b for b in bodies if b] + extra_texts

def filter_data(raw: List[str], product: str) -> List[str]:
    p_lower = product.lower()
    p_nums = set(_RE_NUMS.findall(product))
    result, seen = [], set()
    for text in raw:
        t_lower = text.lower()
        if len(text) < MIN_LEN or "로그인" in t_lower: continue
        if p_nums and not p_nums.issubset(set(_RE_NUMS.findall(text))): continue
        if p_lower not in t_lower and not any(tk in t_lower for tk in p_lower.split()): continue
        fingerprint = text[:60]
        if fingerprint not in seen:
            seen.add(fingerprint)
            result.append(_RE_SPACE.sub(' ', text).strip())
    return result[:MAX_FILTERED]

# --- [5. 메인 핸들러] ---
PROMPT_TEMPLATE = """당신은 소비자 전문 제품 분석가입니다. [분석 제품]: {product}
[데이터]: {context}
위 리뷰 데이터를 바탕으로 {product}의 장단점을 심층 분석해 주세요. 
반드시 실사용자의 부정적인 피드백을 포함하고, 데이터가 부족하면 '확인 불가'라고 명시하세요."""

@app.post("/chat")
async def handle_analysis(user_input: str = Form(...)):
    product = validate_input(user_input)
    if not product: raise HTTPException(400, "잘못된 입력입니다.")
    if not state.model: return JSONResponse({"error": "AI 준비 중"}, status_code=503)

    if cached := get_cache(product): return cached

    try:
        raw = await fetch_search_data(product)
        filtered = filter_data(raw, product)
        
        if not filtered:
            return {"answer": f"'{product}'에 대한 실사용 리뷰 데이터를 찾지 못했습니다.", "data_info": "0건"}

        filtered.sort(key=len, reverse=True)
        parts, total_len = [], 0
        for i, txt in enumerate(filtered):
            chunk = f"[{i+1}] {txt}\n"
            if total_len + len(chunk) > CTX_LIMIT: break
            parts.append(chunk); total_len += len(chunk)
            
        context = "".join(parts)
        prompt = PROMPT_TEMPLATE.format(product=product, context=context)
        
        # [수정] Gemini 응답 추출 로직 강화 (IndexError 및 Safety 차단 방어)
        response = state.model.generate_content(prompt)
        answer = "분석 결과를 생성할 수 없습니다."
        
        try:
            # 정상적인 텍스트 응답 시도
            if response.candidates and len(response.candidates) > 0:
                # finish_reason 3은 SAFETY(차단)를 의미함
                if response.candidates[0].finish_reason != 3:
                    answer = response.text
                else:
                    # 차단되었더라도 일부 텍스트 파트가 있다면 수집
                    parts_text = [p.text for p in response.candidates[0].content.parts if hasattr(p, 'text')]
                    answer = "".join(parts_text) if parts_text else "안전 정책에 의해 일부 내용이 차단되었습니다."
        except (ValueError, AttributeError, IndexError):
            # fallback: response.text 접근 불가 시 후보군 재탐색
            if response.candidates and response.candidates[0].content.parts:
                answer = "".join(p.text for p in response.candidates[0].content.parts if hasattr(p, 'text'))

        res = {"answer": answer, "data_info": f"분석된 리뷰: {len(parts)}건"}
        set_cache(product, res)
        return res

    except Exception as e:
        print(traceback.format_exc())
        return JSONResponse({"error": "분석 중 오류 발생", "detail": str(e)}, status_code=500)

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
async def health():
    return {"status": "ok", "cache": len(state.cache)}
