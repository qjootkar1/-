import os
import json
import asyncio
import logging
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, HTMLResponse
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

# 페이지당 최대 수집 글자 수
MAX_CHARS_PER_PAGE = 2000
MAX_TOTAL_CHARS = 12000

# --- HTML 페이지 (프론트엔드 내장) ---
HTML_PAGE = """<!DOCTYPE html>
<html lang="ko" data-theme="light">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI 제품 분석기</title>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    :root {
      --bg: #f2f4f8; --surface: #ffffff; --surface2: #f8f9fc;
      --border: #e2e6ed; --border2: #d0d5de;
      --primary: #2563eb; --primary-hover: #1d4ed8; --primary-light: #eff4ff;
      --danger: #dc2626; --danger-light: #fef2f2;
      --text: #0f1117; --text2: #4b5563; --text3: #9ca3af;
      --success: #16a34a; --radius: 10px;
      --shadow-sm: 0 1px 3px rgba(0,0,0,0.07);
      --shadow: 0 4px 16px rgba(0,0,0,0.08);
      --shadow-lg: 0 12px 40px rgba(0,0,0,0.10);
      --font: 'Malgun Gothic', '맑은 고딕', -apple-system, 'Apple SD Gothic Neo', 'Nanum Gothic', sans-serif;
    }
    [data-theme="dark"] {
      --bg: #0d1117; --surface: #161b22; --surface2: #21262d;
      --border: #30363d; --border2: #3d444d;
      --primary: #3b82f6; --primary-hover: #2563eb; --primary-light: #1a2540;
      --danger: #f87171; --danger-light: #1f1214;
      --text: #e6edf3; --text2: #9198a1; --text3: #545d68;
      --success: #3fb950;
      --shadow-sm: 0 1px 3px rgba(0,0,0,0.3);
      --shadow: 0 4px 16px rgba(0,0,0,0.4);
      --shadow-lg: 0 12px 40px rgba(0,0,0,0.5);
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; }
    body {
      font-family: var(--font); background: var(--bg); color: var(--text);
      min-height: 100vh; transition: background 0.3s, color 0.3s;
      font-size: 14px; line-height: 1.6;
    }
    nav {
      position: sticky; top: 0; z-index: 100;
      background: var(--surface); border-bottom: 1px solid var(--border);
      box-shadow: var(--shadow-sm);
    }
    .nav-inner {
      max-width: 780px; margin: 0 auto; padding: 0 20px; height: 56px;
      display: flex; align-items: center; justify-content: space-between;
    }
    .nav-logo { display: flex; align-items: center; gap: 10px; }
    .nav-icon {
      width: 32px; height: 32px; background: var(--primary); border-radius: 8px;
      display: flex; align-items: center; justify-content: center;
      color: white; font-size: 13px; font-weight: 800; flex-shrink: 0;
    }
    .nav-title { font-size: 16px; font-weight: 700; color: var(--text); }
    .nav-title span { color: var(--primary); }
    .nav-badge {
      font-size: 10px; background: var(--primary-light); color: var(--primary);
      padding: 2px 7px; border-radius: 20px; font-weight: 600;
      border: 1px solid rgba(37,99,235,0.3);
    }
    .theme-toggle {
      width: 36px; height: 36px; border-radius: 8px;
      border: 1px solid var(--border); background: var(--surface2);
      cursor: pointer; display: flex; align-items: center;
      justify-content: center; font-size: 17px; transition: 0.15s;
    }
    .theme-toggle:hover { background: var(--border); }
    main { max-width: 780px; margin: 0 auto; padding: 32px 20px 80px; }
    .hero { text-align: center; padding: 36px 0 32px; }
    .hero-badge {
      display: inline-flex; align-items: center; gap: 6px;
      font-size: 12px; color: var(--primary); font-weight: 600;
      background: var(--primary-light); border: 1px solid rgba(37,99,235,0.3);
      border-radius: 20px; padding: 4px 12px; margin-bottom: 18px;
    }
    .hero-badge-dot { width: 6px; height: 6px; background: var(--primary); border-radius: 50%; }
    .hero h2 {
      font-size: clamp(22px, 4vw, 32px); font-weight: 800; color: var(--text);
      letter-spacing: -0.8px; line-height: 1.3; margin-bottom: 12px;
    }
    .hero h2 em { font-style: normal; color: var(--primary); }
    .hero p { font-size: 14px; color: var(--text2); line-height: 1.8; }
    .search-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 14px; padding: 22px 24px;
      box-shadow: var(--shadow); margin-bottom: 14px;
    }
    .search-label {
      font-size: 12px; font-weight: 700; color: var(--text2);
      margin-bottom: 10px; display: flex; align-items: center; gap: 7px;
    }
    .search-label-bar { width: 3px; height: 13px; background: var(--primary); border-radius: 2px; }
    .search-row { display: flex; gap: 8px; }
    .input-wrap { flex: 1; position: relative; }
    .input-wrap::before {
      content: '🔍'; position: absolute; left: 12px; top: 50%;
      transform: translateY(-50%); font-size: 14px; pointer-events: none;
    }
    input[type="text"] {
      width: 100%; padding: 11px 14px 11px 38px;
      border: 1.5px solid var(--border); border-radius: var(--radius);
      background: var(--surface2); color: var(--text);
      font-family: var(--font); font-size: 14px; transition: 0.15s; outline: none;
    }
    input:focus { border-color: var(--primary); background: var(--surface); box-shadow: 0 0 0 3px rgba(37,99,235,0.1); }
    input::placeholder { color: var(--text3); }
    .btn-primary {
      padding: 11px 22px; background: var(--primary); color: white;
      border: none; border-radius: var(--radius); font-family: var(--font);
      font-size: 14px; font-weight: 700; cursor: pointer; transition: 0.15s;
      white-space: nowrap; display: flex; align-items: center; gap: 6px;
    }
    .btn-primary:hover:not(:disabled) { background: var(--primary-hover); transform: translateY(-1px); box-shadow: 0 4px 12px rgba(37,99,235,0.3); }
    .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
    .history-row {
      display: none; align-items: center; gap: 6px; flex-wrap: wrap;
      margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--border);
    }
    .history-row.show { display: flex; }
    .history-label { font-size: 11px; color: var(--text3); font-weight: 600; white-space: nowrap; }
    .history-chip {
      font-size: 12px; padding: 4px 11px; border: 1px solid var(--border2);
      border-radius: 20px; cursor: pointer; color: var(--text2);
      background: var(--surface2); font-family: var(--font); transition: 0.15s;
    }
    .history-chip:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-light); }
    .error-card {
      background: var(--danger-light); border: 1px solid var(--danger);
      border-radius: 12px; padding: 14px 18px; margin-bottom: 14px;
      display: none; align-items: center; gap: 10px;
      font-size: 13px; color: var(--danger);
    }
    .error-card.show { display: flex; }
    .error-text { flex: 1; font-weight: 500; }
    .btn-retry {
      padding: 6px 14px; background: var(--danger); color: white; border: none;
      border-radius: 7px; font-family: var(--font); font-size: 12px;
      font-weight: 700; cursor: pointer; white-space: nowrap;
    }
    .progress-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 18px 22px;
      box-shadow: var(--shadow-sm); margin-bottom: 14px; display: none;
    }
    .progress-card.show { display: block; }
    .progress-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 11px; }
    .progress-status { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text2); font-weight: 500; }
    .spinner {
      width: 14px; height: 14px; border: 2px solid var(--border);
      border-top-color: var(--primary); border-radius: 50%;
      animation: spin 0.7s linear infinite; flex-shrink: 0;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .progress-pct { font-size: 13px; font-weight: 700; color: var(--primary); }
    .progress-track { height: 5px; background: var(--surface2); border-radius: 3px; overflow: hidden; border: 1px solid var(--border); }
    .progress-bar {
      height: 100%; width: 0%; border-radius: 3px;
      background: linear-gradient(90deg, var(--primary), #60a5fa);
      transition: width 0.4s cubic-bezier(0.4,0,0.2,1);
    }
    .skeleton-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 14px; padding: 26px; margin-bottom: 14px; display: none;
    }
    .skeleton-card.show { display: block; }
    .skel {
      height: 13px; border-radius: 6px;
      background: linear-gradient(90deg, var(--border) 25%, var(--surface2) 50%, var(--border) 75%);
      background-size: 300% 100%; animation: shimmer 1.6s infinite; margin-bottom: 10px;
    }
    .skel-h { height: 18px; margin-bottom: 16px; }
    @keyframes shimmer { 0%{background-position:200%} 100%{background-position:-200%} }
    .result-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 14px; overflow: hidden; box-shadow: var(--shadow-lg);
      display: none; animation: slideUp 0.4s cubic-bezier(0.16,1,0.3,1);
    }
    .result-card.show { display: block; }
    @keyframes slideUp { from{opacity:0;transform:translateY(14px)} to{opacity:1;transform:none} }
    .result-header {
      padding: 14px 22px; border-bottom: 1px solid var(--border);
      background: var(--surface2); display: flex;
      align-items: center; justify-content: space-between; gap: 12px;
    }
    .result-meta { display: flex; align-items: center; gap: 9px; min-width: 0; }
    .result-dot {
      width: 8px; height: 8px; background: var(--success); border-radius: 50%;
      flex-shrink: 0; box-shadow: 0 0 0 3px rgba(22,163,74,0.15);
    }
    .result-meta-info { min-width: 0; }
    .result-product { font-weight: 700; font-size: 14px; color: var(--text); display: block; }
    .result-sub { font-size: 11px; color: var(--text3); }
    .result-actions { display: flex; gap: 6px; flex-shrink: 0; }
    .btn-action {
      padding: 6px 13px; border: 1px solid var(--border2); border-radius: 7px;
      background: var(--surface); color: var(--text2); font-family: var(--font);
      font-size: 12px; font-weight: 600; cursor: pointer; transition: 0.15s;
      display: flex; align-items: center; gap: 4px;
    }
    .btn-action:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-light); }
    .result-body { padding: 26px 26px 30px; }
    .result-body h2 {
      font-size: 16px; font-weight: 800; color: var(--text);
      margin: 26px 0 10px; padding: 9px 14px; background: var(--surface2);
      border-left: 3.5px solid var(--primary); border-radius: 0 6px 6px 0;
    }
    .result-body h2:first-child { margin-top: 0; }
    .result-body h3 { font-size: 14px; font-weight: 700; color: var(--text2); margin: 16px 0 7px; }
    .result-body p { font-size: 14px; color: var(--text); margin-bottom: 11px; line-height: 1.85; }
    .result-body ul, .result-body ol { padding-left: 18px; margin-bottom: 11px; }
    .result-body li { font-size: 14px; color: var(--text); margin-bottom: 5px; line-height: 1.75; }
    .result-body strong { color: var(--primary); font-weight: 700; }
    .result-body code {
      font-size: 12px; background: var(--surface2); padding: 2px 6px;
      border-radius: 4px; border: 1px solid var(--border);
      font-family: 'Consolas', 'Courier New', monospace;
    }
    .result-body hr { border: none; border-top: 1px solid var(--border); margin: 18px 0; }
    .toast {
      position: fixed; bottom: 28px; left: 50%;
      transform: translateX(-50%) translateY(10px);
      background: #1f2937; color: #f9fafb; font-family: var(--font);
      font-size: 13px; font-weight: 600; padding: 11px 20px;
      border-radius: 10px; box-shadow: var(--shadow-lg);
      opacity: 0; pointer-events: none; transition: 0.25s; z-index: 999; white-space: nowrap;
    }
    [data-theme="dark"] .toast { background: #e6edf3; color: #0d1117; }
    .toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
    @media (max-width: 500px) {
      .search-row { flex-direction: column; }
      .result-header { flex-direction: column; align-items: flex-start; }
      .result-actions { width: 100%; }
      .btn-action { flex: 1; justify-content: center; }
      .result-body { padding: 18px 16px 22px; }
      main { padding: 20px 14px 60px; }
    }
  </style>
</head>
<body>
<nav>
  <div class="nav-inner">
    <div class="nav-logo">
      <div class="nav-icon">AI</div>
      <span class="nav-title">AI <span>제품 분석기</span></span>
      <span class="nav-badge">Beta</span>
    </div>
    <button class="theme-toggle" id="themeBtn" onclick="toggleTheme()">🌙</button>
  </div>
</nav>
<main>
  <div class="hero">
    <div class="hero-badge"><div class="hero-badge-dot"></div>실시간 리뷰 분석 엔진</div>
    <h2>궁금한 제품,<br><em>AI가 분석해 드립니다</em></h2>
    <p>실제 사용자 리뷰를 수집·분석하여<br>장단점을 한눈에 정리해 드립니다.</p>
  </div>
  <div class="search-card">
    <div class="search-label"><div class="search-label-bar"></div>분석할 제품 입력</div>
    <div class="search-row">
      <div class="input-wrap">
        <input type="text" id="productInput"
          placeholder="예: 갤럭시 S25, 다이슨 에어랩, 맥북 프로 M4…"
          onkeydown="if(event.key==='Enter') runAnalysis()">
      </div>
      <button class="btn-primary" id="analyzeBtn" onclick="runAnalysis()">분석 시작 →</button>
    </div>
    <div class="history-row" id="historyRow"><span class="history-label">최근 검색</span></div>
  </div>
  <div class="error-card" id="errorCard">
    <span>⚠️</span>
    <span class="error-text" id="errorMsg">오류가 발생했습니다.</span>
    <button class="btn-retry" onclick="runAnalysis()">재시도</button>
  </div>
  <div class="progress-card" id="progressCard">
    <div class="progress-top">
      <div class="progress-status"><div class="spinner"></div><span id="statusMsg">분석 준비 중...</span></div>
      <span class="progress-pct" id="pctText">0%</span>
    </div>
    <div class="progress-track"><div class="progress-bar" id="progressBar"></div></div>
  </div>
  <div class="skeleton-card" id="skeletonCard">
    <div class="skel skel-h" style="width:40%"></div>
    <div class="skel" style="width:100%"></div><div class="skel" style="width:86%"></div>
    <div class="skel" style="width:72%"></div><div style="height:14px"></div>
    <div class="skel skel-h" style="width:34%"></div>
    <div class="skel" style="width:93%"></div><div class="skel" style="width:80%"></div>
  </div>
  <div class="result-card" id="resultCard">
    <div class="result-header">
      <div class="result-meta">
        <div class="result-dot"></div>
        <div class="result-meta-info">
          <span class="result-product" id="resultName"></span>
          <span class="result-sub">분석 완료</span>
        </div>
      </div>
      <div class="result-actions">
        <button class="btn-action" onclick="copyResult()">📋 복사</button>
        <button class="btn-action" onclick="downloadResult()">⬇ 저장</button>
      </div>
    </div>
    <div class="result-body" id="resultBody"></div>
  </div>
</main>
<div class="toast" id="toast"></div>
<script>
  let isAnalyzing=false,currentProduct='',currentMarkdown='',retryCount=0;
  const MAX_RETRY=3,HIST_KEY='aiAnalyzerHistory';
  (function(){
    const t=localStorage.getItem('theme')||'light';
    document.documentElement.dataset.theme=t;
    document.getElementById('themeBtn').textContent=t==='dark'?'☀️':'🌙';
  })();
  function toggleTheme(){
    const html=document.documentElement;
    const next=html.dataset.theme==='dark'?'light':'dark';
    html.dataset.theme=next;
    document.getElementById('themeBtn').textContent=next==='dark'?'☀️':'🌙';
    localStorage.setItem('theme',next);
  }
  function toast(msg){
    const el=document.getElementById('toast');
    el.textContent=msg; el.classList.add('show');
    setTimeout(()=>el.classList.remove('show'),2400);
  }
  function getHistory(){try{return JSON.parse(localStorage.getItem(HIST_KEY))||[];}catch{return[];}}
  function addHistory(name){
    let h=getHistory().filter(x=>x!==name);
    h.unshift(name);
    localStorage.setItem(HIST_KEY,JSON.stringify(h.slice(0,5)));
    renderHistory();
  }
  function renderHistory(){
    const h=getHistory(),row=document.getElementById('historyRow');
    if(!h.length){row.classList.remove('show');return;}
    row.classList.add('show');
    while(row.children.length>1)row.removeChild(row.lastChild);
    h.forEach(name=>{
      const c=document.createElement('button');
      c.className='history-chip';c.textContent=name;
      c.onclick=()=>{document.getElementById('productInput').value=name;runAnalysis();};
      row.appendChild(c);
    });
  }
  renderHistory();
  function setProgress(p,msg){
    document.getElementById('progressBar').style.width=p+'%';
    document.getElementById('pctText').textContent=p+'%';
    if(msg)document.getElementById('statusMsg').textContent=msg;
  }
  function showError(msg){document.getElementById('errorMsg').textContent=msg;document.getElementById('errorCard').classList.add('show');}
  function hideError(){document.getElementById('errorCard').classList.remove('show');}
  function resetUI(){
    isAnalyzing=false;
    document.getElementById('analyzeBtn').disabled=false;
    document.getElementById('progressCard').classList.remove('show');
    document.getElementById('skeletonCard').classList.remove('show');
  }
  function runAnalysis(){
    const name=document.getElementById('productInput').value.trim();
    if(!name||isAnalyzing)return;
    hideError();isAnalyzing=true;currentProduct=name;retryCount=0;
    document.getElementById('analyzeBtn').disabled=true;
    document.getElementById('resultCard').classList.remove('show');
    document.getElementById('progressCard').classList.add('show');
    document.getElementById('skeletonCard').classList.add('show');
    setProgress(0,'분석 준비 중...');
    connectSSE(name);
  }
  function connectSSE(name){
    const src=new EventSource('/analyze?product='+encodeURIComponent(name));
    src.onmessage=function(e){
      let data;try{data=JSON.parse(e.data);}catch{return;}
      if(data.p!==undefined)setProgress(data.p,data.m);
      if(data.p===100&&data.answer){
        src.close();currentMarkdown=data.answer;addHistory(name);
        setTimeout(()=>{
          document.getElementById('skeletonCard').classList.remove('show');
          document.getElementById('progressCard').classList.remove('show');
          document.getElementById('resultName').textContent=name;
          document.getElementById('resultBody').innerHTML=marked.parse(data.answer);
          document.getElementById('resultCard').classList.add('show');
          document.getElementById('resultCard').scrollIntoView({behavior:'smooth',block:'start'});
          resetUI();
        },500);
      }
      if(data.error){src.close();handleError(data.m||'분석 중 오류가 발생했습니다.',name);}
    };
    src.onerror=function(){src.close();handleError('서버 연결에 실패했습니다.',name);};
  }
  function handleError(msg,name){
    if(retryCount<MAX_RETRY){
      retryCount++;
      document.getElementById('statusMsg').textContent='재연결 중... ('+retryCount+'/'+MAX_RETRY+')';
      setTimeout(()=>connectSSE(name),2000);
    }else{
      resetUI();document.getElementById('skeletonCard').classList.remove('show');
      showError(msg+' — 재시도 '+MAX_RETRY+'회 실패');
    }
  }
  function copyResult(){
    if(!currentMarkdown)return;
    navigator.clipboard.writeText(currentMarkdown).then(()=>toast('✓ 클립보드에 복사되었습니다')).catch(()=>toast('복사에 실패했습니다'));
  }
  function downloadResult(){
    if(!currentMarkdown)return;
    const a=document.createElement('a');
    a.href=URL.createObjectURL(new Blob([currentMarkdown],{type:'text/markdown'}));
    a.download=currentProduct+'_분석리포트.md';a.click();
    URL.revokeObjectURL(a.href);toast('⬇ 파일 저장을 시작합니다');
  }
</script>
</body>
</html>"""


