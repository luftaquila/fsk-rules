# FSK Rules

Formula Student Korea의 차량기술규정과 경기진행규정을 연도별 LaTeX 원본, PDF, 웹 문서로 관리하는 저장소입니다. 웹 빌드는 사람이 읽는 문서와 외부 서비스가 사용하는 안정적인 조항 인덱스를 함께 생성합니다.

## 저장 구조

```text
rules/
  catalog.json
  2026/
    formula-technical/
      rules.tex
      assets/
    formula-competition/
      rules.tex
      assets/
schemas/
  build-dependencies.schema.json
  source-catalog.schema.json
  rules-manifest.schema.json
  rules-index.schema.json
  rule-refs.schema.json
  document-release.schema.json
  site-release.schema.json
```

문서 ID는 `formula-technical`, `formula-competition` 두 가지입니다. 웹 빌드 결과는 `/<edition>/<document>/`에 놓이며, 각 문서 디렉터리에 `index.html`, LaTeX 빌드 PDF, `rules-index.json`이 함께 생성됩니다.

## 빌드

LuaLaTeX와 Python 3이 필요합니다. Pandoc과 빌드 폰트는 검증된 고정 버전을 사용합니다.

```sh
python -m pip install -r requirements.txt
python scripts/download_build_assets.py
make
make check
npm ci
npx playwright install --with-deps chromium # Ubuntu/Debian
npm run test:web
```

Rocky Linux 등 Playwright가 시스템 패키지 설치를 지원하지 않는 배포판에서는 Chromium 실행 라이브러리를 별도로 설치해야 합니다. GitHub Actions는 Ubuntu에서 위 의존성을 설치해 브라우저 테스트를 실행합니다.

PDF 도구가 없는 환경에서는 `make site-without-pdf`로 HTML과 JSON 계약만 검증할 수 있습니다. `make serve`를 실행하면 `http://localhost:8000`에서 결과를 확인할 수 있습니다.

## 연도별 갱신 절차

1. KSAE 공식 규정 PDF를 확인하고 새 연도의 두 문서 디렉터리를 만듭니다.
2. 공식 문서를 사람이 대조해 LaTeX와 이미지를 갱신합니다.
3. `rules/catalog.json`에 시행일, 게시물 ID, 공식 첨부 URL과 PDF SHA-256을 기록합니다.
4. PDF·웹·조항 인덱스를 빌드하고 테스트합니다.
5. 문서 입력이 바뀌었다면 해당 문서의 `revision`을 하나 올립니다. CI는 이전 Release와 비교해 이 규칙을 강제합니다.
6. `formula-technical-2026-v2` 또는 `formula-competition-2026-v2` 형식의 문서 태그로 PDF·웹·인덱스 Release를 만듭니다.
7. 현재 catalog의 모든 문서 Release가 준비되면 `site-YYYYMMDD-vN` 태그를 만들고 `github-pages` Environment 승인 후 운영에 반영합니다.

매일 실행되는 `Check official rule updates` 워크플로는 KSAE 게시판과 PDF 해시를 비교합니다. 변경을 발견해도 규정 본문을 자동 수정하지 않고, 검토용 이슈와 원문 PDF 아티팩트만 생성합니다. 동일 연도 URL은 최근 승인된 사이트 Release를 가리키며 이전 수정본은 GitHub Release에 보존됩니다. 상세한 버전 계약, 배포와 롤백 절차는 [릴리스 운영 가이드](docs/releases.md)를 따릅니다.

## 외부 서비스 연동

진입점은 `/rules-manifest.json`입니다. 즉시 v2 계약을 사용하며 v1 호환 계층은 제공하지 않습니다. `deployment.site_tag`과 `deployment.source_commit`으로 현재 운영본을 식별하고, 각 문서의 `revision`, `version`, `release_tag`, `document_digest`로 정확한 Release를 검증합니다. 원하는 `edition`과 `document`의 `index_path`를 찾은 뒤, 문서별 `rules-index.json`에서 `rule_key`, `id`, `citation`, `text`, `href`, `content_hash`를 사용합니다. 인덱스 스키마 버전은 2입니다.

```json
{
  "rule_key": "formula-technical.brake-light",
  "id": "formula-technical-10-9",
  "year": 2026,
  "edition": 2026,
  "document": "formula-technical",
  "citation": "제10조 9항",
  "text": "제동등 (Brake Light) …",
  "href": "#formula-technical-10-9",
  "content_hash": "sha256:..."
}
```

`rule_key`는 번호와 독립적인 영구 식별자입니다. 다음 연도에 조항 번호가 바뀌어도 같은 `rule_key`로 새 `id`, `citation`, `href`를 찾을 수 있습니다. `text`는 MathML의 화면 표현에서 만든 검색용 평문이며 LaTeX annotation을 포함하지 않습니다. `content_hash`는 내용 변경 여부를 판별합니다. URL은 매니페스트의 검증된 문서 경로와 인덱스의 `href`를 결합해 만들며 임의의 전체 URL을 데이터베이스에 저장하지 않습니다. 인덱스에 들어가는 모든 조항은 LaTeX에 `\label{rule:formula-technical.brake-light}` 형식의 영구 키를 갖습니다. 조항을 추가하면 키도 함께 추가하고, 한 번 Release된 키는 이름을 바꾸지 않습니다. 키 작성 규칙과 폐기 절차는 [연동 가이드](docs/rule-refs.md)를 따릅니다.

소비자 측 `sheet_template.rule_refs` 계약과 다음 연도 승계 규칙은 [연동 가이드](docs/rule-refs.md)에 정리되어 있습니다.

> 이 저장소의 문서는 검색과 열람 편의를 위한 편집본입니다. 해석 또는 불일치가 문제 되는 경우 KSAE 공식 게시물을 기준으로 확인하세요.
