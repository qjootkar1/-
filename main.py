import os
import asyncio
import json
import logging
import re
import time
from typing import AsyncGenerator, List, Dict
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import httpx
from duckduckgo_search import DDGS

# --- 로깅 및 설정 ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("UltimateAnalyzer")

# API 키 설정 (환경 변수에서 로드)
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
SERPER_KEY = os.environ.get("SERPER_API_KEY", "") # Serper.dev API

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 전역 HTTP 클라이언트 설정 (타임아웃 및 연결 제한 최적화)
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
    app.state.client = httpx.AsyncClient(timeout=30.0, limits=limits, follow_redirects=True)
    yield
    await app.state.client.aclose()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- 데이터 정제 및 유틸리티 ---
def clean_html(raw_html: str) -> str:
    """HTML 태그 제거 및 핵심 텍스트 추출 (v5.3 기준)"""
    if not raw_html: return ""
    clean = re.sub(r'<(script|style|header|footer|nav|form|iframe|noscript).*?>.*?</\1>', '', raw_html, flags=re.DOTALL)
    clean = re.sub(r'<[^>]+>', ' ', clean)
    return " ".join(clean.split())[:12000]

# --- 다중 검색 엔진 엔진 (Serper, DDG, Reddit) ---
async def fetch_search_results(client: httpx.AsyncClient, query: str):
    urls = []
    
    # 1. Serper (Google Search) - 가장 정확함
    if SERPER_KEY:
        try:
            resp = await client.post("https://google.serper.dev/search", 
                headers={"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"},
                json={"q": query, "num": 5})
            if resp.status_code == 200:
                urls.extend([r['link'] for r in resp.json().get('organic', [])])
        except Exception as e: logger.error(f"Serper Error: {e}")

    # 2. DuckDuckGo - 무료 및 익명성
    try:
        with DDGS() as ddgs:
            ddg_results = await asyncio.to_thread(lambda: list(ddgs.text(query, max_results=5)))
            urls.extend([r['href'] for r in ddg_results if 'href' in r])
    except Exception as e: logger.error(f"DDG Error: {e}")

    # 3. Reddit 전용 검색 (커뮤니티 여론 수집)
    try:
        reddit_query = f"{query} site:reddit.com"
        with DDGS() as ddgs:
            reddit_results = await asyncio.to_thread(lambda: list(ddgs.text(reddit_query, max_results=3)))
            urls.extend([r['href'] for r in reddit_results if 'href' in r])
    except Exception as e: logger.error(f"Reddit Search Error: {e}")

    return list(set(urls)) # 중복 제거

# --- 실시간 분석 엔진 (Streaming) ---
async def final_analysis_stream(product_name: str) -> AsyncGenerator[str, None]:
    client = app.state.client
    
    try:
        # [단계 1] 검색 가동 (20%)
        yield f"data: {json.dumps({'p': 20, 'm': '🌐 Google, Reddit, DDG에서 실사용 리뷰를 탐색 중입니다...'})}\n\n"
        search_query = f"{product_name} 실사용 단점 장점 후기"
        target_urls = await fetch_search_results(client, search_query)
        
        if not target_urls:
            raise Exception("검색 결과를 찾을 수 없습니다.")

        # [단계 2] 웹 수집 및 정제 (50%)
        yield f"data: {json.dumps({'p': 50, 'm': f'📦 {len(target_urls)}개의 소스에서 데이터를 수집하고 정제 중...'})}\n\n"
        fetch_tasks = [client.get(url, timeout=15.0) for url in target_urls]
        responses = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        
        contexts = []
        for i, resp in enumerate(responses):
            if isinstance(resp, httpx.Response) and resp.status_code == 200:
                contexts.append(f"[Source {i}]: {clean_html(resp.text)}")
        
        full_context = "\n\n".join(contexts)

        # [단계 3] AI 로테이션 분석 (80%)
        yield f"data: {json.dumps({'p': 80, 'm': '🧠 AI 모델 로테이션(Gemini/Groq/OpenRouter) 가동 중...'})}\n\n"
        
        final_answer = None
        model_used = ""
        prompt = f"제품 '{product_name}'에 대해 수집된 다음 리뷰 데이터를 분석해라. 광고는 제외하고 실제 사용자의 비판과 칭찬을 구분하여 리포트를 작성해라.\n\n데이터:\n{full_context}"

        # AI 로테이션 시도
        # 1. Gemini
        if not final_answer and GEMINI_KEY:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
                r = await client.post(url, json={"contents": [{"parts": [{"text": prompt}]}]})
                if r.status_code == 200:
                    final_answer = r.json()['candidates'][0]['content']['parts'][0]['text']
                    model_used = "Gemini 1.5 Flash"
            except: pass

        # 2. Groq
        if not final_answer and GROQ_KEY:
            try:
                r = await client.post("https://api.groq.com/openai/v1/chat/completions", 
                    headers={"Authorization": f"Bearer {GROQ_KEY}"},
                    json={"model": "llama3-70b-8192", "messages": [{"role": "user", "content": prompt}]})
                if r.status_code == 200:
                    final_answer = r.json()['choices'][0]['message']['content']
                    model_used = "Groq (Llama 3)"
            except: pass

        if not final_answer:
            raise Exception("모든 AI 모델이 응답하지 않습니다. API 키 설정을 확인하세요.")

        # [단계 4] 최종 완료 (100%)
        yield f"data: {json.dumps({'p': 100, 'm': f'✅ {model_used} 분석 완료!', 'answer': final_answer})}\n\n"

    except Exception as e:
        logger.error(f"Fatal Error: {str(e)}")
        yield f"data: {json.dumps({'p': 0, 'm': f'❌ 오류 발생: {str(e)}', 'error': True})}\n\n"

@app.get("/analyze")
async def analyze_endpoint(product: str):
    return StreamingResponse(final_analysis_stream(product), media_type="text/event-stream")