@asynccontextmanager
async def lifespan(app: FastAPI):
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


# ── 루트: HTML 서빙 (핵심 수정) ──────────────────────────────────────
@app.get("/")
async def root():
    return HTMLResponse(content=HTML_PAGE)


# --- 웹 수집 로직 ---
async def fetch_page(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.get(url)
        if r.status_code != 200:
            logger.warning(f"fetch_page non-200 [{r.status_code}]: {url}")
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        for s in soup(['script', 'style', 'header', 'footer', 'nav', 'form', 'aside']):
            s.decompose()
        text = soup.get_text(" ", strip=True)
        return text[:MAX_CHARS_PER_PAGE]
    except Exception as e:
        logger.error(f"fetch_page error [{url}]: {e}")
        return ""


async def collect_reviews(product_name: str, client: httpx.AsyncClient) -> str:
    urls = []
    try:
        with DDGS() as ddgs:
            results = await asyncio.to_thread(
                list, ddgs.text(f"{product_name} 실사용 후기 단점", max_results=6)
            )
            urls = [r.get("href") for r in results if r and r.get("href")]
    except Exception as e:
        logger.error(f"Search error: {e}")

    if not urls:
        return ""

    tasks = [fetch_page(client, u) for u in urls]
    pages = await asyncio.gather(*tasks, return_exceptions=True)
    valid_pages = [p for p in pages if isinstance(p, str) and p]

    collected = []
    total = 0
    for page in valid_pages:
        if total + len(page) > MAX_TOTAL_CHARS:
            remaining = MAX_TOTAL_CHARS - total
            if remaining > 0:
                collected.append(page[:remaining])
            break
        collected.append(page)
        total += len(page)

    return "\n\n".join(collected)


# --- 프롬프트 빌더 ---
def build_prompt(product_name: str, context: str) -> str:
    return f"""
# 역할
너는 데이터 기반 전문 제품 분석 리서처다. 오직 제공된 리뷰 데이터만 기반으로 분석한다.

# 🔴 절대 규칙
- "{product_name}" 이 제품만 분석하라. (Pro, Max, 이전 세대 언급 금지)
- 데이터에 없는 정보 생성 금지. 불확실하면 "확인되지 않음" 표기.

# 📊 분석 목표
1. 핵심 요약
2. 주요 특징
3. 장점 상세
4. 단점 상세
5. 감정 분석
6. 점수 평가 (성능 / 디자인 / 내구성 / 편의성 / 가성비)
7. 전체 평균
8. 추천 / 비추천 대상
9. 종합 결론

# 데이터
{context}
"""


async def call_ai_logic(client: httpx.AsyncClient, prompt: str):
    # 1. Gemini 우선 시도
    if GEMINI_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
            r = await client.post(
                url,
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=50
            )
            if r.status_code == 200:
                return r.json()['candidates'][0]['content']['parts'][0]['text'], "Gemini"
            else:
                logger.warning(f"Gemini non-200: {r.status_code} / {r.text[:200]}")
        except Exception as e:
            logger.error(f"Gemini error: {e}")

    # 2. Groq 폴백
    if GROQ_KEY:
        try:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}"},
                json={
                    "model": "llama3-70b-8192",
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=50
            )
            if r.status_code == 200:
                return r.json()['choices'][0]['message']['content'], "Groq"
            else:
                logger.warning(f"Groq non-200: {r.status_code} / {r.text[:200]}")
        except Exception as e:
            logger.error(f"Groq error: {e}")

    raise Exception("AI 응답을 가져올 수 없습니다.")


# --- 스트리밍 엔드포인트 ---
async def final_analysis_stream(product_name: str) -> AsyncGenerator[str, None]:
    client = app.state.client
    try:
        yield f"data: {json.dumps({'p': 20, 'm': '🔍 리뷰 데이터를 수집하고 있습니다...'})}\n\n"
        context = await collect_reviews(product_name, client)

        if not context:
            raise Exception("데이터 수집 실패: 유효한 리뷰를 찾을 수 없습니다.")

        yield f"data: {json.dumps({'p': 60, 'm': '🧠 AI가 심층 분석 리포트를 작성 중입니다...'})}\n\n"
        prompt = build_prompt(product_name, context)
        final_answer, model_name = await call_ai_logic(client, prompt)

        yield f"data: {json.dumps({'p': 100, 'm': f'✅ {model_name} 분석 완료', 'answer': final_answer})}\n\n"

    except Exception as e:
        logger.error(f"Stream error: {e}")
        yield f"data: {json.dumps({'p': -1, 'm': f'오류: {str(e)}', 'error': True})}\n\n"


@app.get("/analyze")
async def analyze(product: str):
    return StreamingResponse(
        final_analysis_stream(product),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Render/Nginx 버퍼링 비활성화 (SSE 필수)
        }
    )
