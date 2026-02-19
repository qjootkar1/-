import os
import json
import time
import hashlib
import asyncio
import logging
from collections import defaultdict
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from contextlib import asynccontextmanager

# ── 로깅 ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("analyzer")

# ── API 키 ────────────────────────────────────────────────────
GEMINI_KEY          = os.getenv("GEMINI_API_KEY")
GROQ_KEY            = os.getenv("GROQ_API_KEY")
SERPER_KEY          = os.getenv("SERPER_API_KEY")

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

# ═══════════════════════════════════════════════════════════════
# 설정 & 상수
# ═══════════════════════════════════════════════════════════════
MAX_CHARS_PER_PAGE  = 2500    # 페이지당 최대 수집 글자
MAX_TOTAL_CHARS     = 15000   # 전체 컨텍스트 최대 글자
MAX_FETCH_WORKERS   = 5       # 동시 페이지 수집 수
MAX_PRODUCT_LEN     = 100     # 제품명 최대 길이
RATE_LIMIT_PER_MIN  = 10      # IP당 분당 최대 요청 수
CACHE_TTL_SEC       = 3600    # 캐시 유효시간 (1시간)

# 인메모리 저장소
_rate_store: dict = defaultdict(list)   # {ip: [timestamp, ...]}
_cache: dict      = {}                  # {md5key: (timestamp, result)}


# ═══════════════════════════════════════════════════════════════
# Lifespan — httpx 클라이언트 풀 관리
# ═══════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=40.0, write=10.0, pool=5.0),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        follow_redirects=True,
        limits=httpx.Limits(
            max_keepalive_connections=10,
            max_connections=20,
            keepalive_expiry=30,
        ),
        http2=False,
    )
    logger.info("✅ httpx 클라이언트 초기화")
    yield
    await app.state.client.aclose()
    logger.info("🔒 httpx 클라이언트 종료")


# ═══════════════════════════════════════════════════════════════
# FastAPI 앱
# ═══════════════════════════════════════════════════════════════
app = FastAPI(
    lifespan=lifespan,
    docs_url=None,      # 보안: Swagger 비공개
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════
# 미들웨어: IP 기반 레이트 리밋
# ═══════════════════════════════════════════════════════════════
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path == "/analyze":
        ip = (request.client.host if request.client else "unknown")
        now = time.time()
        window_start = now - 60
        _rate_store[ip] = [t for t in _rate_store[ip] if t > window_start]
        if len(_rate_store[ip]) >= RATE_LIMIT_PER_MIN:
            logger.warning(f"레이트 리밋 초과: {ip}")
            return JSONResponse(
                {"error": True, "m": "요청이 너무 많습니다. 잠시 후 다시 시도하세요.", "p": -1},
                status_code=429,
            )
        _rate_store[ip].append(now)
    return await call_next(request)


# ═══════════════════════════════════════════════════════════════
# 보안: 입력값 검증 & 새니타이즈
# ═══════════════════════════════════════════════════════════════
def sanitize_product_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(400, "제품명을 입력해주세요.")
    if len(name) > MAX_PRODUCT_LEN:
        raise HTTPException(400, f"제품명은 {MAX_PRODUCT_LEN}자 이하로 입력해주세요.")
    # 제어문자·null 바이트 제거
    name = "".join(c for c in name if ord(c) >= 32 and c != "\x00")
    # 스크립트 인젝션 패턴 차단
    for bad in ["<script", "javascript:", "data:", "--", ";"]:
        if bad.lower() in name.lower():
            raise HTTPException(400, "유효하지 않은 제품명입니다.")
    return name[:MAX_PRODUCT_LEN]


# ═══════════════════════════════════════════════════════════════
# 캐시 (메모리, 최대 100개)
# ═══════════════════════════════════════════════════════════════
def _cache_key(name: str) -> str:
    return hashlib.md5(name.strip().lower().encode()).hexdigest()

def get_cache(name: str) -> str | None:
    key = _cache_key(name)
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < CACHE_TTL_SEC:
            logger.info(f"캐시 HIT: {name}")
            return val
        del _cache[key]
    return None

def set_cache(name: str, val: str):
    if len(_cache) >= 100:
        oldest = min(_cache, key=lambda k: _cache[k][0])
        del _cache[oldest]
    _cache[_cache_key(name)] = (time.time(), val)


# ═══════════════════════════════════════════════════════════════
# 웹 페이지 수집
# ═══════════════════════════════════════════════════════════════
async def fetch_page(client: httpx.AsyncClient, url: str) -> str:
    """단일 URL 텍스트 추출. 실패 시 빈 문자열 반환."""
    try:
        r = await client.get(url, timeout=15)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "header", "footer", "nav",
                          "form", "aside", "iframe", "noscript", "svg"]):
            tag.decompose()
        # 연속 공백 정리
        text = " ".join(soup.get_text(" ", strip=True).split())
        return text[:MAX_CHARS_PER_PAGE]
    except Exception as e:
        logger.debug(f"fetch_page 실패 [{url[:60]}]: {e}")
        return ""


