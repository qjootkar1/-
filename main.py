import os
import json
import asyncio
import logging
import re
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from contextlib import asynccontextmanager

# --- 로깅 설정 ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("analyzer")

# API 키 설정
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 안정성을 위해 브라우저 헤더 설정 (차단 방지)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    app.state.client = httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, read=50.0), 
        headers=headers, 
        follow_redirects=True,
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
    )
    yield
    await app.state.client.aclose()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- 웹 수집 로직 (안정성 강화) ---
async def fetch_page(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.get(url)
        if r.status_code != 200: return ""
        soup = BeautifulSoup(r.text, "html.parser")
        for s in soup(['script', 'style', 'header', 'footer', 'nav', 'form', 'aside']): s.decompose()
        return soup.get_text(" ", strip=True)
    except: return ""

async def collect_reviews(product_name: str, client: httpx.AsyncClient) -> str:
    urls = []
    try:
        with DDGS() as ddgs:
            # 비동기 병목 방지를 위해 스레드 활용
            results = await asyncio.to_thread(lambda: list(ddgs.text(f"{product_name} 실사용 후기 단점", max_results=6)))
            urls = [r.get("href") for r in results if r and r.get("href")]
    except Exception as e:
        logger.error(f"Search error: {e}")

    if not urls: return ""
    tasks = [fetch_page(client, u) for u in urls]
    pages = await asyncio.gather(*tasks, return_exceptions=True)
    valid_pages = [p for p in pages if isinstance(p, str) and p]
    return "\n\n".join(valid_pages)[:10000]

# --- 프롬프트 빌더 (기존 고급 버전 유지) ---
def build_prompt(product_name: str, context: str) -> str:
    return f"""
# 역할
너는 데이터 기반 전문 제품 분석 리서처다. 오직 제공된 리뷰 데이터만 기반으로 분석한다.
# 🔴 절대 규칙
- "{product_name}" 이 제품만 분석하라. (Pro, Max, 이전 세대 언급 금지)
- 데이터에 없는 정보 생성 금지. 불확실하면 "확인되지 않음" 표기.
# 📊 분석 목표
1.핵심 요약 2.주요 특징 3.장점 상세 4.단점 상세 5.감정 분석 6.점수 평가(성능,디자인,내구성,편의성,가성비) 7.전체 평균 8.추천/비추천 대상 9.종합 결론
# 데이터
{context}
"""


async def call_ai_logic(client: httpx.AsyncClient, prompt: str):
    # 1. Gemini 우선 시도
    if GEMINI_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
            r = await client.post(url, json={"contents":[{"parts":[{"text":prompt}]}]}, timeout=50)
            if r.status_code == 200:
                return r.json()['candidates'][0]['content']['parts'][0]['text'], "Gemini"
        except: pass

    # 2. Groq 폴백
    if GROQ_KEY:
        try:
            r = await client.post("https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}"},
                json={"model": "llama3-70b-8192", "messages": [{"role": "user", "content": prompt}]})
            if r.status_code == 200:
                return r.json()['choices'][0]['message']['content'], "Groq"
        except: pass
    raise Exception("AI 응답을 가져올 수 없습니다.")

# --- 스트리밍 엔드포인트 ---
async def final_analysis_stream(product_name: str) -> AsyncGenerator[str, None]:
    client = app.state.client
    try:
        yield f"data: {json.dumps({'p':20, 'm':'🔍 리뷰 데이터를 수집하고 있습니다...'})}\n\n"
        context = await collect_reviews(product_name, client)
        
        if not context:
            raise Exception("데이터 수집 실패")

        yield f"data: {json.dumps({'p':60, 'm':'🧠 AI가 심층 분석 리포트를 작성 중입니다...'})}\n\n"
        prompt = build_prompt(product_name, context)
        final_answer, model_name = await call_ai_logic(client, prompt)

        yield f"data: {json.dumps({'p':100, 'm':f'✅ {model_name} 분석 완료', 'answer': final_answer})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'p':0, 'm':f'오류: {str(e)}', 'error': True})}\n\n"

@app.get("/analyze")
async def analyze(product: str):
    return StreamingResponse(final_analysis_stream(product), media_type="text/event-stream")
