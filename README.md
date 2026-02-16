# 🔍 AI 제품 분석기 (AI Product Analyzer)

> 광고성 리뷰를 걸러내고 진짜 사용자 후기만을 분석하여 객관적인 제품 평가를 제공하는 AI 기반 제품 분석 서비스

## 📌 프로젝트 개요

AI 제품 분석기는 온라인 쇼핑몰의 제품 리뷰 속에서 광고성 콘텐츠를 자동으로 필터링하고, 실제 사용자들의 진솔한 후기만을 추출하여 분석합니다. 
AI를 활용해 제품의 장단점을 객관적으로 정리하고 신뢰할 수 있는 평점을 제공합니다.

## ✨ 주요 기능

### 🎯 핵심 기능
- **자동 리뷰 수집**: Super API를 통한 제품 리뷰 및 사용 후기 데이터 자동 수집
- **광고 필터링**: Gemini API 기반 AI가 광고성 리뷰와 실사용 후기를 자동으로 구분
- **스마트 분석**: 실제 사용자 경험만을 기반으로 제품 특징 추출
- **장단점 정리**: AI가 분석한 객관적인 제품의 장점과 단점 요약
- **신뢰도 평점**: 실사용 후기 기반의 공정한 제품 평점 산출

## 🏗️ 시스템 아키텍처

```
┌─────────────────┐
│  제품 검색 입력  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Super API     │ ← 제품 리뷰 데이터 수집
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Gemini API    │ ← AI 기반 데이터 필터링 및 분석
│                 │   • 광고성 리뷰 제거
│                 │   • 실사용 후기 추출
│                 │   • 특징 및 장단점 분석
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  분석 결과 출력  │ ← 제품 특징, 장단점, 평점
└─────────────────┘
```

## 🛠️ 기술 스택

### APIs
- **Super API**: 제품 리뷰 및 후기 데이터 수집
- **Gemini API**: AI 기반 텍스트 분석 및 필터링

### 개발 환경
- **언어**: [Python/JavaScript/기타]
- **프레임워크**: [사용하는 프레임워크]
- **데이터베이스**: [사용하는 DB]

## 📥 설치 방법

```bash
# 저장소 클론
git clone https://github.com/[your-username]/ai-product-analyzer.git

# 디렉토리 이동
cd ai-product-analyzer

# 의존성 패키지 설치
npm install  # 또는 pip install -r requirements.txt

# 환경 변수 설정
cp .env.example .env
# .env 파일에 API 키 입력
```

## 🔑 환경 변수 설정

`.env` 파일에 다음 API 키를 설정하세요:

```env
SUPER_API_KEY=your_super_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
```

## 🚀 사용 방법

```bash
# 서비스 실행
npm start  # 또는 python main.py

# 제품 분석 예시
node analyze.js "제품명"
```

### 사용 예시

```javascript
// 제품 분석 요청
const result = await analyzeProduct("삼성 갤럭시 버즈");

// 결과 출력
console.log(result);
/*
{
  productName: "삼성 갤럭시 버즈",
  totalReviews: 1250,
  filteredReviews: 890,  // 광고 제외된 실사용 후기 수
  rating: 4.3,
  pros: [
    "음질이 깔끔하고 선명함",
    "착용감이 편안하고 귀에서 잘 빠지지 않음",
    "배터리 수명이 우수함"
  ],
  cons: [
    "노이즈 캔슬링 성능이 다소 아쉬움",
    "바람 소리에 민감함",
    "iOS 기기와의 연동 제한"
  ],
  summary: "전반적으로 만족도가 높은 제품이지만..."
}
*/
```

## 🔄 작동 원리

1. **데이터 수집 단계**
   - Super API를 통해 제품의 리뷰, 평점, 사용 후기 데이터 수집
   - 다양한 쇼핑몰 및 리뷰 플랫폼의 정보 통합

2. **필터링 단계**
   - Gemini API의 자연어 처리 기능으로 각 리뷰 분석
   - 광고성 표현, 과장된 찬사, 반복 패턴 등을 감지
   - 실제 사용 경험이 담긴 리뷰만 선별

3. **분석 단계**
   - 필터링된 리뷰에서 제품 특징 추출
   - 긍정적 의견과 부정적 의견 분류
   - 빈도 분석을 통한 주요 장단점 도출

4. **평가 단계**
   - 실사용 후기의 감성 분석
   - 가중치를 적용한 평점 계산
   - 종합 평가 리포트 생성

## 📊 분석 결과 예시

### 제품: 에어팟 프로 2세대

**수집된 리뷰**: 3,420개  
**실사용 후기**: 2,150개 (광고성 리뷰 1,270개 제외)  
**종합 평점**: 4.5/5.0

**장점**
- ✅ 뛰어난 노이즈 캔슬링 성능 (언급 빈도: 78%)
- ✅ 편안한 착용감 (언급 빈도: 65%)
- ✅ Apple 기기와의 완벽한 연동 (언급 빈도: 71%)

**단점**
- ⚠️ 높은 가격 (언급 빈도: 45%)
- ⚠️ 안드로이드와의 제한적 기능 (언급 빈도: 32%)
- ⚠️ 배터리 수명 아쉬움 (언급 빈도: 28%)

## 🤝 기여하기

프로젝트에 기여하고 싶으신가요? Pull Request를 환영합니다!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📝 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다. 자세한 내용은 `LICENSE` 파일을 참조하세요.

## 🙏 감사의 말

- Super API 제공
- Gemini API 제공
- 모든 기여자분들께 감사드립니다

---

⭐ 이 프로젝트가 유용하다면 Star를 눌러주세요!
