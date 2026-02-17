import os
import asyncio
import json
import logging
import re
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import httpx
from duckduckgo_search import DDGS

# --- 로깅 설정 ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FinalPerfectAnalyzer")

# API 키 (환경변수)
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
SERPER_KEY = os.environ.get("SERPER_API_KEY", "")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Reddit 등의 차단을 피하기 위해 User-Agent 설정
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    }
    app.state.client = httpx.AsyncClient(timeout=30.0, headers=headers, follow_redirects=True)
    yield
    await app.state.client.aclose()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- 유틸리티: HTML 정제 ---
def clean_content(text: str) -> str:
    if not text: return ""
    # 불필요한 태그 제거
    text = re.sub(r'<(script|style|header|footer|nav|form|iframe|noscript).*?>.*?</\1>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    return " ".join(text.split())[:10000]

# --- 핵심: 멀티 소스 검색 로직 (Serper + Reddit + DDG) ---
async def get_all_urls(client: httpx.AsyncClient, product: str) -> list:
    urls = []
    
    # 1. Serper (Google Search) - 가장 품질 좋음
    if SERPER_KEY:
        try:
            r = await client.post("https://google.serper.dev/search", 
                headers={"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"},
                json={"q": f"{product} 실사용 후기 장점 단점", "num": 5})
            if r.status_code == 200:
                urls.extend([item['link'] for item in r.json().get('organic', [])])
        except Exception as e: logger.error(f"Serper Error: {e}")

    # 2. Reddit 전용 검색 (Reddit은 별도의 헤더와 쿼리 필요)
    try:
        with DDGS() as ddgs:
            # 래딧 결과만 따로 수집
            reddit_res = await asyncio.to_thread(lambda: list(ddgs.text(f"{product} review site:reddit.com", max_results=3)))
            urls.extend([r['href'] for r in reddit_res if 'href' in r])
    except Exception as e: logger.error(f"Reddit Search Error: {e}")

    # 3. DuckDuckGo 일반 검색 (백업)
    try:
        with DDGS() as ddgs:
            ddg_res = await asyncio.to_thread(lambda: list(ddgs.text(f"{product} 실사용 단점", max_results=4)))
            urls.extend([r['href'] for r in ddg_res if 'href' in r])
    except Exception as e: logger.error(f"DDG Error: {e}")

    return list(set(urls)) # 중복 제거

# --- 실시간 분석 스트림 엔진 ---
async def main_engine(product: str) -> AsyncGenerator[str, None]:
    client = app.state.client
    try:
        # [Step 1] 검색 시작 (20%)
        yield f"data: {json.dumps({'p': 20, 'm': '🌐 Google, Reddit에서 리뷰 소스를 탐색 중입니다...'})}\n\n"
        target_urls = await get_all_urls(client, product)
        
        if not target_urls:
            raise Exception("검색 결과가 없습니다.")

        # [Step 2] 데이터 수집 (50%)
        yield f"data: {json.dumps({'p': 50, 'm': f'📦 {len(target_urls)}개의 소스에서 본문을 추출하고 광고를 제거 중입니다...'})}\n\n"
        
        # 병렬 수집
        tasks = [client.get(url, timeout=12.0) for url in target_urls]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_texts = []
        for i, res in enumerate(responses):
            if isinstance(res, httpx.Response) and res.status_code == 200:
                valid_texts.append(f"[출처 {i+1}]: {clean_content(res.text)}")
        
        context = "\n\n".join(valid_texts)

        # [Step 3] AI 분석 로테이션 (80%)
        yield f"data: {json.dumps({'p': 80, 'm': '🧠 AI 모델(Gemini/Groq/OpenRouter)을 연결하여 리포트를 작성 중입니다...'})}\n\n"
        
        final_answer = ""
        used_model = ""
        prompt = f"제품 '{product}'에 대한 실사용자들의 진짜 장단점을 요약해줘. 인터넷 광고글은 무시하고, 실제 불만사항과 칭찬을 객관적으로 분석해서 1~10점 평점과 함께 리포트로 써줘.\n\n데이터:\n{context}"

        # --- AI 로테이션 시도 ---
        # 1. Gemini
        if GEMINI_KEY:
            try:
                g_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
                r = await client.post(g_url, json={"contents": [{"parts": [{"text": prompt}]}]})
                if r.status_code == 200:
                    final_answer = r.json()['candidates'][0]['content']['parts'][0]['text']
                    used_model = "Gemini 1.5 Flash"
            except: pass

        # 2. Groq (백업)
        if not final_answer and GROQ_KEY:
            try:
                r = await client.post("https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_KEY}"},
                    json={"model": "llama3-70b-8192", "messages": [{"role": "user", "content": prompt}]})
                if r.status_code == 200:
                    final_answer = r.json()['choices'][0]['message']['content']
                    used_model = "Groq (Llama 3)"
            except: pass
            
        # 3. OpenRouter (최종 백업)
        if not final_answer and OPENROUTER_KEY:
            try:
                r = await client.post("https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
                    json={"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": prompt}]})
                if r.status_code == 200:
                    final_answer = r.json()['choices'][0]['message']['content']
                    used_model = "OpenRouter (DeepSeek)"
            except: pass

        if not final_answer:
            raise Exception("모든 AI 모델이 응답하지 않습니다.")

        # [Step 4] 완료 (100%)
        yield f"data: {json.dumps({'p': 100, 'm': f'✅ {used_model} 분석 완료!', 'answer': final_answer})}\n\n"

    except Exception as e:
        logger.error(f"Error: {e}")
        yield f"data: {json.dumps({'p': 0, 'm': f'❌ 오류: {str(e)}', 'error': True})}\n\n"

@app.get("/analyze")
async def analyze(product: str):
    return StreamingResponse(main_engine(product), media_type="text/event-stream")
