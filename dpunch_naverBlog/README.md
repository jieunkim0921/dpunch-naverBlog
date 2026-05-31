# 네이버 블로그 검색 노출/순위 모니터링 사이트

내 네이버 블로그 글들이 네이버 검색에 잘 나오는지 **매주 자동 점검**하고,
결과를 **웹 대시보드 사이트**로 보여줍니다. 누락된 글은 따로 목록으로 표시되고,
원하면 이메일/슬랙으로 알림도 받습니다.

대상 블로그: `https://blog.naver.com/giant7000` (변경 가능)

---

## 무엇을 점검하나요 (글마다)

1. **포스팅 전체 제목**으로 검색 → 내 글이 **몇 위**에 나오는지 (안 나오면 '미노출')
2. 제목에서 뽑은 **중요 키워드**로 검색 → **몇 위**에 나오는지
3. 제목 검색에서 안 나온 글은 대시보드 상단 **'누락 목록'** 에 따로 모아 표시

> **순위에 대한 중요한 안내**
> 표시되는 순위는 네이버가 공식 제공하는 **블로그 검색 API(정확도순)** 결과 기준의 **근사 순위**입니다.
> 실제 naver.com 통합검색 화면에서 보이는 순위와는 다를 수 있습니다.
> (화면 순위를 그대로 얻으려면 검색 페이지를 크롤링해야 하는데, 약관 위반·차단 문제로 권장하지 않습니다.)
> 새 글 색인 여부와 대략적인 노출 추적 용도로는 충분히 유용합니다.

---

## 전체 구조 (무료, 서버 불필요)

```
GitHub Actions (주 1회 실행) → check.py 가 순위 점검
        → 결과를 docs/results.json 에 저장 + 커밋
        → GitHub Pages 가 docs/ 폴더를 사이트로 표시
```

저장소에 넣을 파일 구조:

```
내-저장소/
├─ check.py                      ← 점검 프로그램
├─ keywords.json                 ← (선택) 중요키워드 직접 지정
├─ .github/
│  └─ workflows/
│     └─ weekly-check.yml        ← 주간 자동 실행 설정
└─ docs/
   ├─ index.html                 ← 대시보드 사이트
   └─ results.json               ← 점검 결과 (자동 갱신됨)
```

---

## 설치 순서

### 1단계. 네이버 검색 API 키 발급 (무료)
1. https://developers.naver.com 접속 → 네이버 로그인
2. **Application > 애플리케이션 등록**
3. 이름 자유 입력, **사용 API = 검색** 선택
4. **비로그인 오픈 API 환경 = WEB**, 주소는 블로그 주소나 `http://localhost`
5. 등록 후 나오는 **Client ID / Client Secret** 복사 (검색 API는 하루 25,000회 무료)

### 2단계. GitHub 저장소에 파일 올리기
1. GitHub에서 새 저장소 생성 (Public 이어야 GitHub Pages 무료, 또는 Private+Pro)
2. 위 구조대로 파일 업로드. (`weekly-check.yml` 은 반드시 `.github/workflows/` 안에, `index.html`·`results.json` 은 `docs/` 안에)

### 3단계. Secrets 등록
저장소 **Settings > Secrets and variables > Actions > New repository secret** 에서 등록:

| 이름 | 값 |
|------|-----|
| `NAVER_BLOG_ID` | `giant7000` (내 블로그 ID) |
| `NAVER_CLIENT_ID` | 1단계 Client ID |
| `NAVER_CLIENT_SECRET` | 1단계 Client Secret |

### 4단계. Actions 쓰기 권한 켜기 (결과 자동 저장에 필요)
**Settings > Actions > General > Workflow permissions** 에서
**"Read and write permissions"** 선택 후 저장.

### 5단계. GitHub Pages 켜기
**Settings > Pages > Build and deployment**
- Source: **Deploy from a branch**
- Branch: **main** / 폴더: **/docs** → Save
- 잠시 후 사이트 주소가 생깁니다: `https://<내아이디>.github.io/<저장소이름>/`

### 6단계. 첫 실행
저장소 **Actions** 탭 > 워크플로우 선택 > **Run workflow** 버튼으로 수동 실행.
끝나면 5단계 Pages 주소로 들어가 결과를 확인하세요.
이후 **매주 월요일 오전 9시(한국시간)** 에 자동으로 점검·갱신됩니다.

---

## 알림도 받고 싶다면 (선택)

Secrets에 아래를 추가하면 누락 글이 있을 때 메일/메신저로도 알려줍니다.

**이메일 (Gmail 예시)** — `NOTIFY_METHOD` = `email`
| 이름 | 값 |
|------|-----|
| `SMTP_USER` | 보내는 Gmail 주소 |
| `SMTP_PASS` | Gmail **앱 비밀번호**(2단계 인증 후 발급, 일반 비번 아님) |
| `MAIL_TO` | 받을 주소 (콤마로 여러 명) |

**슬랙/디스코드** — `NOTIFY_METHOD` = `webhook`, `WEBHOOK_URL` = Incoming Webhook 주소

---

## 자주 만지는 설정

- **점검 주기 변경:** `weekly-check.yml` 의 `cron: "0 0 * * 1"` 수정 (UTC 기준, 월요일 00:00 UTC = 09:00 KST)
- **순위 탐색 범위:** 같은 파일의 `MAX_RANK: "100"` 을 `"300"` 등으로 (최대 1000). 넓힐수록 호출이 늘지만 무료 한도엔 여유 충분.
- **중요키워드 직접 지정:** 자동 추출이 마음에 안 들면 `keywords.json` 에 `"글번호": "원하는 키워드"` 형식으로 지정. (글번호 = 글 주소 맨 뒤 숫자)

---

## 한계와 참고
- RSS 특성상 **최근 글** 위주로 점검합니다. 과거 글 전체까지 보려면 글 목록을 별도로 넣는 방식으로 확장이 필요해요(원하면 추가 가능).
- 키워드 자동 추출은 제목 앞쪽 핵심어를 고르는 방식이라 완벽하지 않습니다. 중요한 글은 `keywords.json` 으로 지정하는 것을 권장합니다.
- 네이버 공식 검색 API만 사용하므로 크롤링 차단·약관 문제가 없습니다.