# ═══════════════════════════════════════════════════════════════
# Serper API — Google 검색
# ═══════════════════════════════════════════════════════════════
async def search_serper(query: str, client: httpx.AsyncClient) -> list[str]:
    """Serper.dev API로 Google 검색 결과 URL 반환."""
    if not SERPER_KEY:
        logger.warning("SERPER_API_KEY 미설정")
        return []
    try:
        r = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"},
            json={"q": query, "gl": "kr", "hl": "ko", "num": 8},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        urls = [item["link"] for item in data.get("organic", []) if item.get("link")]
        logger.info(f"Serper OK: {len(urls)}개 URL")
        return urls
    except httpx.HTTPStatusError as e:
        logger.error(f"Serper HTTP 오류 {e.response.status_code}: {e.response.text[:200]}")
    except Exception as e:
        logger.error(f"Serper 오류: {e}")
    return []


# ═══════════════════════════════════════════════════════════════
# DuckDuckGo 검색 — 올바른 async 패턴
# ═══════════════════════════════════════════════════════════════

def _ddgs_sync(query: str, max_results: int = 6) -> list[str]:
    """
    DDGS를 완전히 동기·스레드 내에서 실행.

    핵심 원칙:
      1) DDGS 인스턴스를 스레드 안에서 생성 — 이벤트 루프 스레드와 분리
      2) 컨텍스트 매니저(with) 미사용 — 교차 스레드 __exit__ 문제 방지
      3) backend 파라미터 없음 — v6에서 완전 제거됨, 넣으면 TypeError
      4) text() 결과를 list()로 강제 소비 — 제너레이터 지연 평가 방지
    """
    ddgs = DDGS(timeout=20)
    results = list(ddgs.text(query, max_results=max_results))
    return [r.get("href", "") for r in results if r.get("href")]


async def search_ddgs(query_ko: str, query_en: str) -> list[str]:
    """
    DuckDuckGo 검색.
    - 한국어 쿼리 먼저, 실패 시 영어 쿼리 폴백
    - 레이트리밋 감지 시 추가 대기 후 재시도
    - 예외는 내부에서 처리, 항상 list 반환
    """
    queries = [
        (query_ko, "KO"),
        (query_en, "EN"),
    ]

    for idx, (query, label) in enumerate(queries):
        if idx > 0:
            # 쿼리 전환 전 대기 (레이트리밋 방지)
            await asyncio.sleep(1.5)
        try:
            urls = await asyncio.to_thread(_ddgs_sync, query, 6)
            if urls:
                logger.info(f"DDGS({label}) OK: {len(urls)}개 URL")
                return urls
            logger.warning(f"DDGS({label}) 결과 없음: {query[:60]}")
        except Exception as e:
            err_lower = str(e).lower()
            # 레이트리밋 / 202 응답 감지 (버전별로 표현 다름)
            is_ratelimit = any(k in err_lower for k in
                               ("ratelimit", "rate limit", "202", "blocked", "forbidden"))
            if is_ratelimit:
                logger.warning(f"DDGS({label}) 레이트리밋: {e} — 3초 대기 후 재시도")
                await asyncio.sleep(3)
                # 레이트리밋이면 같은 쿼리 한 번 더 시도
                try:
                    urls = await asyncio.to_thread(_ddgs_sync, query, 4)
                    if urls:
                        logger.info(f"DDGS({label}) 재시도 성공: {len(urls)}개 URL")
                        return urls
                except Exception as e2:
                    logger.warning(f"DDGS({label}) 재시도 실패: {e2}")
            else:
                logger.warning(f"DDGS({label}) 오류: {type(e).__name__}: {e}")

    logger.warning("DDGS 모든 시도 실패")
    return []


