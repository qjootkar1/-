import os
import json
import time
import hashlib
import asyncio
import logging
import random
from collections import defaultdict
from typing import AsyncGenerator, List, Dict, Optional, Tuple
from urllib.parse import urlparse, parse_qs

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from bs4 import BeautifulSoup
from contextlib import asynccontextmanager

# ── 로깅 ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("product-analyzer")

# ── 환경변수 & 상수 ────────────────────────────────────────────────
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GROQ_KEY   = os.getenv("GROQ_API_KEY")
SERPER_KEY = os.getenv("SERPER_API_KEY")

MAX_PRODUCT_NAME_LEN  = 100
MAX_CHARS_PER_PAGE    = 2500
MAX_TOTAL_CONTEXT     = 15000
MAX_CONCURRENT_FETCH  = 5
RATE_LIMIT_PER_MINUTE = 10
CACHE_TTL_SECONDS     = 3600

REQUEST_TIMEOUT = httpx.Timeout(12.0, read=40.0, connect=10.0, pool=10.0)

# 공개 인스턴스
SEARXNG_INSTANCES = ["https://searx.tiekoetter.net", "https://searx.be", "https://priv.au", "https://search.sapti.me"]
WHOOGLE_INSTANCES = ["https://whoogle.sdf.org", "https://whoogle.privacydev.net"]
METAGER_ENDPOINT = "https://metager.org/meta/meta.ger3"

# ── 전역 상태 ──────────────────────────────────────────────────────
_rate_limit_tracker: Dict[str, List[float]] = defaultdict(list)
_result_cache: Dict[str, Tuple[float, str]] = {}

# ── Lifespan ───────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    client = httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        limits=httpx.Limits(max_connections=25, max_keepalive_connections=10),
        headers={"User-Agent": "Mozilla/5.0 (compatible; ProductAnalyzer/1.0)"},
        follow_redirects=True,
    )
    app.state.http_client = client
    logger.info("HTTP 클라이언트 초기화 완료")
    yield
    await client.aclose()
    logger.info("HTTP 클라이언트 종료")

app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

# ── Rate Limit ─────────────────────────────────────────────────────
@app.middleware("http")
async def rate_limit_mw(request: Request, call_next):
    if request.url.path == "/analyze":
        ip = request.client.host or "unknown"
        now = time.time()
        window = [t for t in _rate_limit_tracker[ip] if t > now - 60]
        if len(window) >= RATE_LIMIT_PER_MINUTE:
            return JSONResponse({"error": True, "message": "Too many requests"}, 429)
        _rate_limit_tracker[ip] = window + [now]
    return await call_next(request)

# ── 입력 검증 ──────────────────────────────────────────────────────
def sanitize_product_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise HTTPException(400, "제품명을 입력해 주세요.")
    if len(cleaned) > MAX_PRODUCT_NAME_LEN:
        raise HTTPException(400, f"제품명은 {MAX_PRODUCT_NAME_LEN}자 이하로 입력해 주세요.")
    cleaned = "".join(c for c in cleaned if ord(c) >= 32 and c != "\x00")
    for bad in ["<script", "javascript:", "data:", "--", ";"]:
        if bad.lower() in cleaned.lower():
            raise HTTPException(400, "유효하지 않은 입력입니다.")
    return cleaned

# ── 캐시 ───────────────────────────────────────────────────────────
def cache_key(name: str) -> str:
    return hashlib.sha256(name.strip().lower().encode()).hexdigest()

def get_cache(name: str) -> Optional[str]:
    key = cache_key(name)
    if key in _result_cache:
        ts, val = _result_cache[key]
        if time.time() - ts < CACHE_TTL_SECONDS:
            return val
        del _result_cache[key]
    return None

def set_cache(name: str, value: str):
    key = cache_key(name)
    if len(_result_cache) >= 100:
        oldest = min(_result_cache, key=lambda k: _result_cache[k][0])
        del _result_cache[oldest]
    _result_cache[key] = (time.time(), value)

