# 🔍 AI 제품 분석기

실제 사용자 리뷰를 수집·분석하여 제품의 장단점을 한눈에 정리해주는 AI 기반 웹 애플리케이션입니다.

---

## 📌 주요 기능

- **리뷰 기반 AI 분석** — 실제 사용자 리뷰 데이터를 수집하고 AI가 요약·분석
- **실시간 진행 상태 표시** — SSE(Server-Sent Events)를 통한 실시간 진행률 업데이트
- **분석 히스토리** — 최근 검색한 제품 5개를 로컬에 저장, 원클릭 재검색
- **결과 복사 / 다운로드** — 분석 결과를 클립보드에 복사하거나 `.md` 파일로 저장
- **다크 모드** — 라이트/다크 테마 전환 및 설정 저장
- **자동 재시도** — 서버 연결 실패 시 최대 3회 자동 재연결
- **반응형 레이아웃** — 모바일, 태블릿, 데스크톱 모두 지원

---

## 🛠 기술 스택

| 구분 | 기술 |
|------|------|
| Frontend | HTML5, CSS3, Vanilla JS |
| 마크다운 렌더링 | [marked.js](https://github.com/markedjs/marked) |
| 실시간 통신 | SSE (Server-Sent Events) |
| 폰트 | 맑은 고딕 / Apple SD Gothic Neo (시스템 폰트) |
| 상태 저장 | localStorage |

> 백엔드는 별도로 구성이 필요합니다. 아래 [백엔드 연동](#-백엔드-연동) 항목을 참고하세요.

---

## 🚀 시작하기

### 1. 파일 다운로드

```bash
git clone https://github.com/qjootkar1/-/main.git
cd ai-product-analyzer
```

### 2. 프론트엔드 실행

별도의 빌드 과정 없이 `ai-report.html` 파일을 웹 서버에 올리거나, 로컬에서 바로 열 수 있습니다.

```bash
# Python을 이용한 간단한 로컬 서버 예시
python -m http.server 8080
```

브라우저에서 `http://localhost:8080/ai-report.html` 에 접속합니다.

---

## 📡 백엔드 연동

프론트엔드는 아래 엔드포인트로 SSE 요청을 보냅니다.

```
GET /analyze?product={제품명}
```

### 응답 형식 (SSE)

서버는 `text/event-stream` 형식으로 아래 JSON 데이터를 스트리밍해야 합니다.

```json
// 진행 중
data: {"p": 30, "m": "리뷰 수집 중..."}

// 완료
data: {"p": 100, "m": "분석 완료!", "answer": "## 분석 결과\n..."}

// 오류
data: {"error": true, "m": "분석 중 오류가 발생했습니다."}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `p` | number | 진행률 (0 ~ 100) |
| `m` | string | 상태 메시지 |
| `answer` | string | 완료 시 마크다운 형식의 분석 결과 |
| `error` | boolean | 오류 발생 여부 |

### 백엔드 예시 (Node.js / Express)

```js
app.get('/analyze', async (req, res) => {
  const product = req.query.product;

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');

  const send = (data) => res.write(`data: ${JSON.stringify(data)}\n\n`);

  send({ p: 10, m: '리뷰 수집 중...' });
  // ... AI 분석 로직 ...
  send({ p: 100, m: '완료!', answer: '## 분석 결과\n...' });

  res.end();
});
```

---

## 📁 프로젝트 구조

```
ai-product-analyzer/
├── ai-report.html      # 프론트엔드 단일 파일
└── README.md           # 프로젝트 문서
```

---

## 🖥 화면 구성

| 영역 | 설명 |
|------|------|
| 네비게이션 바 | 로고, 타이틀, 다크모드 토글 |
| 히어로 섹션 | 서비스 소개 문구 |
| 검색 카드 | 제품명 입력, 분석 시작 버튼, 최근 검색 히스토리 |
| 진행 카드 | 실시간 진행률 바 및 상태 메시지 |
| 스켈레톤 UI | 결과 로딩 중 표시되는 플레이스홀더 |
| 결과 카드 | 마크다운 렌더링 결과, 복사/저장 버튼 |

---

## ⚙️ 주요 설정값

`ai-report.html` 내 스크립트 상단에서 아래 값을 조정할 수 있습니다.

```js
const MAX_RETRY = 3;       // 연결 실패 시 최대 재시도 횟수
const HIST_KEY = 'aiAnalyzerHistory';  // localStorage 키 이름
// 히스토리 최대 저장 개수는 addHistory() 함수 내 .slice(0, 5) 로 조정
```

---

## 📝 라이선스

MIT License. 자유롭게 사용, 수정, 배포 가능합니다.