# ═══════════════════════════════════════════════════════════════
# 통합 리뷰 수집 (Serper + DDGS)
# ═══════════════════════════════════════════════════════════════
async def collect_reviews(product_name: str, client: httpx.AsyncClient) -> str:
    query_ko = f"{product_name} 실사용 후기 장단점"
    query_en = f"{product_name} review pros cons"

    # Serper와 DDGS 병렬 실행
    # DDGS는 한국어·영어 쿼리를 내부에서 순차 처리
    serper_task = search_serper(query_ko, client)
    ddgs_task   = search_ddgs(query_ko, query_en)

    results = await asyncio.gather(
        serper_task, ddgs_task,
        return_exceptions=True,
    )
    serper_urls: list[str] = results[0] if isinstance(results[0], list) else []
    ddgs_urls:   list[str] = results[1] if isinstance(results[1], list) else []

    if isinstance(results[0], Exception):
        logger.error(f"Serper 예외: {results[0]}")
    if isinstance(results[1], Exception):
        logger.error(f"DDGS 예외: {results[1]}")

    # URL 중복 제거 — Serper 결과 우선
    seen: set[str] = set()
    urls: list[str] = []
    for u in serper_urls + ddgs_urls:
        if u and u not in seen:
            seen.add(u)
            urls.append(u)

    logger.info(
        f"검색 결과 — Serper: {len(serper_urls)}, DDGS: {len(ddgs_urls)}, "
        f"합산 URL: {len(urls)}"
    )

    if not urls:
        logger.warning("모든 검색 실패 — AI 자체 지식으로 분석")
        return ""

    # 세마포어로 동시 페이지 요청 수 제한
    sem = asyncio.Semaphore(MAX_FETCH_WORKERS)

    async def _fetch(url: str) -> str:
        async with sem:
            return await fetch_page(client, url)

    pages = await asyncio.gather(
        *[_fetch(u) for u in urls[:8]],
        return_exceptions=True,
    )
    page_texts = [p for p in pages if isinstance(p, str) and p.strip()]

    if not page_texts:
        logger.warning("페이지 수집 모두 실패 — AI 자체 지식으로 분석")
        return ""

    # 전체 최대 글자수 제한
    collected, total = [], 0
    for part in page_texts:
        remaining = MAX_TOTAL_CHARS - total
        if remaining <= 0:
            break
        collected.append(part[:remaining])
        total += len(part[:remaining])

    logger.info(f"최종 수집: {total:,}자 ({len(page_texts)}개 페이지)")
    return "\n\n".join(collected)


# ═══════════════════════════════════════════════════════════════
# 프롬프트 빌더
# ═══════════════════════════════════════════════════════════════
def build_prompt(product_name: str, context: str) -> str:
    if context.strip():
        data_section = (
            "아래는 실제 수집된 리뷰/후기/커뮤니티 데이터입니다. "
            "이를 최우선으로 활용하고, 데이터에 없는 내용은 '확인되지 않음'으로 표기하라.\n\n"
            + context
        )
    else:
        data_section = (
            "⚠️ 실시간 리뷰 수집에 실패했습니다. "
            "AI 학습 지식을 바탕으로 분석하되, 각 항목에 반드시 [AI 추정] 태그를 붙여라."
        )

    return f"""당신은 전문 제품 분석 리서처입니다. 한국어로 상세하고 구조적인 분석 리포트를 작성하세요.

## 분석 대상
- 제품명: {product_name}
- 규칙: 이 제품만 분석. 다른 세대·모델 혼용 금지.

## 출력 형식 (마크다운)

## 1. 핵심 요약
(2~3줄 요약)

## 2. 주요 특징
(핵심 스펙·특징 불릿)

## 3. 장점
(구체적 근거와 함께 서술)

## 4. 단점
(구체적 근거와 함께 서술)

## 5. 사용자 반응 분석
(긍정/부정 비율, 주요 키워드)

## 6. 점수 평가
| 항목 | 점수 |
|------|------|
| 성능 | X/10 |
| 디자인 | X/10 |
| 내구성 | X/10 |
| 편의성 | X/10 |
| 가성비 | X/10 |
| **종합** | **X/10** |

## 7. 추천 대상 / 비추천 대상

## 8. 종합 결론

---

## 데이터 출처
{data_section}"""