# ── 페이지 추출 ────────────────────────────────────────────────────
async def fetch_page_text(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.get(url, timeout=22)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "header", "footer", "nav", "form", "aside", "iframe", "noscript", "svg"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        return " ".join(text.split())[:MAX_CHARS_PER_PAGE]
    except Exception:
        return ""

# ── 검색 엔진 ──────────────────────────────────────────────────────
async def search_serper(query: str, client: httpx.AsyncClient) -> List[str]:
    if not SERPER_KEY:
        return []
    try:
        r = await client.post(
            "https://google.serper.dev/search",
            json={"q": query, "gl": "kr", "hl": "ko", "num": 10},
            headers={"X-API-KEY": SERPER_KEY},
            timeout=12
        )
        r.raise_for_status()
        data = r.json()
        return [item["link"] for item in data.get("organic", []) if "link" in item]
    except Exception as e:
        logger.warning(f"Serper 오류: {e}")
        return []

async def search_free_metasearch(query: str, client: httpx.AsyncClient, target_count: int = 12) -> List[str]:
    engines = [
        ("SearXNG", SEARXNG_INSTANCES, _search_searxng),
        ("Whoogle", WHOOGLE_INSTANCES, _search_whoogle),
        ("MetaGer", [METAGER_ENDPOINT], _search_metager),
    ]
    random.shuffle(engines)
    collected = set()
    for name, bases, func in engines:
        if len(collected) >= target_count:
            break
        try:
            urls = await func(query, target_count - len(collected), client, bases)
            if urls:
                collected.update(urls)
        except Exception:
            pass
    return list(collected)[:target_count]

async def _search_searxng(q: str, want: int, c: httpx.AsyncClient, bases: List[str]) -> List[str]:
    random.shuffle(bases)
    for base in bases:
        try:
            r = await c.get(f"{base}/search", params={"q": q, "format": "json"}, timeout=10)
            if r.status_code == 200:
                data = r.json()
                return [r["url"] for r in data.get("results", []) if r.get("url", "").startswith("http")][:want]
        except:
            pass
    return []

async def _search_whoogle(q: str, want: int, c: httpx.AsyncClient, bases: List[str]) -> List[str]:
    random.shuffle(bases)
    for base in bases:
        try:
            r = await c.get(f"{base}/search", params={"q": q}, timeout=12)
            if r.status_code != 200: continue
            soup = BeautifulSoup(r.text, "html.parser")
            links = []
            for a in soup.select("a[href]"):
                href = a["href"]
                if href.startswith(("http://", "https://")):
                    links.append(href)
                elif "url=" in href:
                    parsed = urlparse(href)
                    real = parse_qs(parsed.query).get("url", [None])[0]
                    if real and real.startswith(("http://", "https://")):
                        links.append(real)
            unique = list(dict.fromkeys(links))[:want]
            if unique:
                return unique
        except Exception:
            pass
    return []

async def _search_metager(q: str, want: int, c: httpx.AsyncClient, bases: List[str]) -> List[str]:
    try:
        r = await c.get(bases[0], params={"eingabe": q, "focus": "web", "out": "json"}, timeout=12)
        if r.status_code == 200:
            data = r.json()
            return [res["link"] for res in data.get("results", []) if "link" in res][:want]
    except:
        pass
    return []

# ── 리뷰 수집 ──────────────────────────────────────────────────────
async def collect_review_data(product: str, client: httpx.AsyncClient) -> Tuple[str, Dict]:
    community = "site:fmkorea.com OR site:clien.net OR site:dcinside.com OR site:ppomppu.co.kr OR site:ruliweb.com OR site:dogdrip.net"
    q_kr = f'"{product}" (후기 OR 장단점 OR 리뷰 OR 사용기 OR 실사용 OR 불만 OR 추천) {community}'
    q_en = f'"{product}" (review OR pros OR cons OR experience OR problem OR recommend)'

    serper_urls = await search_serper(q_kr, client) if SERPER_KEY else []
    free_urls = await search_free_metasearch(q_kr, client, 15)

    if len(free_urls) < 6:
        free_en = await search_free_metasearch(q_en, client, 8)
        free_urls = list(set(free_urls + free_en))

    all_urls = list(set(serper_urls + free_urls))
    logger.info(f"후보 URL: {len(all_urls)}개")

    if not all_urls:
        return "", {"raw": 0, "fetched": 0, "used": 0, "chars": 0}

    sem = asyncio.Semaphore(MAX_CONCURRENT_FETCH)

    async def bounded_fetch(u: str) -> str:
        async with sem:
            return await fetch_page_text(client, u)

    texts = await asyncio.gather(*[bounded_fetch(u) for u in all_urls[:12]], return_exceptions=True)
    valid = [t for t in texts if isinstance(t, str) and len(t.strip()) > 80]

    logger.info(f"유효 페이지: {len(valid)}개")

    collected = []
    total = 0
    for txt in valid:
        remain = MAX_TOTAL_CONTEXT - total
        if remain <= 0:
            break
        piece = txt[:remain]
        collected.append(piece)
        total += len(piece)

    context = "\n\n".join(collected)

    stats = {
        "raw_urls": len(all_urls),
        "fetched_pages": len(valid),
        "used_pages": len(collected),
        "context_chars": total
    }

    return context, stats

# ── 프롬프트 ──────────────────────────────────────────────────────
def build_prompt(product_name: str, context: str) -> str:
    p = f'"{product_name}"'
    if context.strip():
        data_section = f"""[엄격 규칙]
1. {p} 문자열이 정확히 등장한 문장만 사용
2. 다른 모델·세대 절대 포함 금지
3. 근거 없는 내용은 "데이터 부족" 처리
원문: {context}"""
    else:
        data_section = f"실시간 데이터 없음. 모든 항목에 [AI 추정] 필수. {p} 외 정보 금지."

    return f"""당신은 매우 엄격한 제품 분석 전문가입니다. 분석 대상은 오직 {p} 하나뿐입니다.

출력 (마크다운)

## 1. 핵심 요약
## 2. 주요 특징
## 3. 장점 (근거 필수)
## 4. 단점 (근거 필수)
## 5. 사용자 반응
## 6. 점수
| 항목   | 점수 | 근거 |
|--------|------|------|
| 성능   |      |      |
| 디자인 |      |      |
| 내구성 |      |      |
| 편의성 |      |      |
| 가성비 |      |      |
| 종합   |      |      |
## 7. 추천/비추천
## 8. 결론

---
{data_section}

최종 지시: {p} 외 모든 데이터 무시."""

# ── AI 호출 ───────────────────────────────────────────────────────
async def call_ai(client: httpx.AsyncClient, prompt: str) -> Tuple[str, str]:
    if GEMINI_KEY:
        try:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}",
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": 0.35, "maxOutputTokens": 4096}},
                timeout=70
            )
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return text, "Gemini"
        except Exception as e:
            logger.warning(f"Gemini 실패: {e}")

    if GROQ_KEY:
        try:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}"},
                json={
                    "model": "llama3-70b-8192",
                    "messages": [
                        {"role": "system", "content": "한국어로 전문적으로 답변하세요."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.35,
                    "max_tokens": 3800
                },
                timeout=80
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            return text, "Groq"
        except Exception as e:
            logger.error(f"Groq 실패: {e}")

    raise RuntimeError("AI 호출 실패")

# ── SSE 스트리밍 (최종 강화 버전) ─────────────────────────────────
async def analysis_stream(product: str) -> AsyncGenerator[str, None]:
    def emit(p: int, msg: str, **extra):
        return f"data: {json.dumps({'p': p, 'm': msg, **extra}, ensure_ascii=False)}\n\n"

    client = app.state.http_client

    try:
        cached = get_cache(product)
        if cached:
            yield emit(30, "캐시 로드 중...")
            yield emit(100, "분석 완료", answer=cached)
            return

        # 연결 유지용 heartbeat
        yield emit(5, "연결 확인 중...")
        await asyncio.sleep(1.5)

        yield emit(10, "리뷰 수집 중...")

        context, stats = await collect_review_data(product, client)

        yield emit(50, f"수집 완료 → {stats['raw_urls']}개 URL → {stats['fetched_pages']}개 페이지")
        await asyncio.sleep(0.6)

        # AI 분석 시작 전 heartbeat 강화
        for i in range(6):
            yield emit(62 + i*3, "AI 분석 진행 중...")
            await asyncio.sleep(4)   # 4초마다 heartbeat → 브라우저 연결 유지

        prompt = build_prompt(product, context)
        answer, model = await call_ai(client, prompt)

        if context:
            set_cache(product, answer)

        source = "리뷰 기반" if context else "AI 추정"
        yield emit(100, f"{model} 분석 완료 [{source}]", answer=answer)

    except Exception as e:
        logger.exception("분석 스트림 오류")
        yield emit(-1, "분석 중 오류가 발생했습니다. 다시 시도해 주세요.", error=True)

# ── 라우트 ─────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    try:
        with open("templates/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        logger.error("templates/index.html 파일을 찾을 수 없습니다.")
        return HTMLResponse(content="<h1>templates/index.html 파일이 없습니다.</h1>", status_code=500)

@app.get("/analyze")
async def analyze(product: str = ""):
    clean = sanitize_product_name(product)
    return StreamingResponse(
        analysis_stream(clean),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "gemini": bool(GEMINI_KEY),
        "groq": bool(GROQ_KEY),
        "serper": bool(SERPER_KEY)
    }
