import os
import asyncio
import json
import logging
import re
from typing import AsyncGenerator, List
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import httpx
from duckduckgo_search import DDGS
from bs4 import BeautifulSoup  # HTML 파싱 안정화

# --- 로깅 및 설정 ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("UltimateAnalyzer")

# API 키 설정
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
SERPER_KEY = os.environ.get("SERPER_API_KEY", "")

@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
    app.state.client = httpx.AsyncClient(timeout=30.0, limits=limits, follow_redirects=True)
    yield
    await app.state.client.aclose()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- 데이터 정제 ---
def clean_html(raw_html: str) -> str:
    """HTML 태그 제거 및 핵심 텍스트 추출"""
    if not raw_html:
        return ""
    try:
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style", "header", "footer", "nav", "form", "iframe", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
        return " ".join(text.split())[:12000]
    except Exception as e:
        logger.error(f"HTML 정제 오류: {e}")
        return raw_html[:2000]

# --- 다중 검색 엔진 ---
async def fetch_search_results(client: httpx.AsyncClient, query: str) -> List[str]:
    urls = []
    # 1. Serper
    if SERPER_KEY:
        try:
            resp = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"},
                json={"q": query, "num": 5}
            )
            if resp.status_code == 200:
                urls.extend([r.get("link") for r in resp.json().get("organic", []) if r.get("link")])
        except Exception as e:
            logger.error(f"Serper Error: {e}")

    # 2. DuckDuckGo
    try:
        with DDGS() as ddgs:
            ddg_results = await asyncio.to_thread(lambda: list(ddgs.text(query, max_results=5)))
            urls.extend([r.get("href") for r in ddg_results if r.get("href")])
    except Exception as e:
        logger.error(f"DDG Error: {e}")

    # 3. Reddit
    try:
        reddit_query = f"{query} site:reddit.com"
        with DDGS() as ddgs:
            reddit_results = await asyncio.to_thread(lambda: list(ddgs.text(reddit_query, max_results=3)))
            urls.extend([r.get("href") for r in reddit_results if r.get("href")])
    except Exception as e:
        logger.error(f"Reddit Search Error: {e}")

    return list(set(urls))

# --- 실시간 분석 엔진 ---
async def final_analysis_stream(product_name: str) -> AsyncGenerator[str, None]:
    client = app.state.client
    try:
        # 단계 1
        yield f"data: {json.dumps({'p': 20, 'm': '🌐 검색 중...'})}\n\n"
        search_query = f"{product_name} 실사용 단점 장점 후기"
        target_urls = await fetch_search_results(client, search_query)
        if not target_urls:
            raise Exception("검색 결과 없음")

        # 단계 2
        yield f"data: {json.dumps({'p': 50, 'm': f'📦 {len(target_urls)}개 소스 수집 중...'})}\n\n"
        semaphore = asyncio.Semaphore(5)  # 동시 요청 제한

        async def safe_fetch(url):
            async with semaphore:
                try:
                    resp = await client.get(url, timeout=15.0)
                    if resp.status_code == 200:
                        return clean_html(resp.text)
                except Exception as e:
                    logger.error(f"Fetch Error {url}: {e}")
                return ""

        contexts = await asyncio.gather(*[safe_fetch(url) for url in target_urls])
        full_context = "\n\n".join([c for c in contexts if c])

        # 단계 3
        yield f"data: {json.dumps({'p': 80, 'm': '🧠 AI 분석 중...'})}\n\n"
        final_answer, model_used = None, ""
        prompt = f"제품 '{product_name}' 리뷰 데이터를 분석해라. 광고 제외, 장점/단점 구분.\n\n데이터:\n{full_context}"

        # Gemini
        if not final_answer and GEMINI_KEY:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
                r = await client.post(url, json={"contents": [{"parts": [{"text": prompt}]}]})
                if r.status_code == 200:
                    data = r.json()
                    final_answer = (
                        data.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")
                    )
                    model_used = "Gemini 1.5 Flash"
            except Exception as e:
                logger.error(f"Gemini Error: {e}")

        # Groq
        if not final_answer and GROQ_KEY:
            try:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_KEY}"},
                    json={"model": "llama3-70b-8192", "messages": [{"role": "user", "content": prompt}]}
                )
                if r.status_code == 200:
                    data = r.json()
                    final_answer = (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
                    model_used = "Groq (Llama 3)"
            except Exception as e:
                logger.error(f"Groq Error: {e}")

        if not final_answer:
            raise Exception("AI 모델 응답 없음")

        # 단계 4
        yield f"data: {json.dumps({'p': 100, 'm': f'✅ {model_used} 분석 완료!', 'answer': final_answer})}\n\n"

    except Exception as e:
        logger.error(f"Fatal Error: {str(e)}")
        yield f"data: {json.dumps({'p': 0, 'm': f'❌ 오류 발생: {str(e)}', 'error': True})}\n\n"

@app.get("/analyze")
async def analyze_endpoint(product: str):
    return StreamingResponse(final_analysis_stream(product), media_type="text/event-stream")