# ═══════════════════════════════════════════════════════════════
# AI 호출 (Gemini → Groq 폴백)
# ═══════════════════════════════════════════════════════════════
async def call_ai(client: httpx.AsyncClient, prompt: str) -> tuple[str, str]:
    # 1순위: Gemini 1.5 Flash
    if GEMINI_KEY:
        try:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-1.5-flash:generateContent?key={GEMINI_KEY}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 4096,
                    },
                },
                timeout=60,
            )
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            logger.info("✅ Gemini 응답 성공")
            return text, "Gemini"
        except httpx.HTTPStatusError as e:
            logger.warning(f"Gemini HTTP 오류 {e.response.status_code}: {e.response.text[:300]}")
        except (KeyError, IndexError) as e:
            logger.error(f"Gemini 응답 파싱 오류: {e}")
        except Exception as e:
            logger.error(f"Gemini 오류: {e}")

    # 2순위: Groq Llama3-70B
    if GROQ_KEY:
        try:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}"},
                json={
                    "model": "llama3-70b-8192",
                    "messages": [
                        {
                            "role": "system",
                            "content": "당신은 전문 제품 분석 리서처입니다. 반드시 한국어로 답변하세요.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 4000,
                },
                timeout=60,
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            logger.info("✅ Groq 응답 성공")
            return text, "Groq"
        except httpx.HTTPStatusError as e:
            logger.warning(f"Groq HTTP 오류 {e.response.status_code}: {e.response.text[:300]}")
        except (KeyError, IndexError) as e:
            logger.error(f"Groq 응답 파싱 오류: {e}")
        except Exception as e:
            logger.error(f"Groq 오류: {e}")

    raise RuntimeError("사용 가능한 AI API가 없거나 모든 호출에 실패했습니다.")


# ═══════════════════════════════════════════════════════════════
# SSE 스트리밍 제너레이터
# ═══════════════════════════════════════════════════════════════
async def analysis_stream(product_name: str) -> AsyncGenerator[str, None]:
    def emit(p: int, m: str, **extra) -> str:
        payload = {"p": p, "m": m, **extra}
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    client: httpx.AsyncClient = app.state.client

    try:
        # 캐시 확인
        cached = get_cache(product_name)
        if cached:
            yield emit(30, "⚡ 이전 분석 결과를 불러오는 중...")
            await asyncio.sleep(0.4)
            yield emit(100, "✅ 캐시 결과 로드 완료", answer=cached)
            return

        # 리뷰 수집
        yield emit(10, "🔍 리뷰 데이터를 수집하고 있습니다...")
        context = await collect_reviews(product_name, client)

        if context:
            yield emit(55, f"📄 수집 완료 ({len(context):,}자) — AI 분석 중...")
        else:
            yield emit(55, "⚠️ 실시간 수집 실패 — AI 학습 지식으로 분석합니다...")

        # AI 분석
        prompt = build_prompt(product_name, context)
        answer, model = await call_ai(client, prompt)

        # 캐시 저장 (리뷰 기반 결과만)
        if context:
            set_cache(product_name, answer)

        source = "리뷰 기반" if context else "AI 추정"
        yield emit(100, f"✅ {model} 분석 완료 [{source}]", answer=answer)

    except RuntimeError as e:
        logger.error(f"AI 호출 실패: {e}")
        yield emit(-1, str(e), error=True)
    except Exception as e:
        logger.error(f"Stream 예외: {e}", exc_info=True)
        yield emit(-1, "서버 내부 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.", error=True)


# ═══════════════════════════════════════════════════════════════
# 라우트
# ═══════════════════════════════════════════════════════════════
@app.get("/")
async def root():
    return HTMLResponse(content=HTML_PAGE)


@app.get("/analyze")
async def analyze(request: Request, product: str = ""):
    clean = sanitize_product_name(product)
    return StreamingResponse(
        analysis_stream(clean),
        media_type="text/event-stream",
        headers={
            "Cache-Control":        "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering":    "no",           # Nginx 버퍼링 비활성 (SSE 필수)
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options":       "DENY",
        },
    )


@app.get("/health")
async def health():
    """헬스체크 — 배포 상태 확인용"""
    return {
        "status":     "ok",
        "gemini":     bool(GEMINI_KEY),
        "groq":       bool(GROQ_KEY),
        "serper":     bool(SERPER_KEY),
        "cache_size": len(_cache),
    }
