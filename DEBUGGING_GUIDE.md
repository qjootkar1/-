# 🔧 Gemini API 에러 해결 가이드

## 현재 에러 상황
```
404 models/gemini-1.5-flash-latest is not found for API version v1beta
```

## ✅ 해결 방법

### 1️⃣ **Render 환경 변수 확인**

Render 대시보드에서 다음을 확인하세요:

1. **Environment** 탭으로 이동
2. 다음 환경 변수가 **정확히** 설정되어 있는지 확인:
   ```
   GEMINI_API_KEY=your_actual_api_key_here
   SERPER_API_KEY=your_serper_api_key_here
   ```

⚠️ **주의사항:**
- API 키 앞뒤에 공백이 없어야 합니다
- 따옴표(" " 또는 ' ')로 감싸지 마세요
- 실제 API 키 값을 정확히 입력하세요

### 2️⃣ **Gemini API 키 유효성 확인**

Google AI Studio에서 API 키를 재확인하세요:

1. [Google AI Studio](https://makersuite.google.com/app/apikey) 접속
2. API 키 생성 또는 기존 키 확인
3. 키가 활성화되어 있는지 확인
4. 할당량(Quota)이 남아 있는지 확인

### 3️⃣ **업데이트된 파일 배포**

1. 수정된 `main.py` 파일로 교체
2. `requirements.txt` 파일도 함께 업데이트
3. Render에서 **Manual Deploy** 버튼 클릭
4. 배포 로그를 주의깊게 확인

### 4️⃣ **로그 확인 방법**

배포 후 Render 로그에서 다음 메시지를 확인하세요:

**✅ 성공 시:**
```
=== 사용 가능한 Gemini 모델 목록 ===
모델명: models/gemini-1.5-flash-001, 지원 메소드: ['generateContent']
✅ 선택된 모델: models/gemini-1.5-flash-001
```

**❌ 실패 시:**
```
❌ GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.
또는
❌ 모든 모델 초기화 실패. API 키를 확인하세요.
```

### 5️⃣ **코드 변경 사항**

새 `main.py`는 다음과 같이 작동합니다:

1. **1단계**: 사용 가능한 모델 리스트를 API에서 직접 조회
2. **2단계**: `generateContent`를 지원하는 모델 중 flash 모델 우선 선택
3. **3단계**: 실패 시 알려진 모델명으로 재시도 (fallback)

이렇게 하면 API 버전이 변경되어도 자동으로 사용 가능한 모델을 찾습니다.

## 🐛 문제가 계속되면?

### 체크리스트:

- [ ] GEMINI_API_KEY가 Render Environment에 정확히 설정됨
- [ ] API 키가 Google AI Studio에서 활성화됨
- [ ] `requirements.txt`에 `google-generativeai==0.8.3` 포함
- [ ] 새 `main.py` 파일로 교체 완료
- [ ] Render에서 수동 재배포 완료
- [ ] 배포 로그에서 "✅ 선택된 모델" 메시지 확인

### 추가 확인 사항:

1. **API 할당량 확인**
   - Google AI Studio에서 무료 할당량을 초과했는지 확인
   - 필요시 결제 정보 등록

2. **라이브러리 버전**
   ```bash
   # 로컬에서 테스트
   pip install --upgrade google-generativeai
   python -c "import google.generativeai as genai; print(genai.__version__)"
   ```

3. **직접 테스트**
   ```python
   import google.generativeai as genai
   genai.configure(api_key="YOUR_API_KEY")
   for m in genai.list_models():
       print(m.name, m.supported_generation_methods)
   ```

## 📞 여전히 안 되면?

Render 로그 전체를 복사해서 다시 공유해주세요. 특히:
- 앱 시작 시 출력되는 모델 목록
- 에러 메시지 전체 스택

이 정보로 더 정확한 진단이 가능합니다!
